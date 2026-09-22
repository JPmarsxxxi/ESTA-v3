"""Generative video (AI B-roll) on Kaggle — the free lane for Higgsfield-style shots.

Why this exists: the user's local GPU is a 4 GB RTX A2000 Laptop. Every open
model that does credible image/text->video (Wan, LTX-Video, HunyuanVideo, SVD)
wants 12-40 GB. So generation is offloaded to Kaggle's free GPU.

Why Kaggle and not Colab (which tools/assets/youtube_colab.py uses):

  * Kaggle has a real API. `kernels push/status/output` means this whole thing
    is a headless background job — no browser MCP, no pasting cells, no
    scraping stdout for a sentinel, and no filebin round-trip because outputs
    download straight from /kaggle/working.
  * 30 GPU-hours/week of *guaranteed* quota. Colab free can simply refuse you a
    GPU, which makes it useless as a pipeline step.
  * Sessions run up to 12 h detached. Colab free kills idle sessions, so a long
    generation needs a babysitter.
  * Fast datacenter internet, so the multi-GB model weights pull in seconds.

Flow (three steps, all scriptable — this is the whole reason to prefer Kaggle):

  1. `push`   — read plan.json, collect the shots asking for generated footage,
                resolve a camera preset + prompt for each, build a notebook and
                kernel-metadata.json, and `kaggle kernels push` it. Returns the
                kernel ref immediately; the GPU work happens detached.
  2. `status` — poll the run ("queued" | "running" | "complete" | "error").
  3. `apply`  — `kaggle kernels output` the finished clips into
                assets/source_pool/ and append an assets_progress.jsonl line per
                slot, so render picks them up with no special handling (later
                line wins over the stock pick). Writes gen_video.json as the
                conductor's done-marker.

If the run fails or the quota is out, nothing is written and the stock pick
stays — render is never blocked. Same reversible-upgrade posture as the
YouTube HD path.

On clip length: these models are trained on a fixed window (~5 s), so a single
pass is ~5 s. `--chain` beats that by feeding the last frame of segment N into
segment N+1 as an i2v seed and concatenating on the Kaggle side. Drift
accumulates per hop, so 2-3 segments is the honest ceiling for a clean look.
"""

import argparse
import base64
import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, REPO_ROOT, fetch_output, kaggle_username, kernel_status,
    push_kernel, slugify, use_utf8_stdout, write_kernel_dir,
)

use_utf8_stdout()

HERE = Path(__file__).resolve().parent
PRESETS_PATH = HERE / "presets.json"

# Seed images ride inside the notebook as base64 JPEGs rather than as a Kaggle
# Dataset. A dataset is the "proper" mechanism but costs a create/version call,
# a propagation wait, and a second object to garbage-collect; a downscaled JPEG
# seed is ~60 KB, so a normal slot count fits comfortably in the notebook source.
# Past this ceiling we refuse rather than silently push something Kaggle rejects.
MAX_NOTEBOOK_BYTES = 4 * 1024 * 1024

# ffmpeg -q:v scale, 2 (best) to 31 (worst). 4 is visually clean at 704x480 and
# lands well under 100 KB — the seed only has to survive one VAE encode.
SEED_JPEG_QSCALE = 4

# Model registry. Deliberately data-driven: the open-video landscape moves fast,
# so adding a model should be an edit here, never a new code path. `pipeline` is
# a diffusers class name resolved by getattr on the Kaggle side.
#
# `gpu` is the honest hardware note. Kaggle's free accelerators are T4 x2
# (16 GB each; Turing, so fp16 yes / bf16 no / no flash-attention) and P100
# (16 GB, Pascal). A single diffusers pipeline does not shard across the two
# T4s, so treat the usable budget as 16 GB either way.
MODELS = {
    "ltx": {
        "repo": "Lightricks/LTX-Video",
        "pipeline_t2v": "LTXPipeline",
        "pipeline_i2v": "LTXImageToVideoPipeline",
        "dtype": "float16",
        "frames": 121,
        "fps": 24,
        "width": 704,
        "height": 480,
        "steps": 40,
        "guidance": 3.0,
        "gpu": "t4",
        "notes": "Fast, T4-safe, both t2v and i2v. The default for the free lane.",
    },
    "ltx-distilled": {
        "repo": "Lightricks/LTX-Video-0.9.7-distilled",
        "pipeline_t2v": "LTXPipeline",
        "pipeline_i2v": "LTXImageToVideoPipeline",
        "dtype": "float16",
        "frames": 121,
        "fps": 24,
        "width": 704,
        "height": 480,
        "steps": 8,
        "guidance": 1.0,
        "gpu": "t4",
        "notes": "Same model distilled to ~8 steps. Several times faster, slightly softer motion. Best pick when generating many slots.",
    },
    "svd": {
        "repo": "stabilityai/stable-video-diffusion-img2vid-xt",
        "pipeline_t2v": "",
        "pipeline_i2v": "StableVideoDiffusionPipeline",
        "dtype": "float16",
        "frames": 25,
        "fps": 7,
        "width": 1024,
        "height": 576,
        "steps": 25,
        "guidance": 3.0,
        "gpu": "t4",
        "notes": "Image-to-video only, ~4 s, no text prompt. Old but rock solid on a T4 - the fallback when LTX misbehaves. Requires --seed-from-assets.",
    },
    "hunyuan": {
        "repo": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v_distilled",
        "repo_t2v": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v_distilled",
        "repo_i2v": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v_step_distilled",
        "pipeline_t2v": "HunyuanVideo15Pipeline",
        "pipeline_i2v": "HunyuanVideo15ImageToVideoPipeline",
        "dtype": "float16",
        "frames": 121,
        "fps": 24,
        "width": 832,
        "height": 480,
        "steps": 12,
        "guidance": 1.0,
        "gpu": "t4",
        "diffusers_spec": "diffusers>=0.36.0",
        "caps": {"guider": True, "i2v_no_size": True,
                 "precompute_prompts": True, "cfg_free": True},
        "notes": "Best quality that still fits a free T4. 8.3B, fp16-native (unlike Wan), "
                 "step-distilled to 8-12 steps. Costs ~2-3x an LTX slot; worth it on hero shots.",
    },
    "hunyuan-hq": {
        "repo": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v",
        "repo_t2v": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v",
        "repo_i2v": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v",
        "pipeline_t2v": "HunyuanVideo15Pipeline",
        "pipeline_i2v": "HunyuanVideo15ImageToVideoPipeline",
        "dtype": "float16",
        "frames": 121,
        "fps": 24,
        "width": 832,
        "height": 480,
        "steps": 30,
        "guidance": 6.0,
        "gpu": "t4",
        "diffusers_spec": "diffusers>=0.36.0",
        "caps": {"guider": True, "i2v_no_size": True, "precompute_prompts": True},
        "notes": "Undistilled HunyuanVideo-1.5 with real CFG. The quality ceiling of the free "
                 "lane and roughly 5x the GPU minutes of `hunyuan` - one or two hero shots, not a whole video.",
    },
    "wan5b": {
        "repo": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "pipeline_t2v": "WanPipeline",
        "pipeline_i2v": "WanImageToVideoPipeline",
        "dtype": "bfloat16",
        "frames": 121,
        "fps": 24,
        "width": 704,
        "height": 480,
        "steps": 40,
        "guidance": 5.0,
        "gpu": "l4+",
        "notes": "Wan's 5B. Superseded here by `hunyuan`: it's bf16 and neither Kaggle T4 (Turing) nor P100 (Pascal) has native bf16, so it falls back to fp16 and crawls. Kept for comparison, not recommended.",
    },
}
DEFAULT_MODEL = "ltx"

# Shots ask for generated footage either by type or by carrying a `generate`
# block. Both are honored so the plan skill can adopt this incrementally.
GEN_TYPE = "AI_VIDEO"

# When a shot has no explicit preset, fall back to whatever its render-time fx
# already implied. Keeps existing plans meaningful without a plan-skill change.
FX_TO_PRESET = {
    "zoom_in": "push_in",
    "zoom_out": "pull_back",
    "pan_left": "pan_left",
    "pan_right": "pan_right",
}


# ── presets ───────────────────────────────────────────────────────────────────

def load_presets() -> dict:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


def resolve_preset(shot: dict, presets: dict, default: str) -> str:
    """Preset name for a shot: explicit > implied by fx > caller default."""
    gen = shot.get("visual", {}).get("generate") or {}
    name = gen.get("preset") or ""
    if name and name in presets["presets"]:
        return name
    for fx in shot.get("visual", {}).get("fx", []) or []:
        if fx in FX_TO_PRESET:
            return FX_TO_PRESET[fx]
    return default if default in presets["presets"] else presets["default"]


def build_prompt(shot: dict, preset_name: str, presets: dict, style: str) -> str:
    """Subject + camera move + look, in that order.

    Open video models read a prompt as a scene description, not as a command
    list, so the subject has to lead. The camera fragment goes second because
    trailing clauses get weaker attention, and the style suffix last because it
    only needs to tint the result.
    """
    visual = shot.get("visual", {}) or {}
    gen = visual.get("generate") or {}
    subject = (
        gen.get("prompt")
        or visual.get("desc")
        or visual.get("search_query")
        or shot.get("audio", "")
    ).strip().rstrip(".")
    camera = presets["presets"][preset_name]["prompt"]
    suffix = presets["style_suffix"].get(style, "")
    parts = [p for p in (subject, camera, suffix) if p]
    return ", ".join(parts)


# ── slot collection ───────────────────────────────────────────────────────────

def _load_plan(session_dir: Path) -> list[dict]:
    plan_path = session_dir / "plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"no plan.json in {session_dir}")
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    return data.get("shots", data) if isinstance(data, dict) else data


def _shot_duration(shot: dict) -> float:
    if shot.get("duration"):
        return float(shot["duration"])
    start, end = shot.get("start"), shot.get("end")
    if start is not None and end is not None:
        return max(0.0, float(end) - float(start))
    return 0.0


def collect_slots(
    session_dir: Path,
    presets: dict,
    model: dict,
    preset_default: str,
    style: str,
    only_shots: set[int] | None,
    chain_max: int,
) -> list[dict]:
    """One slot per shot that wants generated footage.

    `segments` is how many chained passes this slot needs to cover its duration,
    clamped by --chain. 1 means a single ~5 s generation.
    """
    shots = _load_plan(session_dir)
    clip_len = model["frames"] / model["fps"]
    slots = []
    for shot in shots:
        n = shot.get("shot_number")
        visual = shot.get("visual", {}) or {}
        wants = visual.get("type") == GEN_TYPE or bool(visual.get("generate"))
        if only_shots is not None:
            wants = n in only_shots
        if not wants:
            continue
        preset_name = resolve_preset(shot, presets, preset_default)
        duration = _shot_duration(shot)
        segments = 1
        if duration > clip_len and chain_max > 1:
            segments = min(chain_max, math.ceil(duration / clip_len))
        slots.append({
            "shot_number": n,
            "key": str(n),
            "preset": preset_name,
            "prompt": build_prompt(shot, preset_name, presets, style),
            "duration": round(duration, 2),
            "segments": segments,
            "seed_b64": "",
        })
    return slots


# ── seed images (image-to-video) ──────────────────────────────────────────────

def _latest_asset_for_shot(session_dir: Path, shot_number: int) -> tuple[Path | None, float]:
    """Last successful assets_progress line for this shot -> (file, in_point).

    Later lines win, matching how render resolves the feed.
    """
    feed = session_dir / "assets_progress.jsonl"
    if not feed.exists():
        return None, 0.0
    found, in_point = None, 0.0
    for line in feed.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("shot_number") != shot_number or not rec.get("ok"):
            continue
        if str(rec.get("key", rec.get("shot_number"))).endswith("-overlay"):
            continue
        # The feed stores repo-root-relative paths (sessions\<id>\assets\...).
        path = Path(rec.get("file", ""))
        if not path.is_absolute():
            path = REPO_ROOT / path
        found, in_point = path, float(rec.get("in_point") or 0.0)
    return found, in_point


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    """ffmpeg via the esta conda env — the same binary render and probe use.

    Explicit utf-8/replace decoding: ffmpeg writes non-cp1252 bytes to stderr
    (codec names, box-drawing), and the Windows locale codec raises on them.
    """
    return subprocess.run(
        ["conda", "run", "--no-capture-output", "-n", "esta", "ffmpeg", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )


def attach_seed_images(session_dir: Path, slots: list[dict], model: dict) -> dict:
    """Extract a frame from each shot's existing footage and embed it as base64.

    This is what turns text-to-video into image-to-video: the generated clip
    starts from the stock frame the user already picked, so the AI motion
    inherits their taste instead of inventing a new subject.

    The frame is scaled to the model's exact generation size first — the
    pipeline would resize anyway, and doing it here keeps the notebook small.
    """
    tmp = session_dir / "assets" / "gen_seeds"
    tmp.mkdir(parents=True, exist_ok=True)
    report = {"seeded": 0, "skipped": []}
    for slot in slots:
        src, in_point = _latest_asset_for_shot(session_dir, slot["shot_number"])
        if not src or not src.exists():
            report["skipped"].append({"shot": slot["shot_number"], "why": "no fetched asset"})
            continue
        frame = tmp / f"seed_{slot['shot_number']}.jpg"
        scale = (f"scale={model['width']}:{model['height']}:force_original_aspect_ratio=increase,"
                 f"crop={model['width']}:{model['height']}")
        tail = ["-frames:v", "1", "-vf", scale, "-q:v", str(SEED_JPEG_QSCALE), str(frame)]

        # Seek first, then retry from the head. Input-seeking a single-frame
        # source (stills are a normal asset type here) consumes the only frame
        # and yields an empty output, and an in_point past a clip's end does the
        # same — both recover by simply not seeking.
        attempts = ([["-ss", str(in_point), "-i", str(src)]] if in_point > 0 else []) \
            + [["-i", str(src)]]
        res = None
        for head in attempts:
            res = _ffmpeg("-y", *head, *tail)
            if res.returncode == 0 and frame.exists() and frame.stat().st_size > 0:
                break
        if not frame.exists() or frame.stat().st_size == 0:
            why = ((res.stderr if res else "") or "").strip().splitlines()[-1:] or ["extract failed"]
            report["skipped"].append({"shot": slot["shot_number"], "why": why[0][:120]})
            continue
        slot["seed_b64"] = base64.b64encode(frame.read_bytes()).decode("ascii")
        report["seeded"] += 1
    return report


# ── notebook source ───────────────────────────────────────────────────────────

NOTEBOOK_CODE = '''# ESTA - generative video on Kaggle's free GPU.
# Writes gen_<key>.mp4 + gen_results.json to /kaggle/working for `kernels output`.
import subprocess, sys, json, os, gc, base64, io, traceback

SLOTS = json.loads(__SLOTS__)
MODEL = json.loads(__MODEL__)
NEG   = __NEG__
OUT   = "/kaggle/working"
CAPS  = MODEL.get("caps", {}) or {}

# Weights go to /kaggle/temp, never /kaggle/working: `kernels output` downloads
# the working dir and it is capped at 20 GB, while a modern checkpoint plus its
# 7B text encoder is ~35 GB. /kaggle/temp is scratch and never collected.
if os.path.isdir("/kaggle/temp"):
    os.makedirs("/kaggle/temp/hf", exist_ok=True)
    os.environ["HF_HOME"] = "/kaggle/temp/hf"

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                MODEL.get("diffusers_spec", "diffusers>=0.33.0"),
                "transformers", "accelerate",
                "imageio[ffmpeg]", "sentencepiece", "protobuf"], check=False)

import numpy as np
import torch, diffusers
from diffusers.utils import export_to_video
from PIL import Image

def finish(results, errors):
    with open(os.path.join(OUT, "gen_results.json"), "w") as fh:
        json.dump({"results": results, "errors": errors}, fh)
    print("ESTA_GEN_RESULT::" + json.dumps({"results": results, "errors": errors}))

if not torch.cuda.is_available():
    finish({}, {"_": "no GPU on this kernel - set Accelerator to GPU T4 x2 or P100"})
    raise SystemExit

print("[esta] GPU:", torch.cuda.get_device_name(0), flush=True)
dtype = getattr(torch, MODEL["dtype"])
if dtype is torch.bfloat16 and not torch.cuda.is_bf16_supported():
    # Kaggle's T4 (Turing) and P100 (Pascal) both lack native bf16.
    print("[esta] bf16 unsupported here, falling back to fp16", flush=True)
    dtype = torch.float16

def repo_for(kind):
    """Some models ship t2v and i2v as separate checkpoints; most share one."""
    return MODEL.get("repo_" + kind) or MODEL["repo"]

def pipe_cls(kind):
    cls_name = MODEL["pipeline_i2v"] if kind == "i2v" else MODEL["pipeline_t2v"]
    if not cls_name:
        raise RuntimeError(MODEL["repo"] + " has no " + kind + " pipeline")
    return getattr(diffusers, cls_name)

def _as_pil(frame):
    """Pipelines return PIL or a float ndarray depending on their output_type default."""
    if isinstance(frame, Image.Image):
        return frame
    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        arr = (arr.clip(0, 1) * 255).astype("uint8")
    return Image.fromarray(arr)

# -- prompt pre-encoding -------------------------------------------------------
# HunyuanVideo-1.5 carries a 7B Qwen2.5-VL text encoder. Transformer + encoders
# together are ~33 GB in fp16 and a Kaggle GPU kernel has 32 GB of *host* RAM, so
# CPU offload alone OOMs the host rather than the card. Encoding every prompt up
# front and then dropping the encoders keeps exactly one large model resident.
EMB = {}
EMB_KEYS = ("prompt_embeds", "prompt_embeds_mask", "prompt_embeds_2", "prompt_embeds_mask_2")

def precompute_prompts():
    # Pick the checkpoint this run will actually use: passing transformer=None
    # makes diffusers skip downloading it, so only the encoders come down here
    # and only the denoiser comes down later.
    seeded = any(s.get("seed_b64") for s in SLOTS)
    kind = "i2v" if (seeded and MODEL["pipeline_i2v"]) else "t2v"
    pipe = pipe_cls(kind).from_pretrained(
        repo_for(kind), torch_dtype=dtype, transformer=None, vae=None)
    try:
        pipe.enable_model_cpu_offload()
    except Exception:
        pipe.to("cuda")

    def enc(text):
        out = pipe.encode_prompt(text)
        out = out if isinstance(out, (list, tuple)) else (out,)
        return [t.cpu() if torch.is_tensor(t) else t for t in out]

    neg = None if CAPS.get("cfg_free") else enc(NEG)
    for slot in SLOTS:
        EMB[slot["key"]] = {"pos": enc(slot["prompt"]), "neg": neg}
        print("[esta] encoded prompt for", slot["key"], flush=True)
    del pipe
    gc.collect(); torch.cuda.empty_cache()

if CAPS.get("precompute_prompts"):
    try:
        precompute_prompts()
    except Exception as e:
        # In-pipeline encoding is correct but memory-hungry; say so loudly,
        # because a host OOM later just reads as an unexplained kernel kill.
        EMB.clear()
        print("[esta] prompt pre-encode failed, using in-pipeline encoding:", e, flush=True)
        traceback.print_exc()

_PIPES = {}
def get_pipe(kind):
    """Load t2v/i2v lazily, keeping only one resident - host RAM is the real cap."""
    if kind in _PIPES:
        return _PIPES[kind]
    for other in list(_PIPES):
        del _PIPES[other]
    gc.collect(); torch.cuda.empty_cache()
    kw = dict(torch_dtype=dtype)
    if EMB:
        kw.update(text_encoder=None, text_encoder_2=None)
    pipe = pipe_cls(kind).from_pretrained(repo_for(kind), **kw)
    # A pipeline can also be split across Kaggle's two T4s with
    # device_map="balanced", but sequential offload is what this lane has
    # actually been proven on, and it holds peak VRAM under one 16 GB card.
    pipe.enable_sequential_cpu_offload()
    if hasattr(pipe, "vae"):
        try:
            pipe.vae.enable_tiling(); pipe.vae.enable_slicing()
        except Exception:
            pass
    if CAPS.get("guider") and getattr(pipe, "guider", None) is not None:
        # Newer pipelines carry a guider object instead of a guidance_scale arg.
        # A distilled checkpoint wants CFG off entirely, which also halves the
        # forward passes per step.
        g = float(MODEL.get("guidance") or 1.0)
        try:
            pipe.guider = (pipe.guider.new(enabled=False) if g <= 1.0
                           else pipe.guider.new(guidance_scale=g))
        except Exception as e:
            print("[esta] guider config skipped:", e, flush=True)
    _PIPES[kind] = pipe
    return pipe

def _kwargs(kind, slot, image):
    if MODEL["pipeline_i2v"].startswith("StableVideoDiffusion"):
        # SVD takes no text at all - image + motion knobs only.
        return dict(image=image, num_frames=MODEL["frames"],
                    width=MODEL["width"], height=MODEL["height"],
                    decode_chunk_size=4, motion_bucket_id=127)

    kw = dict(num_frames=MODEL["frames"], num_inference_steps=MODEL["steps"])
    emb = EMB.get(slot["key"])
    if emb and len(emb["pos"]) == len(EMB_KEYS):
        kw.update(dict(zip(EMB_KEYS, emb["pos"])))
        if emb["neg"] and len(emb["neg"]) == len(EMB_KEYS):
            kw.update({"negative_" + k: v for k, v in zip(EMB_KEYS, emb["neg"])})
    else:
        kw.update(prompt=slot["prompt"], negative_prompt=NEG)
    if not CAPS.get("guider"):
        kw["guidance_scale"] = MODEL["guidance"]
    # Image-to-video on some models takes the frame size from the seed image
    # and rejects width/height outright.
    if not (kind == "i2v" and CAPS.get("i2v_no_size")):
        kw.update(width=MODEL["width"], height=MODEL["height"])
    if kind == "i2v":
        kw["image"] = image
    return kw

def generate(slot):
    """Generate the slot, chaining segments when it needs to outrun the 5 s window."""
    frames_all, image = [], None
    if slot.get("seed_b64"):
        image = Image.open(io.BytesIO(base64.b64decode(slot["seed_b64"]))).convert("RGB")
    for seg in range(slot["segments"]):
        kind = "i2v" if image is not None else "t2v"
        out = get_pipe(kind)(**_kwargs(kind, slot, image)).frames[0]
        # Drop the duplicated seam frame on every segment after the first.
        frames_all.extend(out if seg == 0 else out[1:])
        if seg + 1 < slot["segments"]:
            image = _as_pil(out[-1])          # last frame seeds the next hop
        print("[esta] shot", slot["key"], "segment", seg + 1, "/", slot["segments"], flush=True)
    path = os.path.join(OUT, "gen_" + str(slot["key"]) + ".mp4")
    export_to_video(frames_all, path, fps=MODEL["fps"])
    return path, len(frames_all)

results, errors = {}, {}
for slot in SLOTS:
    key = slot["key"]
    try:
        print("[esta] ---", key, slot["preset"], "|", slot["prompt"][:90], flush=True)
        path, nframes = generate(slot)
        results[key] = {"file": os.path.basename(path), "frames": nframes,
                        "fps": MODEL["fps"], "preset": slot["preset"],
                        "shot_number": slot["shot_number"]}
        print("OK", key, nframes, "frames", flush=True)
    except Exception as e:
        errors[key] = (str(e) or repr(e))[:250]
        traceback.print_exc()
        print("ERR", key, errors[key], flush=True)
    gc.collect(); torch.cuda.empty_cache()
    # Checkpoint after every slot: a kernel that times out at 12 h still keeps
    # whatever it finished, because `kernels output` reads /kaggle/working.
    finish(results, errors)
'''


def build_notebook_code(slots: list[dict], model: dict, negative: str) -> str:
    """Fill the notebook template by placeholder substitution.

    Substitution rather than an f-string because the template is full of dict
    literals, and doubling every brace to survive .format() is how this kind of
    template rots.
    """
    lean = [
        {k: s[k] for k in ("key", "shot_number", "preset", "prompt", "segments", "seed_b64")}
        for s in slots
    ]
    return (
        NOTEBOOK_CODE
        .replace("__SLOTS__", repr(json.dumps(lean)))
        .replace("__MODEL__", repr(json.dumps(model)))
        .replace("__NEG__", repr(negative))
    )


def _state_path(session_dir: Path) -> Path:
    return session_dir / "gen_video_kernel.json"


# ── apply results ─────────────────────────────────────────────────────────────

def _shot_durations(session_dir: Path) -> dict[int, float]:
    """{shot_number: duration} from plan.json, or {} if it can't be read."""
    try:
        return {s.get("shot_number"): _shot_duration(s) for s in _load_plan(session_dir)}
    except Exception:  # noqa: BLE001 — trimming is an optimisation, never a blocker
        return {}


def apply_results(session_dir: Path, results: dict, errors: dict, out_dir: Path) -> dict:
    """Move generated clips into source_pool and publish them on the assets feed.

    Publishing as an ordinary assets_progress line is the whole integration:
    render already resolves that feed with later-line-wins, so a generated clip
    supersedes the stock pick for the same shot with no render change at all.
    Nothing is deleted — the stock file stays as the fallback.
    """
    pool = session_dir / "assets" / "source_pool"
    pool.mkdir(parents=True, exist_ok=True)
    feed = session_dir / "assets_progress.jsonl"
    applied, failed, lines = [], [], []

    for key, info in sorted(results.items(), key=lambda kv: str(kv[0])):
        src = out_dir / info.get("file", f"gen_{key}.mp4")
        if not src.exists() or src.stat().st_size == 0:
            failed.append({"key": key, "why": "clip missing from kernel output"})
            continue
        dest = pool / f"gen_{key}.mp4"
        dest.write_bytes(src.read_bytes())
        # Match the assets skill: the feed carries repo-root-relative paths, so a
        # session folder stays portable. Fall back to absolute if it's outside.
        try:
            feed_path = str(dest.resolve().relative_to(REPO_ROOT))
        except ValueError:
            feed_path = str(dest)

        fps = float(info.get("fps") or 24)
        nframes = int(info.get("frames") or 0)
        clip_seconds = round(nframes / fps, 3) if nframes and fps else 0.0
        shot_number = info.get("shot_number")
        if shot_number is None and str(key).split("-")[0].isdigit():
            shot_number = int(str(key).split("-")[0])

        # Trim to the shot's own duration rather than publishing the whole clip.
        # Two reasons, and the second is the important one: the model always
        # emits its full trained window (~5 s) regardless of what the shot needs,
        # AND diffusion quality decays toward the tail — verified on the first
        # live run, where frame 120 of 121 had smeared into incoherence while
        # frame 60 was clean. Cutting to the shot length discards the drifted
        # tail for free. Only ever trims; a shot longer than the clip keeps all.
        out_point = clip_seconds
        want = _shot_durations(session_dir).get(shot_number) or 0.0
        if want and clip_seconds and want < clip_seconds:
            out_point = round(want, 3)
        lines.append({
            "shot_number": shot_number,
            "key": str(key),
            "ok": True,
            "source": "genvideo",
            "asset_type": "video",
            "url": "",
            "file": feed_path,
            "search_query": info.get("preset", ""),
            "in_point": 0.0,
            "out_point": out_point,
            "visual_verdict": "",
            "visual_confidence": 0,
            "error": "",
        })
        applied.append({"key": key, "file": feed_path, "seconds": out_point,
                        "preset": info.get("preset", "")})

    if lines:
        with open(feed, "a", encoding="utf-8") as fh:
            for rec in lines:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    marker = {
        "generated": len(applied),
        "failed": len(failed) + len(errors),
        "slots": applied,
        "errors": {**{f["key"]: f["why"] for f in failed}, **errors},
    }
    (session_dir / "gen_video.json").write_text(
        json.dumps(marker, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return marker


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_presets(args: argparse.Namespace) -> None:
    presets = load_presets()
    if args.json:
        print(json.dumps(presets, ensure_ascii=False))
        return
    print(f"{'name':<16} {'family':<8} {'reliability':<12} label")
    for name, p in presets["presets"].items():
        print(f"{name:<16} {p['family']:<8} {p['reliability']:<12} {p['label']}")
    print("\nmodels:")
    for name, m in MODELS.items():
        shape = f"{m['width']}x{m['height']} {m['steps']}st"
        print(f"  {name:<14} {m['gpu']:<5} ~{m['frames'] / m['fps']:.1f}s/clip  "
              f"{shape:<16} {m['notes']}")


def _resolve_model(args: argparse.Namespace) -> dict:
    if args.model not in MODELS:
        raise ValueError(f"unknown model {args.model!r}; try: {', '.join(MODELS)}")
    model = dict(MODELS[args.model])
    for key in ("frames", "fps", "width", "height", "steps"):
        if getattr(args, key, 0):
            model[key] = getattr(args, key)
    if getattr(args, "guidance", 0.0):
        model["guidance"] = args.guidance
    return model


def cmd_push(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    presets = load_presets()
    model = _resolve_model(args)

    only = None
    if args.shots:
        only = {int(x) for x in args.shots.replace(" ", "").split(",") if x}

    slots = collect_slots(session_dir, presets, model, args.preset,
                          args.style, only, args.chain)
    if not slots:
        print(json.dumps({"ok": True, "count": 0,
                          "message": "no shots ask for generated footage"}))
        return

    seeding = {"seeded": 0, "skipped": []}
    if args.seed_from_assets:
        seeding = attach_seed_images(session_dir, slots, model)
    if not model["pipeline_t2v"] and seeding["seeded"] < len(slots):
        raise ValueError(f"{args.model} is image-to-video only — every slot needs "
                         f"--seed-from-assets to succeed ({seeding['seeded']}/{len(slots)} seeded)")

    code = build_notebook_code(slots, model, presets["negative_default"])
    kernel_id = f"{kaggle_username()}/{slugify(session_dir.name, prefix='esta-gen-')}"
    build_dir = session_dir / "assets" / "gen_kernel"
    nb_path = write_kernel_dir(build_dir, code, kernel_id,
                               ACCELERATORS.get(args.accelerator, ACCELERATORS["t4"]))

    size = nb_path.stat().st_size
    if size > MAX_NOTEBOOK_BYTES:
        raise ValueError(f"notebook is {size / 1e6:.1f} MB (seed images) — over the "
                         f"{MAX_NOTEBOOK_BYTES / 1e6:.0f} MB ceiling. Push fewer slots per run.")

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "kernel": kernel_id,
                          "count": len(slots), "notebook_bytes": size,
                          "slots": [{k: s[k] for k in ("key", "preset", "prompt", "segments")}
                                    for s in slots],
                          "seeding": seeding}, ensure_ascii=False))
        return

    ok, log = push_kernel(build_dir)
    state = {
        "kernel": kernel_id,
        "model": args.model,
        "accelerator": args.accelerator,
        "count": len(slots),
        "slots": [{k: s[k] for k in ("key", "shot_number", "preset", "segments")} for s in slots],
        "seeding": seeding,
    }
    _state_path(session_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": ok, "kernel": kernel_id, "count": len(slots),
        "notebook_bytes": size, "seeding": seeding,
        "url": f"https://www.kaggle.com/code/{kernel_id}",
        "log": log[-400:],
    }, ensure_ascii=False))


def _kernel_ref(session_dir: Path, explicit: str) -> str:
    if explicit:
        return explicit
    state = _state_path(session_dir)
    if state.exists():
        ref = json.loads(state.read_text(encoding="utf-8")).get("kernel", "")
        if ref:
            return ref
    return f"{kaggle_username()}/{slugify(session_dir.name, prefix='esta-gen-')}"


def cmd_status(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    ref = _kernel_ref(session_dir, args.kernel)
    state, raw = kernel_status(ref)
    print(json.dumps({"ok": bool(state), "kernel": ref,
                      "state": state, "raw": raw}, ensure_ascii=False))


def cmd_apply(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    ref = _kernel_ref(session_dir, args.kernel)
    out_dir = Path(args.output_dir) if args.output_dir else session_dir / "assets" / "gen_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        fetch_output(ref, out_dir)

    results_path = out_dir / "gen_results.json"
    if not results_path.exists():
        raise FileNotFoundError(
            f"no gen_results.json in {out_dir} — the kernel may still be running "
            f"(check `status`) or it failed before writing anything")
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    summary = apply_results(session_dir, raw.get("results", {}), raw.get("errors", {}), out_dir)
    print(json.dumps({"ok": True, "kernel": ref, **summary}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA generative video on Kaggle")
    sub = parser.add_subparsers(dest="mode", required=True)

    pr = sub.add_parser("presets", help="List camera presets and models")
    pr.add_argument("--json", action="store_true")

    p = sub.add_parser("push", help="Build the notebook and start the Kaggle run")
    p.add_argument("--session", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))
    p.add_argument("--accelerator", default="t4", choices=list(ACCELERATORS))
    p.add_argument("--preset", default="push_in", help="Preset for shots that don't name one")
    p.add_argument("--style", default="cinematic",
                   help="Style suffix key from presets.json (cinematic|documentary|broadcast|gritty)")
    p.add_argument("--shots", default="", help="Force specific shot numbers, e.g. 3,7,9")
    p.add_argument("--chain", type=int, default=1,
                   help="Max chained segments per slot (1 = single ~5s clip). Drift grows per hop.")
    p.add_argument("--seed-from-assets", action="store_true",
                   help="Image-to-video: seed each slot from the frame already fetched for that shot")
    p.add_argument("--dry-run", action="store_true", help="Build and report, don't push")
    for flag in ("frames", "fps", "width", "height", "steps"):
        p.add_argument(f"--{flag}", type=int, default=0)
    p.add_argument("--guidance", type=float, default=0.0,
                   help="Override CFG scale. <=1 disables guidance entirely on models "
                        "that use a guider (halves the forward passes per step).")

    s = sub.add_parser("status", help="Poll the Kaggle run")
    s.add_argument("--session", required=True)
    s.add_argument("--kernel", default="")

    a = sub.add_parser("apply", help="Pull finished clips in and publish them on the assets feed")
    a.add_argument("--session", required=True)
    a.add_argument("--kernel", default="")
    a.add_argument("--output-dir", default="")
    a.add_argument("--skip-download", action="store_true",
                   help="Use an already-downloaded output dir instead of re-fetching")

    args = parser.parse_args()
    try:
        {"presets": cmd_presets, "push": cmd_push,
         "status": cmd_status, "apply": cmd_apply}[args.mode](args)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
