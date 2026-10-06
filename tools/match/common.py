"""Shared pieces of the M5 inspo match: config, kind groups, keyframes, colour
statistics, embeddings and cut detection.

Runs on the system python, not `esta`: `esta` pins transformers 4.33 for XTTS,
which predates DINOv3 and SigLIP 2 (see SPEC.md, revisions of 2026-09-29).
"""

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "cache" / "inspo"
ESTA_PYTHON = Path(os.environ.get("ESTA_PYTHON", Path.home() / ".conda" / "envs" / "esta" / "python.exe"))

DEFAULT_MATCH = {
    "weights": {"a": 1, "b": 1, "c": 1, "d": 1, "e": 2},
    "pass_overall": 80,
    "pass_section": 70,
    "max_rounds": 8,
    "min_gain": 1.0,
    # The describe lane answers footage/still/graphic only, so meme folds into footage.
    "kind_classes": 3,
    "models": {"cuts": "transnetv2", "theme": "dinov3-small", "text_image": "siglip2",
               "tags": "haiku"},
    "dropped_tags": ["panels", "clips_in_shot"],
    "describe": {"model": "haiku", "batch": 10, "workers": 4, "max_side": 384},
}

# Without these every `claude -p` call carries ~29k tokens of MCP tool
# definitions and skills: 7x the cost of the work itself (describe bake-off).
LEAN_CLAUDE = ["--strict-mcp-config", "--setting-sources", "", "--tools", "", "--max-turns", "1"]

MODEL_IDS = {
    "dinov3-small": "facebook/dinov3-convnext-small-pretrain-lvd1689m",
    "siglip2": "google/siglip2-base-patch16-224",
    "gemma4-e4b": "google/gemma-4-E4B-it",
    "qwen3-vl-8b": "Qwen/Qwen3-VL-8B-Instruct",
}

PLAN_KIND = {"REAL_FOOTAGE": "footage", "AI_VIDEO": "footage", "REAL_IMAGE": "still",
             "MOTION_GRAPHICS": "graphic"}
# Fine tag kinds -> the classes plan and final can both express.
# `screen` joins graphic: the plan has no screen type, and Gemma reads terminal
# and UI cards (built as MOTION_GRAPHICS) as screens.
KIND_GROUPS = {
    4: {"footage": "footage", "talking_head": "footage", "screen": "graphic", "ai": "footage",
        "still": "still", "graphic": "graphic", "meme": "meme"},
    3: {"footage": "footage", "talking_head": "footage", "screen": "graphic", "ai": "footage",
        "still": "still", "graphic": "graphic", "meme": "footage"},
}


def load_config() -> dict:
    import yaml
    return yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}


def match_config() -> dict:
    cfg = (load_config().get("match") or {})
    out = json.loads(json.dumps(DEFAULT_MATCH))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def hf_login() -> None:
    token = (load_config().get("apis") or {}).get("hf_token") or ""
    if token:
        os.environ.setdefault("HF_TOKEN", token)
    # With the weights cached, the hub's freshness checks only add failure
    # points: on a flaky connection one load took 25 minutes of retries.
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    cached = [hub / f"models--{MODEL_IDS[m].replace('/', '--')}" for m in ("dinov3-small", "siglip2")]
    if all(p.exists() for p in cached):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")


def kind_group(fine: str, classes: int) -> str:
    return KIND_GROUPS[classes].get(str(fine).lower(), "footage")


def plan_kind(shot: dict, classes: int) -> str:
    v = shot.get("visual") or {}
    comp = shot.get("composite") or {}
    slots = comp.get("slots") or []
    typ = (slots[0].get("type") if slots and slots[0].get("type") else v.get("type")) or "REAL_FOOTAGE"
    if shot.get("generate") or typ == "AI_VIDEO":
        return "footage"
    kind = PLAN_KIND.get(typ, "footage")
    if classes == 4 and kind != "graphic":
        lead = ((v.get("search_sources") or [{}])[0] or {}).get("source", "")
        if lead == "giphy":
            return "meme"
    return kind


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(p: Path, data) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Video ────────────────────────────────────────────────────────────────────

def probe(video: Path) -> tuple[float, float]:
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    return (frames / fps if fps else 0.0), fps


def frames_at(video: Path, times: list[float], max_side: int = 0):
    """RGB uint8 arrays at the given seconds (missing frames skipped)."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(t * fps)))
        ok, frame = cap.read()
        if ok:
            # Hundreds of 4K frames held at full size exhaust RAM; the embedders downscale anyway.
            scale = max_side / max(frame.shape[:2]) if max_side else 1.0
            if scale < 1.0:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            out.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    return out


def image_rgb(path: Path):
    from PIL import Image
    import numpy as np
    with Image.open(path) as im:
        im.seek(0)
        return np.asarray(im.convert("RGB"))


def media_frames(path: Path, in_point: float = 0.0, out_point: float = 0.0, n: int = 3, max_side: int = 0):
    """Keyframes of a clip window, or the image itself."""
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return [image_rgb(path)]
    dur, _ = probe(Path(path))
    lo = max(0.0, in_point or 0.0)
    hi = out_point if out_point and out_point > lo else dur
    hi = min(hi, dur) if dur else hi
    if hi <= lo:
        hi = lo + 0.1
    times = [lo + (hi - lo) * (k + 0.5) / n for k in range(n)]
    return frames_at(Path(path), times, max_side)


def save_jpg(arr, path: Path, max_side: int = 640) -> Path:
    from PIL import Image
    im = Image.fromarray(arr)
    im.thumbnail((max_side, max_side))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=88)
    return path


# ── Colour ───────────────────────────────────────────────────────────────────

COLOUR_FEATURES = ["L_mean", "L_std", "chroma", "a_mean", "b_mean", "colourfulness"]


def crop_content(frame):
    """The picture inside letterbox or pillarbox bars. Inspos often float footage
    on a black field; measured whole, the bars would read as a dark grade and the
    colour adjust would crush our footage to match. Frames that are black by design
    (terminal cards) have no mostly-lit rows and stay whole."""
    import numpy as np
    lit = frame.max(axis=2) > 30
    rows = np.where(lit.mean(axis=1) > 0.6)[0]
    if len(rows) < 0.1 * frame.shape[0]:
        return frame
    band = frame[rows.min(): rows.max() + 1]
    cols = np.where((band.max(axis=2) > 30).mean(axis=0) > 0.6)[0]
    return band[:, cols.min(): cols.max() + 1] if len(cols) >= 0.1 * frame.shape[1] else band


def colour_features(frames) -> dict:
    """CIELAB statistics (L* 0-100) plus Hasler-Susstrunk colourfulness, mean over frames."""
    import cv2
    import numpy as np
    acc = {k: [] for k in COLOUR_FEATURES}
    for f in frames:
        f = crop_content(f)
        small = cv2.resize(f, (160, max(1, int(160 * f.shape[0] / max(f.shape[1], 1)))))
        lab = cv2.cvtColor(small.astype("float32") / 255.0, cv2.COLOR_RGB2LAB)
        L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
        rgb = small.astype("float32")
        rg = rgb[..., 0] - rgb[..., 1]
        yb = 0.5 * (rgb[..., 0] + rgb[..., 1]) - rgb[..., 2]
        acc["L_mean"].append(float(L.mean()))
        acc["L_std"].append(float(L.std()))
        acc["chroma"].append(float(np.sqrt(a ** 2 + b ** 2).mean()))
        acc["a_mean"].append(float(a.mean()))
        acc["b_mean"].append(float(b.mean()))
        acc["colourfulness"].append(float(math.hypot(rg.std(), yb.std()) + 0.3 * math.hypot(rg.mean(), yb.mean())))
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in acc.items()}


# ── Embeddings ───────────────────────────────────────────────────────────────

class Embedder:
    """DINOv3 (image-image, inspo look) and SigLIP 2 (text-image), loaded lazily."""

    def __init__(self):
        hf_login()
        import torch
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._dino = None
        self._siglip = None

    def _load_dino(self):
        if self._dino is None:
            from transformers import AutoImageProcessor, AutoModel
            mid = MODEL_IDS["dinov3-small"]
            self._dino = (AutoImageProcessor.from_pretrained(mid),
                          AutoModel.from_pretrained(mid).to(self.device).eval())
        return self._dino

    def _load_siglip(self):
        if self._siglip is None:
            from transformers import AutoModel, AutoProcessor
            mid = MODEL_IDS["siglip2"]
            self._siglip = (AutoProcessor.from_pretrained(mid),
                            AutoModel.from_pretrained(mid).to(self.device).eval())
        return self._siglip

    @staticmethod
    def _norm(x):
        import numpy as np
        x = np.asarray(x, dtype="float32")
        while x.ndim > 2:
            x = x.mean(axis=1)
        return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)

    def _pil(self, frames):
        from PIL import Image
        return [Image.fromarray(f) if not hasattr(f, "convert") else f.convert("RGB") for f in frames]

    def dino(self, frames, batch: int = 16):
        import numpy as np
        proc, model = self._load_dino()
        out = []
        pils = self._pil(frames)
        for i in range(0, len(pils), batch):
            inputs = proc(images=pils[i:i + batch], return_tensors="pt").to(self.device)
            with self.torch.no_grad():
                res = model(**inputs)
            pooled = getattr(res, "pooler_output", None)
            if pooled is None:
                pooled = res.last_hidden_state.mean(dim=1)
            out.append(pooled.float().cpu().numpy())
        return self._norm(np.concatenate(out)) if out else np.zeros((0, 768), "float32")

    def siglip_images(self, frames, batch: int = 16):
        import numpy as np
        proc, model = self._load_siglip()
        out = []
        pils = self._pil(frames)
        for i in range(0, len(pils), batch):
            inputs = proc(images=pils[i:i + batch], return_tensors="pt").to(self.device)
            with self.torch.no_grad():
                feat = model.get_image_features(**inputs)
            feat = getattr(feat, "pooler_output", feat)
            out.append(feat.float().cpu().numpy())
        return self._norm(np.concatenate(out)) if out else np.zeros((0, 768), "float32")

    def siglip_texts(self, texts: list[str]):
        import numpy as np
        proc, model = self._load_siglip()
        # SigLIP 2 was trained on lowercase text padded to 64 tokens.
        inputs = proc(text=[t.lower() for t in texts], padding="max_length", max_length=64,
                      truncation=True, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            feat = model.get_text_features(**inputs)
        feat = getattr(feat, "pooler_output", feat)
        return self._norm(feat.float().cpu().numpy()) if len(texts) else np.zeros((0, 768), "float32")


# ── Cuts ─────────────────────────────────────────────────────────────────────

def detect_cuts(video: Path) -> list[float]:
    """Shot boundaries [0, c1, ..., duration] from TransNetV2; shots under 2 frames merge."""
    dur, fps = probe(video)
    with tempfile.TemporaryDirectory() as tmp:
        out_csv = Path(tmp) / "cuts.csv"
        r = subprocess.run(["transnetv2_pytorch", str(video), "--output", str(out_csv), "--quiet",
                            "--no-progress-bar"], capture_output=True, text=True, timeout=3600)
        if r.returncode != 0 or not out_csv.exists():
            raise RuntimeError("transnetv2_pytorch failed: " + (r.stderr or r.stdout)[-400:])
        with open(out_csv, newline="") as fh:
            rows = list(csv.DictReader(fh))
    cuts = [round(float(row["end_time"]), 3) for row in rows[:-1]]
    bounds = [0.0]
    min_len = 2.0 / (fps or 25.0)
    for c in cuts:
        if c - bounds[-1] >= min_len and dur - c >= min_len:
            bounds.append(c)
    bounds.append(round(dur, 3))
    return bounds


def claude_bin() -> str:
    for p in (os.environ.get("CLAUDE_BIN"), os.environ.get("CLAUDE_CODE_EXECPATH"),
              str(Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")):
        if p and Path(p).exists():
            return p
    return "claude"


def run_esta(args: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run([str(ESTA_PYTHON), *args], cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def utf8_stdout() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
