"""The real M5.1 bake-off: score every candidate model against the frozen answer
key, on Kaggle's free GPU. Three jobs, all in one kernel — see the module docstring
in candidates.py for why sequencing four VLMs + three embedders on a 16GB T4 is
the real risk here, not total GPU-time.

Cuts: TransNetV2, PySceneDetect (AutoShot skipped — see candidates.py).
Tags: Qwen3-VL-8B (4-bit), Qwen3-VL-4B, Gemma3-4B (all chat-prompted for the full
  label set), Florence-2-large (OCR task prompt, text_on_screen only).
Theme: SigLIP2, CLIP ViT-B/32, DINOv3-small (centroid-cosine-similarity AUC of
  our shots vs the negative-style pool).

Same push/status/apply shape as genvideo/candidates.py, plus `approve` — the
explicit, human-triggered gate that writes config.yaml (never automatic).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, ensure_dataset, fetch_output, kaggle_username, kernel_status,
    push_kernel, slugify, use_utf8_stdout, wait_dataset_ready, write_kernel_dir,
)
from tools.match.bakeoff import report  # noqa: E402
from tools.match.bakeoff.common import HERE, KEY_DIR, NEGATIVE_DIR  # noqa: E402

use_utf8_stdout()

MAX_NOTEBOOK_BYTES = 512 * 1024  # everything bulky rides in datasets, not inlined
BARS = {"cuts": 0.90, "tags": 0.85, "theme": 0.80}

NOTEBOOK_CODE = r'''# ESTA - M5.1 bake-off: score cut/tag/theme candidates against the frozen answer key.
import subprocess, sys, json, os, gc, glob, traceback, time

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "scenedetect[opencv]", "transnetv2-pytorch", "scikit-learn",
                "git+https://github.com/huggingface/transformers", "accelerate",
                "bitsandbytes", "einops", "timm"], check=False)

import numpy as np
import torch
from sklearn.metrics import roc_auc_score

GT = json.loads(__GT__)
HF_TOKEN = __HF_TOKEN__
OUT = "/kaggle/working"
WORK = "/kaggle/temp"

def _resolve_input_dir(expected_slug, must_contain):
    """/kaggle/input/<slug> sometimes doesn't match the dataset's own slug when
    more than one dataset is attached to a kernel — glob for whichever mounted
    directory actually holds the expected file rather than trust the name.

    With 2+ datasets attached, Kaggle nests them under
    /kaggle/input/datasets/<owner>/<slug>/ instead of mounting each directly at
    /kaggle/input/<slug>/ — confirmed by dumping /kaggle/input's own listing on a
    failed run (it printed just ['datasets']). Recursive search covers both shapes."""
    direct = os.path.join("/kaggle/input", expected_slug)
    if os.path.exists(os.path.join(direct, must_contain)):
        return direct
    hits = glob.glob(os.path.join("/kaggle/input", "**", must_contain), recursive=True)
    if hits:
        return os.path.dirname(hits[0])
    print("[esta] /kaggle/input contents:", os.listdir("/kaggle/input") if os.path.isdir("/kaggle/input") else "MISSING")
    for root, dirs, files in os.walk("/kaggle/input"):
        print("[esta]  ", root, "->", files[:5], dirs[:5])
    return direct  # fall through — callers already handle a missing file per-candidate

IN_VIDEOS = _resolve_input_dir(__IN_VIDEOS_SLUG__, __IN_VIDEOS_PROBE__)
IN_FRAMES = _resolve_input_dir(__IN_FRAMES_SLUG__, __IN_FRAMES_PROBE__)
os.makedirs(WORK, exist_ok=True)
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
os.environ["HF_HOME"] = "/kaggle/temp/hf"

results = {"cuts": {}, "tags": {}, "theme": {}, "errors": {}}

def finish():
    with open(os.path.join(OUT, "bakeoff_results.json"), "w") as fh:
        json.dump(results, fh)
    print("ESTA_BAKEOFF_RESULT::" + json.dumps({"ok": True}))

def purge():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

def f1_cuts(pred, gt, tol=0.1):
    gt_used = [False] * len(gt)
    tp = 0
    for p in sorted(pred):
        best_j, best_d = -1, tol + 1e-9
        for j, g in enumerate(sorted(gt)):
            if gt_used[j]:
                continue
            d = abs(p - g)
            if d <= tol and d < best_d:
                best_d, best_j = d, j
        if best_j >= 0:
            gt_used[best_j] = True
            tp += 1
    fp, fn = len(pred) - tp, len(gt) - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

# ============================== CUTS ==========================================
all_gt_cuts = {slug: v["cuts"][1:-1] for slug, v in GT.items()}  # interior only

# -- PySceneDetect --
t0 = time.time()
try:
    from scenedetect import detect, AdaptiveDetector
    preds = {}
    for slug, v in GT.items():
        path = os.path.join(IN_VIDEOS, v["video_file"])
        scenes = detect(path, AdaptiveDetector())
        preds[slug] = [s[0].get_seconds() for s in scenes[1:]]
    scored = [f1_cuts(preds[s], all_gt_cuts[s]) for s in GT]
    weights = [len(all_gt_cuts[s]) for s in GT]
    f1 = sum(s * w for s, w in zip(scored, weights)) / sum(weights) if sum(weights) else 0.0
    dur_min = sum(GT[s]["duration"] for s in GT) / 60
    results["cuts"]["pyscenedetect"] = {"f1": f1, "sec_per_min": (time.time() - t0) / dur_min, "gpu_min": 0.0}
except Exception as e:
    results["errors"]["cuts:pyscenedetect"] = str(e)[:300]
    traceback.print_exc()
finish()

# -- TransNetV2 -- (CSV format: cli.py::process_video_to_output — see candidates.py)
t0 = time.time()
try:
    import csv
    preds = {}
    for slug, v in GT.items():
        src = os.path.join(IN_VIDEOS, v["video_file"])
        dst = os.path.join(WORK, v["video_file"])
        if not os.path.exists(dst):
            import shutil
            shutil.copy(src, dst)
        out_csv = os.path.join(WORK, slug + "_tn2.csv")
        r = subprocess.run(["transnetv2_pytorch", dst, "--output", out_csv, "--quiet"],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not os.path.exists(out_csv):
            raise RuntimeError("transnetv2_pytorch failed: " + (r.stderr or r.stdout)[-300:])
        with open(out_csv, newline="") as fh:
            rows = list(csv.DictReader(fh))
        preds[slug] = [round(float(row["end_time"]), 3) for row in rows[:-1]]
    scored = [f1_cuts(preds[s], all_gt_cuts[s]) for s in GT]
    weights = [len(all_gt_cuts[s]) for s in GT]
    f1 = sum(s * w for s, w in zip(scored, weights)) / sum(weights) if sum(weights) else 0.0
    dur_min = sum(GT[s]["duration"] for s in GT) / 60
    gpu_min = (time.time() - t0) / 60 if torch.cuda.is_available() else 0.0
    results["cuts"]["transnetv2"] = {"f1": f1, "sec_per_min": (time.time() - t0) / dur_min, "gpu_min": gpu_min}
except Exception as e:
    results["errors"]["cuts:transnetv2"] = str(e)[:300]
    traceback.print_exc()
purge()
finish()

results["errors"]["cuts:autoshot"] = "no reachable AutoShot checkpoint (upstream is Baidu-only)"

# ============================== TAGS ==========================================
ALL_SHOTS = []  # (slug, shot_id, frame_path, gt_label)
for slug, v in GT.items():
    for s in v["shots"]:
        p = os.path.join(IN_FRAMES, "%s__shot_%03d.jpg" % (slug, int(s["shot_id"])))
        if os.path.exists(p):
            ALL_SHOTS.append((slug, s["shot_id"], p, s))

KIND_CLASSES = ["footage", "still", "graphic", "ai", "talking_head", "screen", "meme"]
LABEL_FIELDS = ["kind", "text_on_screen", "panels", "overlay", "clips_in_shot"]

def macro_f1_kind(preds, gts):
    per_class = {}
    for c in KIND_CLASSES:
        support = sum(1 for g in gts if g == c)
        if support == 0:
            continue
        tp = sum(1 for p, g in zip(preds, gts) if p == c and g == c)
        fp = sum(1 for p, g in zip(preds, gts) if p == c and g != c)
        fn = sum(1 for p, g in zip(preds, gts) if p != c and g == c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[c] = {"f1": f1, "support": support}
    macro = sum(v["f1"] for v in per_class.values()) / len(per_class) if per_class else 0.0
    return macro, per_class

def parse_label_json(text):
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
        return {
            "kind": str(obj.get("kind", "")).strip().lower(),
            "text_on_screen": bool(obj.get("text_on_screen", False)),
            "panels": int(obj.get("panels", 1)),
            "overlay": bool(obj.get("overlay", False)),
            "clips_in_shot": int(obj.get("clips_in_shot", 1)),
        }
    except Exception:
        return None

PROMPT = (
    "Look at this single video shot's keyframe. Reply with ONLY a JSON object, no "
    "other text:\n"
    '{"kind": one of ["footage","still","graphic","ai","talking_head","screen","meme"], '
    '"text_on_screen": true/false (any on-screen text/captions visible), '
    '"panels": 1, 2, or 3 (3 means 3 or more split-screen panels), '
    '"overlay": true/false (a graphic/text overlay floating over footage), '
    '"clips_in_shot": integer, normally 1}\n'
    'kind meanings: footage=real camera footage, still=static image/screenshot with no '
    'motion, graphic=motion graphic or animated content, ai=visibly AI-generated, '
    'talking_head=person speaking to camera, screen=screen recording/game UI, meme=meme '
    'template or reaction clip.'
)

def score_tag_predictions(preds_by_shot):
    """preds_by_shot: {(slug, shot_id): label_dict or None}. -> per-field scores."""
    scored = {}
    kinds_p, kinds_g = [], []
    for (slug, sid, _, gt) in ALL_SHOTS:
        pred = preds_by_shot.get((slug, sid))
        if pred is None:
            continue
        kinds_p.append(pred["kind"])
        kinds_g.append(gt["kind"])
    macro, per_class = macro_f1_kind(kinds_p, kinds_g)
    scored["kind"] = {"macro_f1": macro, "per_class": per_class}
    for field in ("text_on_screen", "panels", "overlay", "clips_in_shot"):
        correct, total = 0, 0
        for (slug, sid, _, gt) in ALL_SHOTS:
            pred = preds_by_shot.get((slug, sid))
            if pred is None:
                continue
            total += 1
            if pred[field] == gt[field]:
                correct += 1
        scored[field] = {"accuracy": correct / total if total else 0.0, "support": total}
    return scored

def run_vlm_qwen(model_id, load_kwargs):
    from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
    from PIL import Image
    processor = AutoProcessor.from_pretrained(model_id)
    model = Qwen3VLForConditionalGeneration.from_pretrained(model_id, **load_kwargs)
    preds = {}
    for slug, sid, path, gt in ALL_SHOTS:
        img = Image.open(path).convert("RGB")
        messages = [{"role": "user", "content": [{"type": "image", "image": img},
                                                  {"type": "text", "text": PROMPT}]}]
        inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                               return_tensors="pt", return_dict=True).to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=150, do_sample=False)
        text = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        preds[(slug, sid)] = parse_label_json(text)
    del model
    purge()
    return preds

def run_vlm_gemma(model_id):
    from transformers import AutoProcessor, Gemma3ForConditionalGeneration
    from PIL import Image
    processor = AutoProcessor.from_pretrained(model_id, use_fast=False)
    model = Gemma3ForConditionalGeneration.from_pretrained(
        model_id, torch_dtype=torch.bfloat16, device_map="auto")
    preds = {}
    for slug, sid, path, gt in ALL_SHOTS:
        img = Image.open(path).convert("RGB")
        messages = [{"role": "user", "content": [{"type": "image", "image": img},
                                                  {"type": "text", "text": PROMPT}]}]
        inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                               return_tensors="pt", return_dict=True).to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=150, do_sample=False)
        text = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        preds[(slug, sid)] = parse_label_json(text)
    del model
    purge()
    return preds

def run_vlm_gemma4(model_id):
    # 8B raw params but an "effective 4B" footprint via Per-Layer Embedding
    # offloading — same bf16/no-quantization treatment as gemma3-4b, not the
    # 4-bit path qwen3-vl-8b needs. sdpa + AutoModelForImageTextToText and
    # left padding are what the model's own docs specify.
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from PIL import Image
    processor = AutoProcessor.from_pretrained(model_id, padding_side="left")
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, device_map="auto", attn_implementation="sdpa")
    preds = {}
    for slug, sid, path, gt in ALL_SHOTS:
        img = Image.open(path).convert("RGB")
        messages = [{"role": "user", "content": [{"type": "image", "image": img},
                                                  {"type": "text", "text": PROMPT}]}]
        inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                               return_tensors="pt", return_dict=True).to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=150, do_sample=False)
        text = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        preds[(slug, sid)] = parse_label_json(text)
    del model
    purge()
    return preds

def run_florence_text_on_screen():
    from transformers import AutoModelForCausalLM, AutoProcessor, PretrainedConfig
    from PIL import Image
    model_id = "microsoft/Florence-2-large"
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    # Florence-2's pinned remote code reads self.forced_bos_token_id inside its own
    # Florence2LanguageConfig.__init__, before base PretrainedConfig.__init__ has set
    # it as an instance attribute — AttributeError, and it happens INSIDE
    # from_pretrained() itself, too early for any post-hoc patch on the returned
    # model. A class-level default on the base config makes normal attribute lookup
    # (instance -> class) find it either way.
    if not hasattr(PretrainedConfig, "forced_bos_token_id"):
        PretrainedConfig.forced_bos_token_id = None
    # Same story one layer up: newer transformers auto-selects an attention
    # implementation by checking model_class._supports_sdpa, which Florence-2's
    # custom PreTrainedModel subclass never declares. Forcing eager sidesteps the
    # check entirely rather than patching another missing class attribute.
    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=dtype, trust_remote_code=True, attn_implementation="eager").to(
        "cuda" if torch.cuda.is_available() else "cpu")
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    preds = {}
    for slug, sid, path, gt in ALL_SHOTS:
        img = Image.open(path).convert("RGB")
        task = "<OCR>"
        inputs = processor(text=task, images=img, return_tensors="pt").to(model.device, dtype)
        with torch.no_grad():
            out_ids = model.generate(input_ids=inputs["input_ids"], pixel_values=inputs["pixel_values"],
                                     max_new_tokens=256, num_beams=1)
        text = processor.batch_decode(out_ids, skip_special_tokens=True)[0]
        # text_on_screen only — a handful of stray OCR characters on a busy frame is
        # noise, not real on-screen text.
        preds[(slug, sid)] = {"text_on_screen": len(text.strip()) >= 4}
    del model
    purge()
    return preds

tag_timing = {}
from transformers import BitsAndBytesConfig
bnb_4bit = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
for name, fn in [
    ("qwen3-vl-8b", lambda: run_vlm_qwen("Qwen/Qwen3-VL-8B-Instruct",
        dict(dtype=torch.bfloat16, device_map="auto", quantization_config=bnb_4bit))),
    ("qwen3-vl-4b", lambda: run_vlm_qwen("Qwen/Qwen3-VL-4B-Instruct",
        dict(dtype=torch.bfloat16, device_map="auto"))),
    ("gemma3-4b", lambda: run_vlm_gemma("google/gemma-3-4b-it")),
    ("gemma4-e4b", lambda: run_vlm_gemma4("google/gemma-4-E4B-it")),
]:
    t0 = time.time()
    try:
        preds = fn()
        scored = score_tag_predictions(preds)
        dur_min = sum(GT[s]["duration"] for s in GT) / 60
        gpu_min = (time.time() - t0) / 60 if torch.cuda.is_available() else 0.0
        for field, sc in scored.items():
            results["tags"].setdefault(field, {})[name] = {
                **sc, "sec_per_min": (time.time() - t0) / dur_min, "gpu_min": gpu_min}
    except Exception as e:
        results["errors"]["tags:" + name] = str(e)[:300]
        traceback.print_exc()
    finish()

t0 = time.time()
try:
    preds = run_florence_text_on_screen()
    correct = sum(1 for (slug, sid, _, gt) in ALL_SHOTS
                 if (slug, sid) in preds and preds[(slug, sid)]["text_on_screen"] == gt["text_on_screen"])
    total = len(ALL_SHOTS)
    dur_min = sum(GT[s]["duration"] for s in GT) / 60
    gpu_min = (time.time() - t0) / 60 if torch.cuda.is_available() else 0.0
    results["tags"].setdefault("text_on_screen", {})["florence2-large"] = {
        "accuracy": correct / total if total else 0.0, "support": total,
        "sec_per_min": (time.time() - t0) / dur_min, "gpu_min": gpu_min}
except Exception as e:
    results["errors"]["tags:florence2-large"] = str(e)[:300]
    traceback.print_exc()
purge()
finish()

# ============================== THEME =========================================
neg_frames = sorted(glob.glob(os.path.join(IN_FRAMES, "negative__*.jpg")))
pos_frames = [(slug, sid, path) for slug, sid, path, gt in ALL_SHOTS]

def _pool_vec(arr):
    """get_image_features() sometimes returns unpooled per-patch features
    (e.g. SigLIP2 here: shape (196, hidden) not (hidden,)) rather than one
    pooled vector — mean over every axis but the last collapses it to one."""
    while arr.ndim > 1:
        arr = arr.mean(axis=0)
    return arr

def embed_all(embed_fn):
    pos_emb = np.stack([embed_fn(p) for _, _, p in pos_frames])
    neg_emb = np.stack([embed_fn(p) for p in neg_frames])
    embeddings = np.concatenate([pos_emb, neg_emb], axis=0)
    labels = np.array([1] * len(pos_emb) + [0] * len(neg_emb))
    centroid = pos_emb.mean(axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
    normed = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9)
    sims = normed @ centroid
    return roc_auc_score(labels, sims)

def siglip_embed():
    from transformers import AutoModel, AutoProcessor
    from PIL import Image
    model_id = "google/siglip2-base-patch16-224"
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id, device_map="auto").eval()
    def fn(path):
        img = Image.open(path).convert("RGB")
        inputs = processor(images=[img], return_tensors="pt").to(model.device)
        with torch.no_grad():
            feat = model.get_image_features(**inputs)
        return _pool_vec(feat[0].float().cpu().numpy())
    auc = embed_all(fn)
    del model
    purge()
    return auc

def clip_embed():
    from transformers import CLIPModel, CLIPProcessor
    from PIL import Image
    model_id = "openai/clip-vit-base-patch32"
    processor = CLIPProcessor.from_pretrained(model_id)
    model = CLIPModel.from_pretrained(model_id).to("cuda" if torch.cuda.is_available() else "cpu").eval()
    def fn(path):
        img = Image.open(path).convert("RGB")
        inputs = processor(images=[img], return_tensors="pt").to(model.device)
        with torch.no_grad():
            feat = model.get_image_features(**inputs)
        return _pool_vec(feat[0].float().cpu().numpy())
    auc = embed_all(fn)
    del model
    purge()
    return auc

def dinov3_embed():
    from transformers import AutoImageProcessor, AutoModel
    from PIL import Image
    model_id = "facebook/dinov3-convnext-small-pretrain-lvd1689m"
    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id).to("cuda" if torch.cuda.is_available() else "cpu").eval()
    def fn(path):
        img = Image.open(path).convert("RGB")
        inputs = processor(images=img, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model(**inputs)
        pooled = getattr(out, "pooler_output", None)
        if pooled is None:
            pooled = out.last_hidden_state.mean(dim=1)
        return _pool_vec(pooled[0].float().cpu().numpy())
    auc = embed_all(fn)
    del model
    purge()
    return auc

dur_min_all = sum(GT[s]["duration"] for s in GT) / 60
for name, fn in [("siglip2", siglip_embed), ("clip-vit-b32", clip_embed), ("dinov3-small", dinov3_embed)]:
    t0 = time.time()
    try:
        auc = fn()
        gpu_min = (time.time() - t0) / 60 if torch.cuda.is_available() else 0.0
        results["theme"][name] = {"auc": auc, "sec_per_min": (time.time() - t0) / dur_min_all,
                                  "gpu_min": gpu_min}
    except Exception as e:
        results["errors"]["theme:" + name] = str(e)[:300]
        traceback.print_exc()
    finish()

finish()
print("ESTA_BAKEOFF_DONE")
'''


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


def cmd_push(args: argparse.Namespace) -> None:
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

    hf_token = ""
    try:
        import yaml
        cfg = yaml.safe_load((HERE.parents[2] / "config.yaml").read_text(encoding="utf-8"))
        hf_token = (cfg.get("apis", {}) or {}).get("hf_token", "") or ""
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
    state = {"kernel": kernel_id, "videos_dataset": videos_dataset, "frames_dataset": frames_dataset}
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps({"ok": ok, "kernel": kernel_id, "url": f"https://www.kaggle.com/code/{kernel_id}",
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


def _pick_winner(candidates: dict, metric: str, bar: float) -> tuple[str, str, list[str]]:
    passing = {k: v for k, v in candidates.items() if v.get(metric, 0) >= bar}
    if not passing:
        return "", "no candidate cleared the bar", list(candidates)
    winner = max(passing, key=lambda k: passing[k][metric])
    why = f"highest {metric} ({passing[winner][metric]:.3f}) among candidates clearing {bar}"
    return winner, why, []


def cmd_apply(args: argparse.Namespace) -> None:
    ref = _kernel_ref(args.kernel)
    out_dir = Path(args.output_dir) if args.output_dir else HERE / "bakeoff_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_download:
        fetch_output(ref, out_dir)

    results_path = out_dir / "bakeoff_results.json"
    if not results_path.exists():
        raise FileNotFoundError(f"no bakeoff_results.json in {out_dir} — check `status` first")
    raw = json.loads(results_path.read_text(encoding="utf-8"))

    report.start_fresh({"kernel": ref, "errors": raw.get("errors", {})})

    cuts_rows = [{"candidate": k, "score": v["f1"], "sec_per_min": v.get("sec_per_min", 0),
                 "gpu_min": v.get("gpu_min", 0)} for k, v in raw.get("cuts", {}).items()]
    cuts_winner, cuts_why, cuts_dropped = _pick_winner(
        {k: {"f1": v["f1"]} for k, v in raw.get("cuts", {}).items()}, "f1", BARS["cuts"])
    report.write_job_table("Cuts", "F1", BARS["cuts"], cuts_rows, cuts_winner, cuts_why, cuts_dropped)

    tag_winners = {}
    for field, candidates in raw.get("tags", {}).items():
        metric = "macro_f1" if field == "kind" else "accuracy"
        rows = [{"candidate": k, "score": v.get(metric, 0), "sec_per_min": v.get("sec_per_min", 0),
                 "gpu_min": v.get("gpu_min", 0), "support": v.get("support", "")}
                for k, v in candidates.items()]
        winner, why, dropped = _pick_winner(
            {k: {metric: v.get(metric, 0)} for k, v in candidates.items()}, metric, BARS["tags"])
        report.write_job_table(f"Tags: {field}", metric, BARS["tags"], rows, winner, why, dropped)
        if winner:
            tag_winners[field] = winner

    theme_rows = [{"candidate": k, "score": v["auc"], "sec_per_min": v.get("sec_per_min", 0),
                  "gpu_min": v.get("gpu_min", 0)} for k, v in raw.get("theme", {}).items()]
    theme_winner, theme_why, theme_dropped = _pick_winner(
        {k: {"auc": v["auc"]} for k, v in raw.get("theme", {}).items()}, "auc", BARS["theme"])
    report.write_job_table("Theme embeddings", "AUC", BARS["theme"], theme_rows,
                           theme_winner, theme_why, theme_dropped)

    summary = {"cuts_winner": cuts_winner, "tag_winners": tag_winners, "theme_winner": theme_winner,
              "errors": raw.get("errors", {})}
    (HERE / "bakeoff_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "kernel": ref, **summary, "results_md": str(report.RESULTS_PATH)},
                     ensure_ascii=False))


def cmd_approve(args: argparse.Namespace) -> None:
    summary_path = HERE / "bakeoff_summary.json"
    if not summary_path.exists():
        raise RuntimeError("no bakeoff_summary.json — run `apply` first")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    raw = json.loads((HERE / "bakeoff_out" / "bakeoff_results.json").read_text(encoding="utf-8"))

    dropped = set(t.strip() for t in args.drop_tag.split(",") if t.strip())
    winners = {}
    if args.cuts:
        f1 = raw["cuts"].get(args.cuts, {}).get("f1", 0)
        if f1 < BARS["cuts"] and "cuts" not in dropped:
            raise ValueError(f"{args.cuts} scored {f1:.3f} f1, below bar {BARS['cuts']} "
                             f"— pass --drop-tag cuts to accept anyway")
        winners["cuts"] = args.cuts
    if args.theme:
        auc = raw["theme"].get(args.theme, {}).get("auc", 0)
        if auc < BARS["theme"] and "theme" not in dropped:
            raise ValueError(f"{args.theme} scored {auc:.3f} auc, below bar {BARS['theme']} "
                             f"— pass --drop-tag theme to accept anyway")
        winners["theme"] = args.theme
    for pair in args.tags.split(","):
        if not pair.strip():
            continue
        field, model = pair.split("=", 1)
        field, model = field.strip(), model.strip()
        metric = "macro_f1" if field == "kind" else "accuracy"
        score = raw["tags"].get(field, {}).get(model, {}).get(metric, 0)
        if score < BARS["tags"] and field not in dropped:
            raise ValueError(f"{field}={model} scored {score:.3f}, below bar {BARS['tags']} "
                             f"— pass --drop-tag {field} to accept anyway")
        winners[field] = model

    config_path = HERE.parents[2] / "config.yaml"
    import yaml
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("match", {})["models"] = winners
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    timestamp = datetime.now(timezone.utc).isoformat()
    report.append_writeback_log(winners, timestamp, sorted(dropped))
    print(json.dumps({"ok": True, "winners": winners, "dropped": sorted(dropped)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="The real M5.1 bake-off, scored against the frozen answer key")
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("push")

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
        {"push": cmd_push, "status": cmd_status, "apply": cmd_apply, "approve": cmd_approve}[args.mode](args)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
