"""Generative video (AI B-roll) on Kaggle — the free lane for Higgsfield-style shots.

Why this exists: the user's local GPU is a 4 GB RTX A2000 Laptop. Every open
model that does credible image-to-video (Wan 2.2, AniSora) wants 12-40 GB. So
generation is offloaded to Kaggle's free GPU.

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

On clip length: each slot generates just enough frames to cover its shot, up
to the model's trained window (5 s). `--chain` covers longer shots by feeding
the last frame of segment N into segment N+1 and concatenating on the Kaggle
side. Drift accumulates per hop, so 2-3 segments is the honest ceiling.
"""

import argparse
import base64
import hashlib
import json
import math
import re
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, REPO_ROOT, fetch_output, kaggle_username, kernel_status,
    push_kernel, slugify, use_utf8_stdout, write_kernel_dir,
)
from tools.look import refs as look_refs  # noqa: E402

use_utf8_stdout()

HERE = Path(__file__).resolve().parent
PRESETS_PATH = HERE / "presets.json"
KEYFRAME_LAYOUT = 0.2   # IP-Adapter layout-block scale for styled keyframes (genchar keeps refs.LAYOUT_SCALE)

# Seed images ride inside the notebook as base64 JPEGs rather than as a Kaggle
# Dataset. A dataset is the "proper" mechanism but costs a create/version call,
# a propagation wait, and a second object to garbage-collect; a downscaled JPEG
# seed is ~60 KB, so a normal slot count fits comfortably in the notebook source.
# Past this ceiling we refuse rather than silently push something Kaggle rejects.
MAX_NOTEBOOK_BYTES = 4 * 1024 * 1024

# ffmpeg -q:v scale, 2 (best) to 31 (worst). 4 is visually clean at 704x480 and
# lands well under 100 KB — the seed only has to survive one VAE encode.
SEED_JPEG_QSCALE = 4

# genchar's store (tools/genchar/run.py): characters outlive sessions, like voice_samples/.
CHARACTERS_DIR = REPO_ROOT / "characters"

# Model registry. `gpu` is the honest hardware note: Kaggle's free T4 is 16 GB, Turing (fp16 yes, bf16 no, no
# flash-attention). Both models are Wan 2.2 image-to-video and share one loader (WAN_LOADER). Picked by the
# 2026-10 bake-off (tools/genvideo/bakeoff, SPEC.md Part 6): the previous default broke 2 of 5 styled shots and
# HunyuanVideo-class models never finished on a T4.
MODELS = {
    "anisora": {
        "repo": "Wan-AI/Wan2.2-I2V-A14B-Diffusers",
        "gguf_repo": "youcef079/Index-Anisora-V3.2-GGUF",
        "gguf": ["High/Index-Anisora-V3.2-High-Q4_0.gguf", "Low/Index-Anisora-V3.2-Low-Q4_K_S.gguf"],
        "pipeline_i2v": "WanImageToVideoPipeline",
        "frames": 81,
        "fps": 16,
        "width": 832,
        "height": 480,
        "steps": 8,
        "guidance": 1.0,
        "gpu": "t4",
        "notes": "Index-AniSora V3.2 (Wan 2.2 A14B, animation fine-tune), Q4 GGUF, 8 steps. Best motion in the "
                 "bake-off on styled and real shots; ~14-18 min per 3.5 s clip on a T4.",
    },
    "wan5b": {
        "repo": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "pipeline_i2v": "WanImageToVideoPipeline",
        "frames": 121,
        "fps": 24,
        "width": 832,
        "height": 480,
        "steps": 30,
        "guidance": 5.0,
        "gpu": "t4",
        "notes": "Wan 2.2 TI2V-5B, fp16, 30 steps. Faster (~11-12 min per 3.5 s clip), follows the camera move, "
                 "adds less action.",
    },
}
DEFAULT_MODEL = "anisora"
HD_SIZE = (1280, 720)    # generate.hd: true; untested on a T4, so the notebook retries at the model size on OOM
MIN_FRAMES = 17
SPLIT_MIN_SLOTS = 4   # fewer slots than this stay one Kaggle run
# apply's clip check, calibrated on the bake-off clips (tools/genvideo/bakeoff): every AniSora and Wan 5B clip
# passes, the old default's black and melted clips fail.
CHECK_STEP, CHECK_DARK, CHECK_COLLAPSE = 0.25, 20.0, 0.05

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


def keyframe_prompt(shot: dict, look_style: str) -> str:
    """A still needs no camera move, and SDXL's CLIP stops at 77 tokens: subject + look only."""
    visual = shot.get("visual", {}) or {}
    subject = ((visual.get("generate") or {}).get("prompt") or visual.get("desc") or shot.get("audio", "")).strip().rstrip(".")
    return ", ".join(p for p in (subject, look_style) if p)


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


def frames_for(seconds: float, fps: int, cap: int) -> int:
    """Frames covering `seconds`, in the 4k+1 counts Wan's temporal VAE needs, between MIN_FRAMES and `cap`."""
    need = max(MIN_FRAMES, math.ceil(seconds * fps))
    return min(cap, 4 * math.ceil((need - 1) / 4) + 1)


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
    clamped by --chain; `frames` is each pass's length, just enough to cover its
    share of the shot (SPEC.md Part 6, decision 3).
    """
    shots = _load_plan(session_dir)
    clip_len = model["frames"] / model["fps"]
    look_style = _look_style(session_dir)
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
        frames = frames_for(duration / segments, model["fps"], model["frames"])
        # A session look replaces the --style suffix: "shot on film, natural lighting" fights an animated look.
        prompt = build_prompt(shot, preset_name, presets, "" if look_style else style)
        slots.append({
            "shot_number": n,
            "key": str(n),
            "preset": preset_name,
            "prompt": f"{prompt}, {look_style}" if look_style else prompt,
            "kf_prompt": keyframe_prompt(shot, look_style),
            "duration": round(duration, 2),
            "segments": segments,
            "frames": frames,
            "hd": bool((visual.get("generate") or {}).get("hd")),
            "seed_b64": "",
            "character": (visual.get("generate") or {}).get("character") or "",
            "talk": bool((visual.get("generate") or {}).get("talk")),
        })
    return slots


def _look_style(session_dir: Path) -> str:
    try:
        req = json.loads((session_dir / "requirements.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(req.get("look_style") or "").strip()


# ── seed images (image-to-video) ──────────────────────────────────────────────

def _scale_to(src: Path, dest: Path, model: dict) -> bool:
    scale = (f"scale={model['width']}:{model['height']}:force_original_aspect_ratio=increase,"
             f"crop={model['width']}:{model['height']}")
    res = _ffmpeg("-y", "-i", str(src), "-frames:v", "1", "-vf", scale, "-q:v", str(SEED_JPEG_QSCALE), str(dest))
    return res.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def attach_talk_audio(session_dir: Path, slots: list[dict]) -> dict:
    """Cut each talking shot's slice of the voiceover (16 kHz mono wav) to ship with the job."""
    audio = session_dir / "audio.wav"
    shots = {s.get("shot_number"): s for s in _load_plan(session_dir)}
    tmp = session_dir / "assets" / "gen_seeds"
    tmp.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    for slot in slots:
        if not slot.get("talk"):
            continue
        shot = shots.get(slot["shot_number"]) or {}
        start, end = float(shot.get("start") or 0), float(shot.get("end") or 0)
        if not audio.exists():
            report[slot["shot_number"]] = "no audio.wav"
            continue
        if not str(shot.get("audio") or "").strip():
            report[slot["shot_number"]] = "no spoken line: no lip-sync"
            continue
        if end - start < 0.5:
            report[slot["shot_number"]] = "line under 0.5 s: no lip-sync"
            continue
        wav = tmp / f"talk_{slot['shot_number']}.wav"
        res = _ffmpeg("-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(audio), "-ac", "1", "-ar", "16000", str(wav))
        if res.returncode != 0 or not wav.exists():
            report[slot["shot_number"]] = "audio cut failed"
            continue
        slot["audio_b64"] = base64.b64encode(wav.read_bytes()).decode("ascii")
        slot["audio_seconds"] = round(end - start, 3)
        report[slot["shot_number"]] = f"{end - start:.2f} s"
    return report


def attach_character_seeds(session_dir: Path, slots: list[dict], model: dict) -> dict:
    """Seed each character shot from its LoRA keyframe (genchar render --session), else the picked
    design (ref.png), else describe the character in a text-to-video prompt (SPEC.md Part 4)."""
    tmp = session_dir / "assets" / "gen_seeds"
    tmp.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    for slot in slots:
        name = slot.get("character")
        if not name:
            continue
        d = CHARACTERS_DIR / slugify(name)
        keyframe = d / "render" / f"{slugify(session_dir.name)}__s{slot['shot_number']}.png"
        for source, path in (("lora_keyframe", keyframe), ("ref", d / "ref.png")):
            frame = tmp / f"seed_{slot['shot_number']}.jpg"
            if path.exists() and _scale_to(path, frame, model):
                slot["seed_b64"] = base64.b64encode(frame.read_bytes()).decode("ascii")
                report[slot["shot_number"]] = source
                break
        else:
            try:
                desc = json.loads((d / "character.json").read_text(encoding="utf-8")).get("desc", "")
            except Exception:
                desc = ""
            slot["prompt"] = f"{desc}, {slot['prompt']}" if desc else slot["prompt"]
            report[slot["shot_number"]] = "text" if desc else "text (no character.json)"
    return report


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


def attach_keyframes(session_dir: Path, slots: list[dict], model: dict, model_name: str, strength: float) -> dict:
    """Mark every still-unseeded slot for a keyframe: SDXL draws its first frame on Kaggle, then the video model
    animates it. With look refs it is styled through the IP-Adapter (SPEC.md Part 5, decision 5); without, it is
    plain SDXL from the prompt, because both video models are image-to-video only (Part 6, decision 2)."""
    if not model["pipeline_i2v"]:
        return {"skipped": f"{model_name} has no image-to-video pipeline: no keyframes"}
    refs = look_refs.resolve(session_dir, "keyframe") if strength > 0 else []
    from tools.genchar.run import LOOK_MODEL, MODELS, NEGATIVE
    try:
        look = json.loads((session_dir / "requirements.json").read_text(encoding="utf-8")).get("look") or ""
    except Exception:  # noqa: BLE001
        look = ""
    sd = MODELS[LOOK_MODEL.get(look, "sdxl")]
    marked = [slot for slot in slots if not slot["seed_b64"]]
    for slot in marked:
        slot["keyframe"] = True
    if not marked:
        return {}
    model["keyframe"] = {k: sd[k] for k in ("repo", "pipeline", "variant", "steps", "guidance")}
    # World refs set a keyframe's palette and brushwork, not its layout: at the shared 0.6 the refs' street
    # replaced the subject's setting (wolves in a forest came out on a city street, first Kaggle run).
    scale = {**look_refs.scales(strength), "layout": round(KEYFRAME_LAYOUT * strength, 3)}
    model["keyframe"].update(neg=NEGATIVE, refs=look_refs.payload(refs) if refs else [], ref_scale=scale)
    kind = "styled_keyframe" if refs else "plain_keyframe"
    return {"refs": [p.name for p in refs], "shots": {slot["shot_number"]: kind for slot in marked}}


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
        if slot["seed_b64"]:
            continue
        if slot.get("character"):
            # A stock frame would swap the character's face for whoever is in the footage.
            report["skipped"].append({"shot": slot["shot_number"], "why": "character shot: no stock seed"})
            continue
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
        # A styled-keyframe slot keeps the stock frame as its backup, used if the keyframe fails on Kaggle.
        slot["backup_b64" if slot.get("keyframe") else "seed_b64"] = base64.b64encode(frame.read_bytes()).decode("ascii")
        if slot.get("keyframe"):
            report.setdefault("backups", []).append(slot["shot_number"])
        else:
            report["seeded"] += 1
    return report


# ── notebook source ───────────────────────────────────────────────────────────

# The Wan 2.2 loader, shared by this notebook and genchar's animate (notebook-side code). The recipe is the one that
# survived the bake-off on a T4: prompts are encoded with UMT5 before any denoiser loads, so the 11 GB encoder and
# the experts are never resident together; GGUF experts dequantize to fp16 per layer; the VAE stays fp32; and every
# slot ends by releasing the offload hooks, because a failed slot once left a 9 GB expert on the card.
WAN_LOADER = '''
def _free():
    gc.collect(); torch.cuda.empty_cache()

def wan_embeds(repo, texts):
    """UMT5 embeddings as diffusers' Wan pipeline builds them; bf16 on the GPU, fp32 on the CPU as fallback."""
    from transformers import AutoTokenizer, UMT5EncoderModel
    tok = AutoTokenizer.from_pretrained(repo, subfolder="tokenizer")
    for dev, dt in (("cuda", torch.bfloat16), ("cpu", torch.float32)):
        te, out = None, None
        try:
            te = UMT5EncoderModel.from_pretrained(repo, subfolder="text_encoder", torch_dtype=dt).to(dev)
            out = []
            for t in texts:
                ids = tok([t], padding="max_length", max_length=512, truncation=True, add_special_tokens=True,
                          return_attention_mask=True, return_tensors="pt")
                n = int(ids.attention_mask.sum())
                with torch.no_grad():
                    h = te(ids.input_ids.to(dev), ids.attention_mask.to(dev)).last_hidden_state[0, :n]
                h = torch.cat([h, h.new_zeros(512 - n, h.size(1))])[None].float().cpu()
                if not torch.isfinite(h).all():
                    raise ValueError("non-finite prompt embeddings")
                out.append(h)
            print("[esta] prompts encoded on", dev, flush=True)
        except Exception as e:
            print("[esta] prompt encoding on", dev, "failed:", str(e)[:200], flush=True)
            out = None
        finally:
            te = None; _free()
        if out is not None:
            return out
    raise RuntimeError("prompt encoding failed on cuda and cpu")

def load_wan(model):
    from diffusers import WanImageToVideoPipeline, AutoencoderKLWan
    kw = dict(vae=AutoencoderKLWan.from_pretrained(model["repo"], subfolder="vae", torch_dtype=torch.float32),
              text_encoder=None, torch_dtype=torch.float16)
    if model.get("gguf"):
        from huggingface_hub import hf_hub_download
        from diffusers import WanTransformer3DModel, GGUFQuantizationConfig
        q = GGUFQuantizationConfig(compute_dtype=torch.float16)
        for name, fn in zip(("transformer", "transformer_2"), model["gguf"]):
            kw[name] = WanTransformer3DModel.from_single_file(
                hf_hub_download(model["gguf_repo"], fn), quantization_config=q, config=model["repo"],
                subfolder=name, torch_dtype=torch.float16)
    pipe = WanImageToVideoPipeline.from_pretrained(model["repo"], **kw)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    return pipe

def wan_generate(pipe, model, image, emb, neg, frames, width, height, seed):
    from PIL import ImageOps
    kw = dict(image=ImageOps.fit(image.convert("RGB"), (width, height)), prompt_embeds=emb.to("cuda", torch.float16),
              height=height, width=width, num_frames=frames, num_inference_steps=model["steps"],
              guidance_scale=model["guidance"], generator=torch.Generator("cpu").manual_seed(seed))
    if model.get("gguf"):
        kw["guidance_scale_2"] = model["guidance"]
    if neg is not None and model["guidance"] > 1:
        kw["negative_prompt_embeds"] = neg.to("cuda", torch.float16)
    try:
        return pipe(**kw).frames[0]
    finally:
        pipe.maybe_free_model_hooks(); _free()
'''

NOTEBOOK_CODE = '''# ESTA - generative video on Kaggle's free GPU (SPEC.md Part 6).
# Writes gen_<key>.mp4 + gen_results.json to /kaggle/working for `kernels output`.
import subprocess, sys, json, os, gc, base64, io, traceback
# Reserved-but-fragmented memory, not total size, failed large allocations on the T4 (bake-off): let segments grow.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

SLOTS = json.loads(__SLOTS__)
MODEL = json.loads(__MODEL__)
NEG   = __NEG__
OUT   = "/kaggle/working"

# Weights go to /kaggle/temp, never /kaggle/working: `kernels output` downloads
# the working dir and it is capped at 20 GB. /kaggle/temp is scratch and never collected.
if os.path.isdir("/kaggle/temp"):
    os.makedirs("/kaggle/temp/hf", exist_ok=True)
    os.environ["HF_HOME"] = "/kaggle/temp/hf"

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers", "transformers", "accelerate",
                "gguf", "imageio[ffmpeg]", "sentencepiece", "protobuf", "ftfy"], check=False)

import numpy as np
import torch, diffusers
from diffusers.utils import export_to_video
from PIL import Image

def finish(results, errors):
    with open(os.path.join(OUT, "gen_results.json"), "w") as fh:
        json.dump({"results": results, "errors": errors}, fh)
    print("ESTA_GEN_RESULT::" + json.dumps({"results": results, "errors": errors}))

if not torch.cuda.is_available():
    finish({}, {"_": "no GPU on this kernel - set Accelerator to GPU T4 x2"})
    raise SystemExit

print("[esta] GPU:", torch.cuda.get_device_name(0), flush=True)

def _as_pil(frame):
    """Pipelines return PIL or a float ndarray depending on their output_type default."""
    if isinstance(frame, Image.Image):
        return frame
    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        arr = (arr.clip(0, 1) * 255).astype("uint8")
    return Image.fromarray(arr)

KEYFRAMES, KF_NOTES = {}, {}
__KEYFRAMES__
__WAN_LOADER__

def seed_image(slot):
    """Start image by precedence: character seed, then keyframe, then the stock backup (SPEC.md Parts 5-6)."""
    if slot.get("seed_b64"):
        return Image.open(io.BytesIO(base64.b64decode(slot["seed_b64"]))).convert("RGB")
    if slot["key"] in KEYFRAMES:
        return KEYFRAMES[slot["key"]]
    if slot.get("backup_b64"):
        return Image.open(io.BytesIO(base64.b64decode(slot["backup_b64"]))).convert("RGB")
    return None

texts = [s["prompt"] for s in SLOTS] + ([NEG] if MODEL["guidance"] > 1 else [])
ENC = wan_embeds(MODEL["repo"], texts)
EMB = {s["key"]: ENC[i] for i, s in enumerate(SLOTS)}
NEG_EMB = ENC[-1] if MODEL["guidance"] > 1 else None
pipe = load_wan(MODEL)

def generate(slot):
    """Generate the slot, chaining segments when the shot outruns one clip."""
    image = seed_image(slot)
    if image is None:
        raise RuntimeError("no start image: the keyframe failed and there is no stock backup")
    size = (MODEL["width"], MODEL["height"])
    if slot.get("hd"):
        size = (__HD_W__, __HD_H__)
    frames_all, note = [], {}
    seed = int(slot["shot_number"]) * 7919
    for seg in range(slot["segments"]):
        try:
            out = wan_generate(pipe, MODEL, image, EMB[slot["key"]], NEG_EMB, slot["frames"], size[0], size[1], seed + seg)
        except torch.OutOfMemoryError:
            if size == (MODEL["width"], MODEL["height"]):
                raise
            size = (MODEL["width"], MODEL["height"])
            note["hd_fallback"] = True
            print("[esta] shot", slot["key"], "720p OOM, retrying at", size, flush=True)
            out = wan_generate(pipe, MODEL, image, EMB[slot["key"]], NEG_EMB, slot["frames"], size[0], size[1], seed + seg)
        # Drop the duplicated seam frame on every segment after the first.
        frames_all.extend(out if seg == 0 else out[1:])
        if seg + 1 < slot["segments"]:
            image = _as_pil(out[-1])
        print("[esta] shot", slot["key"], "segment", seg + 1, "/", slot["segments"], flush=True)
    path = os.path.join(OUT, "gen_" + str(slot["key"]) + ".mp4")
    export_to_video(frames_all, path, fps=MODEL["fps"])
    return path, len(frames_all), note

results, errors = {}, {}
for slot in SLOTS:
    key = slot["key"]
    try:
        print("[esta] ---", key, slot["preset"], slot["frames"], "frames |", slot["prompt"][:90], flush=True)
        path, nframes, note = generate(slot)
        results[key] = {"file": os.path.basename(path), "frames": nframes,
                        "fps": MODEL["fps"], "preset": slot["preset"],
                        "shot_number": slot["shot_number"], **note,
                        **({"keyframe": KF_NOTES[key]} if key in KF_NOTES else {})}
        print("OK", key, nframes, "frames", flush=True)
    except Exception as e:
        errors[key] = (str(e) or repr(e))[:250]
        traceback.print_exc()
        print("ERR", key, errors[key], flush=True)
    _free()
    # Checkpoint after every slot: a kernel that times out at 12 h still keeps
    # whatever it finished, because `kernels output` reads /kaggle/working.
    finish(results, errors)

# Lip-sync (SPEC.md Part 4): LatentSync 1.5 repaints the mouth of each talking
# shot to its slice of the voiceover. 1.5 fits a 16 GB T4 (8 GB); 1.6 needs 18 GB.
TALK = [s for s in SLOTS if s.get("audio_b64") and s["key"] in results]
if TALK and MODEL.get("lipsync") == "latentsync":
    pipe = None; _free()
    LS = "/kaggle/temp/LatentSync" if os.path.isdir("/kaggle/temp") else os.path.join(OUT, "LatentSync")
    ready = ""
    try:
        if not os.path.isdir(LS):
            subprocess.run(["git", "clone", "--depth", "1", "https://github.com/bytedance/LatentSync", LS], check=True)
        # Keep Kaggle's CUDA torch: reinstalling it from the repo's pins wastes the session.
        reqs = [l.strip() for l in open(os.path.join(LS, "requirements.txt")) if l.strip() and not l.lower().startswith("torch")]
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *reqs], check=False)
        from huggingface_hub import hf_hub_download
        for f in ("latentsync_unet.pt", "whisper/tiny.pt"):
            hf_hub_download("ByteDance/LatentSync-1.5", f, local_dir=os.path.join(LS, "checkpoints"))
    except Exception as e:
        ready = "lipsync setup failed: " + (str(e) or repr(e))[:200]
    for slot in TALK:
        key = slot["key"]
        if ready:
            results[key]["lipsync"] = ready; continue
        try:
            wav = os.path.join(OUT, "talk_" + key + ".wav")
            open(wav, "wb").write(base64.b64decode(slot["audio_b64"]))
            dur = float(slot["audio_seconds"])
            # Loop the generated clip to the line's length so the synced clip covers the whole line.
            looped = os.path.join(OUT, "loop_" + key + ".mp4")
            # LatentSync reads 25 fps video; AniSora renders 16 fps.
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", os.path.join(OUT, results[key]["file"]),
                            "-t", str(dur), "-r", "25", "-an", looped], check=True)
            synced = os.path.join(OUT, "gen_" + key + "_talk.mp4")
            r = subprocess.run([sys.executable, "-m", "scripts.inference", "--unet_config_path", "configs/unet/stage2.yaml",
                                "--inference_ckpt_path", "checkpoints/latentsync_unet.pt", "--inference_steps", "20",
                                "--guidance_scale", "1.5", "--video_path", looped, "--audio_path", wav,
                                "--video_out_path", synced], cwd=LS, capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(synced):
                results[key].update({"synced_file": os.path.basename(synced), "synced_seconds": dur, "lipsync": "ok"})
                print("OK lipsync", key, flush=True)
            else:
                tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["no output"]
                results[key]["lipsync"] = ("no face found" if "face" in tail[0].lower() else "lipsync failed: " + tail[0])[:200]
                print("ERR lipsync", key, results[key]["lipsync"], flush=True)
            for f in (wav, looped):
                os.path.exists(f) and os.remove(f)
        except Exception as e:
            results[key]["lipsync"] = "lipsync failed: " + (str(e) or repr(e))[:200]
        gc.collect(); torch.cuda.empty_cache()
        finish(results, errors)
'''


# The styled-keyframe pass (SPEC.md Part 5): SDXL plus the look refs draws each marked slot's first frame, then
# is freed before the video model loads. A failure leaves the slot on text-to-video, never a failed run.
KEYFRAME_CODE = '''
def keyframe_pass():
    from PIL import ImageOps
    KF = MODEL["keyframe"]
    kf_cls = getattr(diffusers, KF["pipeline"])
    # The fp16-safe VAE with force_upcast off: the stock SDXL VAE flips itself to fp32 to decode, and an
    # OOM mid-decode left it there, so every later keyframe failed on Half vs float.
    vae = diffusers.AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
    vae.config.force_upcast = False
    try:
        pipe = kf_cls.from_pretrained(KF["repo"], vae=vae, torch_dtype=torch.float16, use_safetensors=True,
                                      variant=KF.get("variant") or None)
    except Exception:
        pipe = kf_cls.from_pretrained(KF["repo"], vae=vae, torch_dtype=torch.float16, use_safetensors=True)
    pipe.set_progress_bar_config(disable=True)
    REFS, REF_SCALE = KF["refs"], KF["ref_scale"]
__IPA__
    # SDXL + the IP-Adapter image encoder + a 1216x832 decode overflow one T4 by the second image when all
    # resident. Offload goes on after the adapter loads, or its image encoder stays on the CPU unhooked.
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_tiling()
    # SDXL draws at its own landscape/portrait bucket; the frame is then fitted to the video size.
    w, h = (1216, 832) if MODEL["width"] >= MODEL["height"] else (832, 1216)
    for slot in SLOTS:
        if not slot.get("keyframe"):
            continue
        key = slot["key"]
        try:
            gen = torch.Generator("cuda").manual_seed(int(slot["shot_number"]) * 7919)
            img = pipe(prompt=slot.get("kf_prompt") or slot["prompt"], negative_prompt=KF["neg"], width=w, height=h,
                       num_inference_steps=KF["steps"], guidance_scale=KF["guidance"], generator=gen,
                       **IPA_KW).images[0]
            KEYFRAMES[key] = ImageOps.fit(img, (MODEL["width"], MODEL["height"]))
            KEYFRAMES[key].save(os.path.join(OUT, "kf_" + key + ".png"))
            KF_NOTES[key] = "ok" + (" (" + REF_ERROR + ")" if REF_ERROR else "")
            print("[esta] keyframe", key, flush=True)
        except Exception as e:
            KF_NOTES[key] = "keyframe failed: " + (str(e) or repr(e))[:150]
            print("[esta]", key, KF_NOTES[key], flush=True)
        gc.collect(); torch.cuda.empty_cache()
    del pipe, vae

try:
    keyframe_pass()
except Exception as e:
    print("[esta] keyframe pass failed, slots fall back to their stock backup:", e, flush=True)
    traceback.print_exc()
gc.collect(); torch.cuda.empty_cache()
'''


def build_notebook_code(slots: list[dict], model: dict, negative: str) -> str:
    """Fill the notebook template by placeholder substitution.

    Substitution rather than an f-string because the template is full of dict
    literals, and doubling every brace to survive .format() is how this kind of
    template rots.
    """
    lean = [
        {k: s.get(k, "") for k in ("key", "shot_number", "preset", "prompt", "segments", "frames", "hd", "seed_b64",
                                    "audio_b64", "audio_seconds")}
        for s in slots
    ]
    for row, slot in zip(lean, slots):
        if slot.get("keyframe"):
            row["keyframe"] = True
            row["kf_prompt"] = slot.get("kf_prompt", "")
        if slot.get("backup_b64"):
            row["backup_b64"] = slot["backup_b64"]
    kf = ""
    if model.get("keyframe"):
        # No refs: plain SDXL keyframes, with no IP-Adapter code in the notebook at all.
        ipa = look_refs.NOTEBOOK_IPA if model["keyframe"]["refs"] else 'IPA_KW, REF_ERROR = {}, ""\n'
        kf = KEYFRAME_CODE.replace("__IPA__", textwrap.indent(ipa, "    "))
    return (
        NOTEBOOK_CODE
        .replace("__KEYFRAMES__", kf)
        .replace("__WAN_LOADER__", WAN_LOADER)
        .replace("__HD_W__", str(HD_SIZE[0])).replace("__HD_H__", str(HD_SIZE[1]))
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


def check_clip(path: Path, seconds: float) -> str:
    """"" when the clip holds up over the shot's own length, else "dark" or "collapse" (SPEC.md Part 6, decision 5).

    Dark: any sample's mean brightness under CHECK_DARK (one bake-off clip faded to black). Collapse: the picture's
    structure stops resembling frame 0, measured as the correlation of blurred, brightness-normalised grayscale
    thumbnails; a push-in or a light change keeps it positive (bake-off minimum 0.15), a melt into unrelated shapes
    sends it negative (-0.13, -0.31). Pixel difference alone could not tell a melt from dusk falling."""
    import cv2
    import numpy as np

    def norm(frame):
        g = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36)).astype(np.float32), (5, 5), 0)
        return (g - g.mean()) / (g.std() + 1e-6)

    cap = cv2.VideoCapture(str(path))
    ok, first = cap.read()
    if not ok:
        return "unreadable"
    ref, t = norm(first), CHECK_STEP
    while t <= seconds + 1e-6:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        if frame.mean() < CHECK_DARK:
            return "dark"
        if float((ref * norm(frame)).mean()) < CHECK_COLLAPSE:
            return "collapse"
        t += CHECK_STEP
    return ""


def _feed_path(path: Path) -> str:
    """Repo-root-relative, like the assets skill writes, so a session folder stays portable; absolute if outside."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def apply_results(session_dir: Path, results: dict, errors: dict, out_dir: Path | dict) -> dict:
    """Move generated clips into source_pool and publish them on the assets feed.

    Publishing as an ordinary assets_progress line is the whole integration:
    render already resolves that feed with later-line-wins, so a generated clip
    supersedes the stock pick for the same shot with no render change at all.
    Nothing is deleted — the stock file stays as the fallback.
    """
    pool = session_dir / "assets" / "source_pool"
    pool.mkdir(parents=True, exist_ok=True)
    feed = session_dir / "assets_progress.jsonl"
    applied, failed, lines, skipped = [], [], [], []
    # Re-running apply on the same output publishes nothing twice: rows carry the clip's hash (Part 6 edge cases).
    published = set()
    if feed.exists():
        for line in feed.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("source") == "genvideo" and row.get("gen_sha"):
                published.add((str(row.get("key")), row["gen_sha"]))

    for key, info in sorted(results.items(), key=lambda kv: str(kv[0])):
        # A split run downloads each half to its own folder (SPEC.md Part 6, decision 4).
        here = out_dir[key] if isinstance(out_dir, dict) else out_dir
        synced = here / info.get("synced_file", "") if info.get("synced_file") else None
        talk = bool(synced and synced.exists() and synced.stat().st_size > 0)
        src = synced if talk else here / info.get("file", f"gen_{key}.mp4")
        if not src.exists() or src.stat().st_size == 0:
            failed.append({"key": key, "why": "clip missing from kernel output"})
            continue
        sha = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
        if (str(key), sha) in published:
            skipped.append(key)
            continue
        fps = float(info.get("fps") or 24)
        nframes = int(info.get("frames") or 0)
        clip_seconds = round(nframes / fps, 3) if nframes and fps else 0.0
        shot_number = info.get("shot_number")
        if shot_number is None and str(key).split("-")[0].isdigit():
            shot_number = int(str(key).split("-")[0])
        want = _shot_durations(session_dir).get(shot_number) or 0.0

        # A clip that went dark or collapsed never reaches the edit: its keyframe stands in as a still, and render
        # gives it the shot's planned camera move (SPEC.md Part 6, decision 5).
        reason = check_clip(src, want or clip_seconds)
        if reason:
            kf = here / f"kf_{key}.png"
            if not kf.exists():
                failed.append({"key": key, "why": f"clip check: {reason}; no keyframe to fall back on"})
                continue
            still = pool / f"genkf_{key}.png"
            still.write_bytes(kf.read_bytes())
            lines.append({"shot_number": shot_number, "key": str(key), "ok": True, "source": "genvideo",
                          "asset_type": "image", "url": "", "file": _feed_path(still), "search_query": "",
                          "in_point": 0.0, "out_point": 0.0, "visual_verdict": "", "visual_confidence": 0,
                          "error": "", "gen_check": reason, "gen_sha": sha})
            applied.append({"key": key, "file": _feed_path(still), "gen_check": reason})
            continue

        dest = pool / f"gen_{key}{'_talk' if talk else ''}.mp4"
        dest.write_bytes(src.read_bytes())
        feed_path = _feed_path(dest)

        # Trim to the shot's own duration rather than publishing the whole clip.
        # Two reasons, and the second is the important one: the model always
        # emits its full trained window (~5 s) regardless of what the shot needs,
        # AND diffusion quality decays toward the tail — verified on the first
        # live run, where frame 120 of 121 had smeared into incoherence while
        # frame 60 was clean. Cutting to the shot length discards the drifted
        # tail for free. Only ever trims; a shot longer than the clip keeps all.
        if talk:
            clip_seconds = float(info.get("synced_seconds") or clip_seconds)
        out_point = clip_seconds
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
            "gen_sha": sha,
            **({"lipsync": info["lipsync"]} if info.get("lipsync") else {}),
        })
        applied.append({"key": key, "file": feed_path, "seconds": out_point,
                        "preset": info.get("preset", ""), **({"lipsync": info["lipsync"]} if info.get("lipsync") else {})})

    if lines:
        with open(feed, "a", encoding="utf-8") as fh:
            for rec in lines:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    marker = {
        "already_published": skipped,
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

    missing, hub_warning = hub_missing(model)
    if missing:
        raise ValueError(f"{args.model}: {', '.join(missing)} not found in {model['gguf_repo']} on the Hub; "
                         f"try --model wan5b")
    characters = attach_character_seeds(session_dir, slots, model)
    model["lipsync"] = args.lipsync
    talking = attach_talk_audio(session_dir, slots) if args.lipsync != "off" else {}
    keyframes = attach_keyframes(session_dir, slots, model, args.model, args.ref_strength)
    seeding = {"seeded": 0, "skipped": []}
    if args.seed_from_assets:
        seeding = attach_seed_images(session_dir, slots, model)
    seeding["seeded"] += sum(1 for v in characters.values() if v in ("lora_keyframe", "ref"))
    seeding["seeded"] += len(keyframes.get("shots", {}))
    seeding["characters"] = characters
    if keyframes:
        seeding["keyframes"] = keyframes
    if seeding["seeded"] < len(slots):
        raise ValueError(f"{args.model} is image-to-video only and {len(slots) - seeding['seeded']} slot(s) have "
                         f"no start image ({seeding['seeded']}/{len(slots)} seeded); is --ref-strength or the keyframe "
                         f"pass off?")

    half = getattr(args, "half", "")
    halves = split_slots(slots, getattr(args, "split", 2))
    base = slugify(session_dir.name, prefix="esta-gen-")
    runs = []
    for i, part in enumerate(halves):
        tag = "ab"[i]
        if half and half != tag:
            continue
        code = build_notebook_code(part, model, presets["negative_default"])
        kernel_id = f"{kaggle_username()}/{base if tag == 'a' else base[:48].rstrip('-') + '-b'}"
        build_dir = session_dir / "assets" / ("gen_kernel" if tag == "a" else "gen_kernel_b")
        nb_path = write_kernel_dir(build_dir, code, kernel_id, ACCELERATORS.get(args.accelerator, ACCELERATORS["t4"]))
        size = nb_path.stat().st_size
        if size > MAX_NOTEBOOK_BYTES:
            raise ValueError(f"notebook {tag} is {size / 1e6:.1f} MB (seed images) — over the "
                             f"{MAX_NOTEBOOK_BYTES / 1e6:.0f} MB ceiling. Push fewer slots per run.")
        runs.append({"half": tag, "kernel": kernel_id, "build_dir": build_dir, "bytes": size,
                     "slots": [s["key"] for s in part], "frames": sum(s["frames"] * s["segments"] for s in part)})

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "kernel": runs[0]["kernel"],
                          "kernels": [{k: r[k] for k in ("half", "kernel", "slots", "frames", "bytes")} for r in runs],
                          "count": len(slots), "notebook_bytes": runs[0]["bytes"], "talking": talking,
                          "slots": [{k: s[k] for k in ("key", "preset", "prompt", "segments", "frames")} for s in slots],
                          "seeding": seeding, **({"hub_warning": hub_warning} if hub_warning else {})},
                         ensure_ascii=False))
        return

    pushed = []
    for r in runs:
        ok, log = push_kernel(r["build_dir"])
        pushed.append({"half": r["half"], "kernel": r["kernel"], "ok": ok, "slots": r["slots"], "log": log[-300:]})
    prev = json.loads(_state_path(session_dir).read_text(encoding="utf-8")) if half and _state_path(session_dir).exists() else {}
    kernels = {k["half"]: k for k in prev.get("kernels", [])}
    kernels.update({p["half"]: {k: p[k] for k in ("half", "kernel", "slots", "ok")} for p in pushed})
    state = {
        "kernel": runs[0]["kernel"],
        "kernels": [kernels[h] for h in sorted(kernels)],
        "model": args.model,
        "accelerator": args.accelerator,
        "count": len(slots),
        "slots": [{k: s[k] for k in ("key", "shot_number", "preset", "segments", "frames")} for s in slots],
        "seeding": seeding,
        "talking": talking,
    }
    _state_path(session_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")
    failed = [p for p in pushed if not p["ok"]]
    print(json.dumps({
        "ok": not failed, "kernels": pushed, "count": len(slots), "seeding": seeding,
        "urls": [f"https://www.kaggle.com/code/{p['kernel']}" for p in pushed],
        **({"retry": "push --half " + " / --half ".join(p["half"] for p in failed)} if failed else {}),
    }, ensure_ascii=False))


def hub_missing(model: dict) -> tuple[list[str], str]:
    """(GGUF files the Hub says are gone, warning). Checked before pushing so a renamed or deleted file fails here,
    not as a download error 20 minutes into a Kaggle run. An unreachable Hub only warns: Kaggle may still reach it."""
    import urllib.error
    import urllib.request
    missing, warn = [], ""
    for fn in model.get("gguf", []):
        url = f"https://huggingface.co/{model['gguf_repo']}/resolve/main/{fn}"
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                missing.append(fn)
            else:
                warn = f"Hub check inconclusive (HTTP {e.code}); files not verified"
        except Exception as e:  # noqa: BLE001 - offline here is not offline on Kaggle
            warn = f"could not reach the Hub ({str(e)[:80]}); files not verified"
    return missing, warn


def split_slots(slots: list[dict], split: int) -> list[list[dict]]:
    """Two halves of near-equal GPU work (frames x segments), or one run. Kaggle allows two GPU runs at once
    (SPEC.md Part 6, decision 4): splitting halves the wall time. Greedy by largest slot keeps the halves
    within one slot's work of each other."""
    if split < 2 or len(slots) < SPLIT_MIN_SLOTS:
        return [slots]
    halves, load = [[], []], [0, 0]
    for s in sorted(slots, key=lambda s: -s["frames"] * s["segments"]):
        i = 0 if load[0] <= load[1] else 1
        halves[i].append(s)
        load[i] += s["frames"] * s["segments"]
    order = {s["key"]: n for n, s in enumerate(slots)}
    return [sorted(h, key=lambda s: order[s["key"]]) for h in halves if h]


def _kernels(session_dir: Path, explicit: str) -> list[dict]:
    """The run's kernels: [{half, kernel, slots}], from the push state; an explicit ref is a single run."""
    if explicit:
        return [{"half": "a", "kernel": explicit, "slots": []}]
    state = _state_path(session_dir)
    if state.exists():
        data = json.loads(state.read_text(encoding="utf-8"))
        if data.get("kernels"):
            return data["kernels"]
        if data.get("kernel"):
            return [{"half": "a", "kernel": data["kernel"], "slots": [s["key"] for s in data.get("slots", [])]}]
    return [{"half": "a", "kernel": f"{kaggle_username()}/{slugify(session_dir.name, prefix='esta-gen-')}", "slots": []}]


def cmd_status(args: argparse.Namespace) -> None:
    runs, not_started = [], []
    for k in _kernels(Path(args.session), args.kernel):
        if k.get("ok") is False:
            # Its push failed (quota, or the two-run limit): there is no run to poll.
            not_started.append(k["half"])
            runs.append({"half": k["half"], "kernel": k["kernel"], "state": "not_started",
                         "raw": f"push failed; run `push --half {k['half']}`"})
            continue
        state, raw = kernel_status(k["kernel"])
        runs.append({"half": k["half"], "kernel": k["kernel"], "state": state, "raw": raw})
    states = {r["state"] for r in runs if r["state"] != "not_started"}
    overall = ("running" if states & {"running", "queued"} else
               "complete" if states == {"complete"} else
               "error" if states & {"error", "cancel"} else next(iter(states), ""))
    print(json.dumps({"ok": all(r["state"] for r in runs), "state": overall, "kernel": runs[0]["kernel"],
                      "kernels": runs, **({"not_started": not_started} if not_started else {})}, ensure_ascii=False))


def cmd_apply(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    results, errors, missing, refs = {}, {}, [], []
    base_out = Path(args.output_dir) if args.output_dir else session_dir / "assets" / "gen_out"
    outs = {}
    for k in _kernels(session_dir, args.kernel):
        out_dir = base_out if k["half"] == "a" else base_out.with_name(base_out.name + "_b")
        out_dir.mkdir(parents=True, exist_ok=True)
        refs.append(k["kernel"])
        if not args.skip_download:
            try:
                fetch_output(k["kernel"], out_dir)
            except Exception as e:  # noqa: BLE001 - one half failing must not sink the other
                errors.update({key: f"half {k['half']} not fetched: {str(e)[:120]}" for key in k.get("slots") or [k["half"]]})
                missing += list(k.get("slots") or [])
                continue
        res = out_dir / "gen_results.json"
        if not res.exists():
            missing += list(k.get("slots") or [])
            errors.update({key: f"half {k['half']} wrote no results (still running, or failed early)"
                           for key in k.get("slots") or [k["half"]]})
            continue
        raw = json.loads(res.read_text(encoding="utf-8"))
        for key, info in raw.get("results", {}).items():
            results[key] = info
            outs[key] = out_dir
        errors.update(raw.get("errors", {}))
    if not results and not errors:
        raise FileNotFoundError(f"no gen_results.json under {base_out} — the kernels may still be running (check `status`)")
    summary = apply_results(session_dir, results, errors, outs)
    print(json.dumps({"ok": True, "kernels": refs, "missing": missing, **summary}, ensure_ascii=False))


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
    p.add_argument("--ref-strength", type=float, default=1.0,
                   help="How hard the session's look refs pull on styled keyframes; 0 turns the pass off")
    p.add_argument("--seed-from-assets", action="store_true",
                   help="Image-to-video: seed each slot from the frame already fetched for that shot")
    p.add_argument("--dry-run", action="store_true", help="Build and report, don't push")
    p.add_argument("--split", type=int, default=2, choices=[1, 2],
                   help=f"Split {SPLIT_MIN_SLOTS}+ slots across two Kaggle runs (Kaggle allows two GPU runs at once)")
    p.add_argument("--half", default="", choices=["", "a", "b"],
                   help="Push only one half of a split run, e.g. after the second hit the two-run limit")
    p.add_argument("--lipsync", default="latentsync", choices=["latentsync", "off"],
                   help="Lip-sync shots marked generate.talk with LatentSync 1.5 (SPEC.md Part 4)")
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
