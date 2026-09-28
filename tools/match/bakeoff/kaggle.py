"""The real M5.1 bake-off on Kaggle's free GPU, against the frozen answer key.

Cuts: TransNetV2, PySceneDetect (AutoShot has no reachable checkpoint).
Tags: Qwen3-VL-8B (4-bit), Qwen3-VL-4B, Gemma 3 4B, Gemma 4 E4B, each shown three
  frames per shot and asked for the full label set. (Florence-2 was dropped
  after three transformers incompatibilities; text_on_screen has passing VLMs.)
Theme: SigLIP 2, CLIP ViT-B/32, DINOv3 small.

The kernel records raw predictions only; `apply` scores them locally with
scoring.py and merges them with earlier runs, so `push --only theme` (or
`--models gemma4-e4b`) re-runs one job or model without paying for the rest.
`approve` is the explicit, human-triggered gate that writes config.yaml.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, ensure_dataset, fetch_output, kaggle_username, kernel_status,
    push_kernel, slugify, use_utf8_stdout, wait_dataset_ready, write_kernel_dir,
)
from tools.match.bakeoff import report, scoring  # noqa: E402
from tools.match.bakeoff.common import HERE, KEY_DIR, NEGATIVE_DIR  # noqa: E402

use_utf8_stdout()

MAX_NOTEBOOK_BYTES = 512 * 1024  # everything bulky rides in datasets, not inlined
BARS = {"cuts": 0.90, "tags": 0.85, "theme": 0.80}

NOTEBOOK_CODE = r"""# ESTA - M5.1 bake-off: run cut/tag/theme candidates and record their raw
# predictions. Scoring happens locally (tools/match/bakeoff/scoring.py).
import subprocess, sys, json, os, gc, glob, traceback, time

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "scenedetect[opencv]", "transnetv2-pytorch",
                "git+https://github.com/huggingface/transformers", "accelerate",
                "bitsandbytes", "einops", "timm"], check=False)

import numpy as np
import torch
import cv2
from PIL import Image

GT = json.loads(__GT__)
JOBS = set(__JOBS__)
MODELS = set(__MODELS__)
HF_TOKEN = __HF_TOKEN__
OUT = "/kaggle/working"
WORK = "/kaggle/temp"
MAX_SIDE = 448
os.makedirs(WORK, exist_ok=True)
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
os.environ["HF_HOME"] = "/kaggle/temp/hf"

def wanted(job, name):
    return job in JOBS and (not MODELS or name in MODELS)

def _resolve_input_dir(expected_slug, must_contain):
    # With 2+ datasets attached, Kaggle mounts them under
    # /kaggle/input/datasets/<owner>/<slug>/ rather than /kaggle/input/<slug>/.
    direct = os.path.join("/kaggle/input", expected_slug)
    if os.path.exists(os.path.join(direct, must_contain)):
        return direct
    hits = glob.glob(os.path.join("/kaggle/input", "**", must_contain), recursive=True)
    return os.path.dirname(hits[0]) if hits else direct

IN_VIDEOS = _resolve_input_dir(__IN_VIDEOS_SLUG__, __IN_VIDEOS_PROBE__)
IN_FRAMES = _resolve_input_dir(__IN_FRAMES_SLUG__, __IN_FRAMES_PROBE__)

# The T4 has no bf16 hardware: bf16 runs emulated and several times slower.
# fp16 is native, but some models (Gemma in particular) overflow in fp16, so a
# model is loaded fp16 first and reloaded bf16 if its first answers are garbage.
FAST = torch.float16 if torch.cuda.is_available() and not torch.cuda.is_bf16_supported() else torch.bfloat16

results = {"cuts": {}, "tags": {}, "theme": {}, "timing": {}, "errors": {}, "dtype": {}}

def finish():
    with open(os.path.join(OUT, "bakeoff_preds.json"), "w") as fh:
        json.dump(results, fh)
    print("ESTA_BAKEOFF_RESULT::" + json.dumps({"ok": True}))

def purge():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

def timed(key, t0):
    dur_min = sum(GT[s]["duration"] for s in GT) / 60
    secs = time.time() - t0
    results["timing"][key] = {"sec_per_min": secs / dur_min,
                              "gpu_min": secs / 60 if torch.cuda.is_available() else 0.0}

def video_path(slug):
    src = os.path.join(IN_VIDEOS, GT[slug]["video_file"])
    dst = os.path.join(WORK, GT[slug]["video_file"])
    if not os.path.exists(dst):
        import shutil
        shutil.copy(src, dst)
    return dst

# ============================== CUTS ==========================================
if wanted("cuts", "pyscenedetect"):
    t0 = time.time()
    try:
        from scenedetect import detect, AdaptiveDetector
        results["cuts"]["pyscenedetect"] = {
            slug: [sc[0].get_seconds() for sc in detect(video_path(slug), AdaptiveDetector())[1:]] for slug in GT}
        timed("cuts:pyscenedetect", t0)
    except Exception as e:
        results["errors"]["cuts:pyscenedetect"] = str(e)[:300]
        traceback.print_exc()
    finish()

if wanted("cuts", "transnetv2"):
    t0 = time.time()
    try:
        import csv
        preds = {}
        for slug in GT:
            out_csv = os.path.join(WORK, slug + "_tn2.csv")
            r = subprocess.run(["transnetv2_pytorch", video_path(slug), "--output", out_csv, "--quiet"],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0 or not os.path.exists(out_csv):
                raise RuntimeError("transnetv2_pytorch failed: " + (r.stderr or r.stdout)[-300:])
            with open(out_csv, newline="") as fh:
                rows = list(csv.DictReader(fh))
            preds[slug] = [round(float(row["end_time"]), 3) for row in rows[:-1]]
        results["cuts"]["transnetv2"] = preds
        timed("cuts:transnetv2", t0)
    except Exception as e:
        results["errors"]["cuts:transnetv2"] = str(e)[:300]
        traceback.print_exc()
    purge()
    finish()

# ============================== SHOTS =========================================
# Shot i spans cuts[i-1]..cuts[i]. Three frames per shot (one keyframe can't
# show whether a shot moves), downscaled so a VLM spends few tokens on each,
# plus a measured motion level the prompt passes on as a hint.
def shot_frames(slug, shot_id):
    cuts = GT[slug]["cuts"]
    i = int(shot_id)
    a, b = cuts[i - 1], cuts[i]
    cap = cv2.VideoCapture(video_path(slug))
    def grab(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        return img if ok else None
    frames = []
    for f in (0.2, 0.5, 0.8):
        img = grab(a + (b - a) * f)
        if img is not None:
            h, w = img.shape[:2]
            k = MAX_SIDE / max(h, w)
            frames.append(Image.fromarray(cv2.cvtColor(cv2.resize(img, (int(w * k), int(h * k))), cv2.COLOR_BGR2RGB)))
    grays = []
    for k in range(8):
        img = grab(a + (b - a) * (0.05 + 0.9 * k / 7))
        if img is not None:
            grays.append(cv2.cvtColor(cv2.resize(img, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32))
    cap.release()
    motion = float(np.mean([np.abs(x - y).mean() for x, y in zip(grays, grays[1:])])) if len(grays) > 1 else 0.0
    return frames, motion

SHOTS = []  # (key, frames, motion)
if "tags" in JOBS:
    for slug, v in GT.items():
        for s in v["shots"]:
            try:
                frames, motion = shot_frames(slug, s["shot_id"])
                if frames:
                    SHOTS.append((f"{slug}/{s['shot_id']}", frames, motion))
            except Exception as e:
                results["errors"][f"frames:{slug}/{s['shot_id']}"] = str(e)[:200]
    results["motion"] = {k: m for k, _, m in SHOTS}

PROMPT = (
    "These are 3 frames (start, middle, end) from ONE shot of an edited short-form video. "
    "Measured motion across the shot: {motion}. Reply with ONLY a JSON object:\n"
    '{{"kind": one of ["footage","still","graphic","talking_head","meme"], '
    '"text_on_screen": true/false, "panels": 1, 2 or 3, "overlay": true/false, '
    '"clips_in_shot": integer}}\n'
    "kind: footage = real camera footage, screen recording or game capture; "
    "still = a photo or screenshot shown without its own motion (a slow zoom or pan on it is still a still); "
    "graphic = motion graphic, animated text card, chart or title card; "
    "talking_head = a person speaking to camera; meme = meme template or reaction clip. "
    "text_on_screen = any readable words or numbers on screen, captions included. "
    "panels = how many separate pictures share the frame side by side or stacked (3 = 3 or more). "
    "overlay = a graphic, sticker or text card floating over footage. "
    "clips_in_shot = how many different source clips appear within this one shot."
)

def motion_word(m):
    return "none" if m < 1.0 else "low" if m < 4.0 else "high"

def parse_label_json(text):
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return {"kind": str(obj.get("kind", "")).strip().lower(),
                "text_on_screen": bool(obj.get("text_on_screen", False)),
                "panels": int(obj.get("panels", 1)), "overlay": bool(obj.get("overlay", False)),
                "clips_in_shot": int(obj.get("clips_in_shot", 1))}
    except Exception:
        return None

def run_vlm(load, ask):
    # load(dtype) -> (model, processor); ask(model, processor, frames, prompt) -> text.
    preds = {}
    for dtype in (FAST, torch.bfloat16) if FAST != torch.bfloat16 else (torch.bfloat16,):
        model, processor = load(dtype)
        preds = {}
        for n, (key, frames, motion) in enumerate(SHOTS):
            preds[key] = parse_label_json(ask(model, processor, frames, PROMPT.format(motion=motion_word(motion))))
            # fp16 overflow shows up as unparseable output from the start; retry in bf16.
            if n == 3 and dtype != torch.bfloat16 and sum(p is None for p in preds.values()) >= 3:
                break
        else:
            del model
            purge()
            return preds, str(dtype)
        del model
        purge()
    return preds, "bfloat16"

def chat_ask(model, processor, frames, prompt):
    messages = [{"role": "user", "content": [*({"type": "image", "image": f} for f in frames),
                                              {"type": "text", "text": prompt}]}]
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                           return_tensors="pt", return_dict=True).to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=80, do_sample=False)
    return processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

def qwen_loader(model_id, four_bit=False):
    def load(dtype):
        from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
        kw = dict(dtype=dtype, device_map="auto")
        if four_bit:
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=dtype)
        processor = AutoProcessor.from_pretrained(model_id)
        return Qwen3VLForConditionalGeneration.from_pretrained(model_id, **kw), processor
    return load

def auto_loader(model_id, **proc_kw):
    def load(dtype):
        from transformers import AutoModelForImageTextToText, AutoProcessor
        processor = AutoProcessor.from_pretrained(model_id, **proc_kw)
        return AutoModelForImageTextToText.from_pretrained(model_id, dtype=dtype, device_map="auto"), processor
    return load

TAGGERS = [
    ("qwen3-vl-8b", qwen_loader("Qwen/Qwen3-VL-8B-Instruct", four_bit=True)),
    ("qwen3-vl-4b", qwen_loader("Qwen/Qwen3-VL-4B-Instruct")),
    ("gemma3-4b", auto_loader("google/gemma-3-4b-it")),
    ("gemma4-e4b", auto_loader("google/gemma-4-E4B-it", padding_side="left")),
]
for name, load in TAGGERS:
    if not wanted("tags", name):
        continue
    t0 = time.time()
    try:
        preds, used = run_vlm(load, chat_ask)
        results["tags"][name] = preds
        results["dtype"][name] = used
        timed("tags:" + name, t0)
    except Exception as e:
        results["errors"]["tags:" + name] = str(e)[:300]
        traceback.print_exc()
    purge()
    finish()

# ============================== THEME =========================================
def image_embedding(out):
    # Newer transformers return a ModelOutput from get_image_features; the
    # embedding is its pooler_output (projected), not the per-patch states.
    if isinstance(out, torch.Tensor):
        return out[0]
    pooled = getattr(out, "pooler_output", None)
    return pooled[0] if pooled is not None else out.last_hidden_state[0].mean(dim=0)

def theme_sims(embed):
    pos = [p for p in sorted(glob.glob(os.path.join(IN_FRAMES, "*__shot_*.jpg"))) if not os.path.basename(p).startswith("negative__")]
    neg = sorted(glob.glob(os.path.join(IN_FRAMES, "negative__*.jpg")))
    def norm(v):
        v = v.float().cpu().numpy().reshape(-1)
        return v / (np.linalg.norm(v) + 1e-9)
    pe = np.stack([norm(embed(Image.open(p).convert("RGB"))) for p in pos])
    ne = np.stack([norm(embed(Image.open(p).convert("RGB"))) for p in neg])
    # Leave-one-out centroid, so a frame isn't scored against itself.
    total = pe.sum(axis=0)
    pos_sims = [float(v @ ((total - v) / (np.linalg.norm(total - v) + 1e-9))) for v in pe]
    centroid = total / (np.linalg.norm(total) + 1e-9)
    return {"pos": pos_sims, "neg": [float(v @ centroid) for v in ne]}

def hf_image_embedder(model_cls, proc_cls, model_id, via_features=True):
    import transformers
    processor = getattr(transformers, proc_cls).from_pretrained(model_id)
    model = getattr(transformers, model_cls).from_pretrained(model_id).to(
        "cuda" if torch.cuda.is_available() else "cpu").eval()
    def embed(img):
        inputs = processor(images=[img], return_tensors="pt").to(model.device)
        with torch.no_grad():
            return image_embedding(model.get_image_features(**inputs) if via_features else model(**inputs))
    return model, embed

EMBEDDERS = [
    ("siglip2", ("AutoModel", "AutoProcessor", "google/siglip2-base-patch16-224", True)),
    ("clip-vit-b32", ("CLIPModel", "CLIPProcessor", "openai/clip-vit-base-patch32", True)),
    ("dinov3-small", ("AutoModel", "AutoImageProcessor", "facebook/dinov3-convnext-small-pretrain-lvd1689m", False)),
]
for name, spec in EMBEDDERS:
    if not wanted("theme", name):
        continue
    t0 = time.time()
    try:
        model, embed = hf_image_embedder(*spec)
        results["theme"][name] = theme_sims(embed)
        del model
        timed("theme:" + name, t0)
    except Exception as e:
        results["errors"]["theme:" + name] = str(e)[:300]
        traceback.print_exc()
    purge()
    finish()

finish()
print("ESTA_BAKEOFF_DONE")
"""


def _load_gt() -> dict:
    gt = {}
    for vdir in sorted(KEY_DIR.iterdir()):
        if not vdir.is_dir() or vdir.name == "negative_style":
            continue
        cuts = json.loads((vdir / "cuts.json").read_text(encoding="utf-8"))
        shots = json.loads((vdir / "shots.json").read_text(encoding="utf-8"))
        meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
        gt[vdir.name] = {"cuts": cuts["cuts"], "duration": meta["duration"],
                        "video_file": Path(meta["path"]).name, "shots": shots}
    return gt


def _state_path() -> Path:
    return HERE / "bakeoff_kernel.json"


JOBS = ("cuts", "tags", "theme")


def cmd_push(args: argparse.Namespace) -> None:
    jobs = [j.strip() for j in args.only.split(",") if j.strip()] or list(JOBS)
    unknown = set(jobs) - set(JOBS)
    if unknown:
        raise ValueError(f"unknown job(s) {sorted(unknown)}; choose from {JOBS}")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    frozen = KEY_DIR / "frozen.json"
    if not frozen.exists():
        raise RuntimeError("answer key is not frozen — run key_build.py freeze first")

    gt = _load_gt()
    if not gt:
        raise RuntimeError("no ground truth found under key/")

    # Reuse the same raw-video dataset candidates.py already uploaded.
    videos_dataset = f"{kaggle_username()}/{slugify('esta-bakeoff-cuts-data')}"

    # Frames dataset: shot keyframes + negative pool, built fresh each push so it
    # always matches the current (possibly corrected) shots.json. Flat filenames,
    # not subdirectories — `kaggle datasets create` silently skips nested folders
    # without an explicit --dir-mode, which kaggle_lane.py's ensure_dataset doesn't pass.
    frames_build = HERE / "frames_dataset_build"
    if frames_build.exists():
        import shutil
        shutil.rmtree(frames_build)
    frames_build.mkdir(parents=True, exist_ok=True)
    for slug in gt:
        for s in gt[slug]["shots"]:
            src = KEY_DIR / slug / "shot_frames" / f"shot_{int(s['shot_id']):03d}.jpg"
            if src.exists():
                (frames_build / f"{slug}__{src.name}").write_bytes(src.read_bytes())
    for f in (NEGATIVE_DIR / "frames").glob("*.jpg"):
        (frames_build / f"negative__{f.name}").write_bytes(f.read_bytes())

    frames_dataset = f"{kaggle_username()}/{slugify('esta-bakeoff-frames-data')}"
    ok, log = ensure_dataset(frames_build, frames_dataset, frames_dataset.split("/", 1)[-1])
    if not ok:
        raise RuntimeError(f"frames dataset upload failed: {log}")
    if not wait_dataset_ready(frames_dataset):
        raise RuntimeError("frames dataset never reached ready state")

    # HF_TOKEN in the environment (a cloud session's secret) wins over config.yaml.
    hf_token = os.environ.get("HF_TOKEN", "")
    try:
        import yaml
        cfg = yaml.safe_load((HERE.parents[2] / "config.yaml").read_text(encoding="utf-8"))
        hf_token = hf_token or (cfg.get("apis", {}) or {}).get("hf_token", "") or ""
    except Exception:
        pass

    first_slug = next(iter(gt))
    any_video = gt[first_slug]["video_file"]
    any_shot_id = int(gt[first_slug]["shots"][0]["shot_id"])
    any_frame = f"{first_slug}__shot_{any_shot_id:03d}.jpg"
    code = (
        NOTEBOOK_CODE
        .replace("__GT__", repr(json.dumps(gt)))
        .replace("__IN_VIDEOS_SLUG__", repr(videos_dataset.split("/", 1)[-1]))
        .replace("__IN_VIDEOS_PROBE__", repr(any_video))
        .replace("__IN_FRAMES_SLUG__", repr(frames_dataset.split("/", 1)[-1]))
        .replace("__IN_FRAMES_PROBE__", repr(any_frame))
        .replace("__HF_TOKEN__", repr(hf_token))
        .replace("__JOBS__", repr(jobs))
        .replace("__MODELS__", repr(models))
    )

    kernel_id = f"{kaggle_username()}/{slugify('esta-bakeoff-main-kernel')}"
    kernel_build = HERE / "bakeoff_kernel_build"
    nb_path = write_kernel_dir(kernel_build, code, kernel_id, ACCELERATORS["t4"])
    (kernel_build / "kernel-metadata.json").write_text(
        json.dumps({
            **json.loads((kernel_build / "kernel-metadata.json").read_text(encoding="utf-8")),
            "dataset_sources": [videos_dataset, frames_dataset],
        }, indent=2), encoding="utf-8")

    size = nb_path.stat().st_size
    if size > MAX_NOTEBOOK_BYTES:
        raise ValueError(f"notebook is {size / 1e6:.1f} MB — over the {MAX_NOTEBOOK_BYTES / 1e6:.1f} MB ceiling")

    ok, log = push_kernel(kernel_build)
    state = {"kernel": kernel_id, "videos_dataset": videos_dataset, "frames_dataset": frames_dataset,
             "jobs": jobs, "models": models}
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps({"ok": ok, "kernel": kernel_id, "jobs": jobs, "models": models,
                      "url": f"https://www.kaggle.com/code/{kernel_id}",
                      "log": log[-400:]}, ensure_ascii=False))


def _kernel_ref(explicit: str) -> str:
    if explicit:
        return explicit
    state = _state_path()
    if state.exists():
        ref = json.loads(state.read_text(encoding="utf-8")).get("kernel", "")
        if ref:
            return ref
    return f"{kaggle_username()}/{slugify('esta-bakeoff-main-kernel')}"


def cmd_status(args: argparse.Namespace) -> None:
    ref = _kernel_ref(args.kernel)
    state, raw = kernel_status(ref)
    print(json.dumps({"ok": bool(state), "kernel": ref, "state": state, "raw": raw}, ensure_ascii=False))


def _pick_winner(scores: dict, bar: float) -> tuple[str, str]:
    passing = {k: v for k, v in scores.items() if v >= bar}
    if not passing:
        return "", "no candidate cleared the bar"
    winner = max(passing, key=passing.get)
    return winner, f"highest score ({passing[winner]:.3f}) among candidates clearing {bar}"


MERGED = HERE / "bakeoff_out" / "bakeoff_preds_all.json"


def _merge(raw: dict) -> dict:
    """Newer runs replace a candidate's predictions; candidates a run didn't
    include keep their earlier ones."""
    merged = json.loads(MERGED.read_text(encoding="utf-8")) if MERGED.exists() else {}
    for section in ("cuts", "tags", "theme", "timing", "dtype", "motion"):
        merged.setdefault(section, {}).update(raw.get(section, {}))
    ran = set(raw.get("cuts", {})) | set(raw.get("tags", {})) | set(raw.get("theme", {}))
    errors = {k: v for k, v in merged.get("errors", {}).items() if k.split(":", 1)[-1] not in ran}
    merged["errors"] = {**errors, **raw.get("errors", {})}
    MERGED.write_text(json.dumps(merged), encoding="utf-8")
    return merged


def _score(preds: dict, gt: dict) -> dict:
    timing = preds.get("timing", {})
    t = lambda key: {"sec_per_min": timing.get(key, {}).get("sec_per_min", 0), "gpu_min": timing.get(key, {}).get("gpu_min", 0)}
    gt_cuts = {slug: v["cuts"][1:-1] for slug, v in gt.items()}
    cuts = {}
    for name, by_slug in preds.get("cuts", {}).items():
        weights = {slug: len(gt_cuts[slug]) for slug in gt}
        f1 = sum(scoring.f1_cuts(by_slug.get(slug, []), gt_cuts[slug]) * w for slug, w in weights.items())
        cuts[name] = {"score": f1 / (sum(weights.values()) or 1), **t("cuts:" + name)}
    tags = {name: {**scoring.score_tags(p, gt), **t("tags:" + name), "dtype": preds.get("dtype", {}).get(name, "")}
            for name, p in preds.get("tags", {}).items()}
    theme = {name: {"score": scoring.auc(v["pos"], v["neg"]), **t("theme:" + name)}
             for name, v in preds.get("theme", {}).items()}
    return {"cuts": cuts, "tags": tags, "theme": theme}


def _tag_score(field: str, sc: dict) -> float:
    # kind has five classes: balanced accuracy is its mean per-class recall.
    return sc["balanced_accuracy"] if sc.get("testable") else 0.0


def cmd_apply(args: argparse.Namespace) -> None:
    ref = _kernel_ref(args.kernel)
    out_dir = Path(args.output_dir) if args.output_dir else HERE / "bakeoff_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_download:
        fetch_output(ref, out_dir)
    preds_path = out_dir / "bakeoff_preds.json"
    if not preds_path.exists():
        raise FileNotFoundError(f"no bakeoff_preds.json in {out_dir} — check `status` first")
    merged = _merge(json.loads(preds_path.read_text(encoding="utf-8")))
    gt = _load_gt()
    scored = _score(merged, gt)

    report.start_fresh({"kernel": ref, "errors": merged.get("errors", {})})
    report.write_label_counts(scoring.label_counts(gt))

    winners = {}
    cuts_scores = {k: v["score"] for k, v in scored["cuts"].items()}
    winners["cuts"], why = _pick_winner(cuts_scores, BARS["cuts"])
    report.write_job_table("Cuts", "F1", BARS["cuts"],
                           [{"candidate": k, **v} for k, v in scored["cuts"].items()], winners["cuts"], why)

    tag_winners = {}
    for field in scoring.TAG_FIELDS:
        per_model = {k: v["fields"][field] for k, v in scored["tags"].items()}
        field_scores = {k: _tag_score(field, sc) for k, sc in per_model.items()}
        winner, why = _pick_winner(field_scores, BARS["tags"])
        untestable = [sc.get("reason") for sc in per_model.values() if not sc.get("testable")]
        if untestable and not any(sc.get("testable") for sc in per_model.values()):
            why = f"not testable: {untestable[0]}"
        rows = [{"candidate": k, "score": field_scores[k], "accuracy": sc.get("accuracy", 0),
                 "baseline": sc.get("baseline", 0), "support": sc.get("n", 0),
                 "sec_per_min": scored["tags"][k]["sec_per_min"], "gpu_min": scored["tags"][k]["gpu_min"]}
                for k, sc in per_model.items()]
        report.write_tag_table(field, BARS["tags"], rows, winner, why)
        if winner:
            tag_winners[field] = winner

    theme_scores = {k: v["score"] for k, v in scored["theme"].items()}
    winners["theme"], why = _pick_winner(theme_scores, BARS["theme"])
    report.write_job_table("Theme embeddings", "AUC", BARS["theme"],
                           [{"candidate": k, **v} for k, v in scored["theme"].items()], winners["theme"], why)

    summary = {"cuts_winner": winners["cuts"], "tag_winners": tag_winners, "theme_winner": winners["theme"],
               "scored": scored, "errors": merged.get("errors", {})}
    (HERE / "bakeoff_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "kernel": ref, "cuts_winner": winners["cuts"], "tag_winners": tag_winners,
                      "theme_winner": winners["theme"], "results_md": str(report.RESULTS_PATH)}, ensure_ascii=False))


def cmd_labels(args: argparse.Namespace) -> None:
    print(json.dumps(scoring.label_counts(_load_gt()), indent=2))


def cmd_approve(args: argparse.Namespace) -> None:
    summary_path = HERE / "bakeoff_summary.json"
    if not summary_path.exists():
        raise RuntimeError("no bakeoff_summary.json — run `apply` first")
    scored = json.loads(summary_path.read_text(encoding="utf-8"))["scored"]
    dropped = set(t.strip() for t in args.drop_tag.split(",") if t.strip())

    def check(job: str, name: str, score: float, bar: float) -> None:
        if score < bar and job not in dropped:
            raise ValueError(f"{job}={name} scored {score:.3f}, below bar {bar} — pass --drop-tag {job} to accept anyway")

    winners = {}
    if args.cuts:
        check("cuts", args.cuts, scored["cuts"].get(args.cuts, {}).get("score", 0), BARS["cuts"])
        winners["cuts"] = args.cuts
    if args.theme:
        check("theme", args.theme, scored["theme"].get(args.theme, {}).get("score", 0), BARS["theme"])
        winners["theme"] = args.theme
    for pair in args.tags.split(","):
        if not pair.strip():
            continue
        field, model = (x.strip() for x in pair.split("=", 1))
        sc = scored["tags"].get(model, {}).get("fields", {}).get(field, {})
        check(field, model, _tag_score(field, sc), BARS["tags"])
        winners[field] = model

    config_path = HERE.parents[2] / "config.yaml"
    import yaml
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("match", {})["models"] = winners
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    report.append_writeback_log(winners, datetime.now(timezone.utc).isoformat(), sorted(dropped))
    print(json.dumps({"ok": True, "winners": winners, "dropped": sorted(dropped)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="The real M5.1 bake-off, scored against the frozen answer key")
    sub = parser.add_subparsers(dest="mode", required=True)

    pu = sub.add_parser("push")
    pu.add_argument("--only", default="", help="Comma-separated jobs to run: cuts,tags,theme (default all)")
    pu.add_argument("--models", default="", help="Comma-separated candidate names to run (default all)")

    sub.add_parser("labels", help="Print the answer key's label counts per tag field")

    s = sub.add_parser("status")
    s.add_argument("--kernel", default="")

    a = sub.add_parser("apply")
    a.add_argument("--kernel", default="")
    a.add_argument("--output-dir", default="")
    a.add_argument("--skip-download", action="store_true")

    ap = sub.add_parser("approve")
    ap.add_argument("--cuts", default="")
    ap.add_argument("--theme", default="")
    ap.add_argument("--tags", default="", help="field=model,field=model,...")
    ap.add_argument("--drop-tag", default="", help="Comma-separated fields to accept below bar")

    args = parser.parse_args()
    try:
        {"push": cmd_push, "status": cmd_status, "apply": cmd_apply, "labels": cmd_labels,
         "approve": cmd_approve}[args.mode](args)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
