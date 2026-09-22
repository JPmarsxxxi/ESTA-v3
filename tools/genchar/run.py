"""Original-character design on Kaggle's free GPU — step 1 of the 2D character lane.

The problem this solves: you can't animate a character that doesn't exist yet,
and you can't keep a character on-model between shots without a locked-down
design to anchor to. So before any video work, a character needs (a) a design
the user actually likes and (b) enough images of that design from enough angles
to train a LoRA on later.

The flow, and it is a generate-then-cull loop, not an automated pipeline:

  1. `explore` — N variations from a text description. Cheap and fast (seconds
                 per image), so the user looks at a grid and points at one.
  2. `pick`    — record the chosen variation.
  3. `sheet`   — generate a POOL of varied candidates (default 40) across angles,
                 expressions and poses. Not all will be on-model; that's expected.
  4. `contact` — build grids of a run's images. Every run ends here, because
                 looking at the output is the workflow.
  5. `cull`    — the user names the on-model ones. Those become the LoRA set.

Consistency comes from the LoRA trained on the culled set, NOT from any trick at
generation time. An earlier version tried seed-locking to force consistency and
it failed instructively — see the SHEET_VIEWS comment.

Everything lands in `characters/<name>/` at the repo root, NOT in a session
folder — a character outlives any one video, the same way voice_samples/ does.

Model: an anime-finetuned SDXL. SDXL is the right tier here because it fits a
free 16 GB T4 comfortably in fp16, generates in seconds rather than minutes, and
has by far the deepest anime LoRA/checkpoint ecosystem to build on later.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, REPO_ROOT, ensure_dataset, fetch_output, kaggle_username,
    kernel_status, notebook_code, push_kernel, slugify, use_utf8_stdout,
    wait_dataset_ready, write_kernel_dir,
)

use_utf8_stdout()

CHARACTERS_DIR = REPO_ROOT / "characters"

MODELS = {
    "animagine": {
        "repo": "cagliostrolab/animagine-xl-4.0",
        "pipeline": "StableDiffusionXLPipeline",
        "dtype": "float16",
        "variant": "",
        "width": 832,
        "height": 1216,
        "steps": 28,
        "guidance": 5.0,
        "notes": "Anime SDXL finetune, 8.4M-image dataset. The default — T4-friendly and the deepest anime ecosystem.",
    },
    "sdxl": {
        "repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "pipeline": "StableDiffusionXLPipeline",
        "dtype": "float16",
        "variant": "fp16",
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "guidance": 7.0,
        "notes": "Plain SDXL. Use for non-anime / semi-realistic character styles.",
    },
}
DEFAULT_MODEL = "animagine"

# Anime SDXL finetunes are tag-trained, so quality tags carry real weight.
QUALITY_TAGS = "masterpiece, best quality, very aesthetic, absurdres, highly detailed"
NEGATIVE = ("lowres, bad anatomy, bad hands, text, error, missing finger, "
            "extra digits, fewer digits, cropped, worst quality, low quality, "
            "low score, bad score, average score, signature, watermark, username, blurry")

# A LoRA training set needs VARIETY — the same character across different poses,
# angles and expressions — so the model learns the character rather than
# memorising one image.
#
# The first version of this held one seed fixed across every view, on the theory
# that a fixed seed preserves identity. Tested live, that failed badly: the seed
# didn't just preserve identity, it **overrode the prompt**. All six expression
# close-ups came back as the same neutral face (the "eyes closed" one had its
# eyes open), and "from behind" rendered as another three-quarter view. A pool of
# near-identical images teaches a LoRA almost nothing.
#
# So seeds vary per candidate now, and consistency comes from the LoRA trained on
# the images the *user* culls — the machine generates cheap options, their taste
# picks the on-model ones. Same principle as the shot picker.
SHEET_VIEWS = [
    ("front", "front view, facing viewer, upper body"),
    ("side", "side view, profile, upper body"),
    ("back", "back view, seen from behind, facing away from viewer, upper body"),
    ("three-quarter", "three-quarter view, looking at viewer, upper body"),
    ("full-body", "full body shot, standing, facing viewer, whole figure in frame"),
    ("full-body-side", "full body shot, standing, side view, whole figure in frame"),
    ("full-body-back", "full body shot, standing, seen from behind, whole figure in frame"),
    ("smile", "close-up portrait, smiling, happy, cheerful expression"),
    ("serious", "close-up portrait, serious determined expression, furrowed brow"),
    ("surprised", "close-up portrait, surprised, shocked, wide open eyes, open mouth"),
    ("angry", "close-up portrait, angry, furious expression, gritted teeth"),
    ("sad", "close-up portrait, sad, crying, tearful, downcast eyes"),
    ("closed-eyes", "close-up portrait, eyes closed, peaceful calm expression"),
    ("laughing", "close-up portrait, laughing, eyes squeezed shut, wide open mouth"),
    ("action", "dynamic action pose, mid-motion, swinging weapon, motion blur"),
    ("sitting", "sitting down, relaxed pose, full body"),
]


# ── character store ───────────────────────────────────────────────────────────

def char_dir(name: str) -> Path:
    return CHARACTERS_DIR / slugify(name)


def load_char(name: str) -> dict:
    path = char_dir(name) / "character.json"
    if not path.exists():
        raise FileNotFoundError(f"no character {name!r} — run `explore` first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_char(name: str, data: dict) -> Path:
    d = char_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "character.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ── notebook ──────────────────────────────────────────────────────────────────

# Shared environment prep. Both notebooks need the identical setup, and keeping
# it in one string is not cosmetic: the torchao removal was fixed in the training
# notebook first and NOT here, so LoRA loading failed with the exact error that
# had already been solved once.
ENV_PREAMBLE = '''import subprocess, sys, json, os, gc, glob, shutil, traceback

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "diffusers>=0.33.0", "transformers", "accelerate", "peft",
                "sentencepiece", "protobuf"], check=False)
# Kaggle preinstalls torchao 0.10.0; peft refuses to build or load LoRA layers
# unless it is >0.16 ("Found an incompatible version of torchao"). Nothing here
# needs it, and removing it is safer than upgrading, which drags torch along.
subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"], check=False)
'''

NOTEBOOK = '''# ESTA - character design on Kaggle's free GPU.
# Writes numbered PNGs + results.json to /kaggle/working for `kernels output`.
__ENV__

import torch, diffusers

JOBS  = json.loads(__JOBS__)
MODEL = json.loads(__MODEL__)
NEG   = __NEG__
OUT   = "/kaggle/working"

def finish(results, errors):
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump({"results": results, "errors": errors}, fh)

if not torch.cuda.is_available():
    finish({}, {"_": "no GPU on this kernel"})
    raise SystemExit

print("[esta] GPU:", torch.cuda.get_device_name(0), flush=True)
cls = getattr(diffusers, MODEL["pipeline"])
kw = dict(torch_dtype=getattr(torch, MODEL["dtype"]), use_safetensors=True)
# Only some repos publish a separate fp16 weight variant. Asking for one that
# isn't there is a hard ValueError, not a fallback — so try it, then retry plain.
try:
    pipe = cls.from_pretrained(MODEL["repo"], variant=MODEL.get("variant") or None, **kw)
except Exception as e:
    print("[esta] variant load failed (" + str(e)[:80] + "), retrying without", flush=True)
    pipe = cls.from_pretrained(MODEL["repo"], **kw)
pipe = pipe.to("cuda")
# SDXL fits a 16 GB T4 outright, so keep it resident and only slice the VAE —
# far faster than the sequential offload the video models need.
try:
    pipe.vae.enable_slicing()
except Exception:
    pass
pipe.set_progress_bar_config(disable=True)

# Optional character LoRA, mounted as a dataset because it's ~90 MB. This is
# what makes the character reproducible: the trigger token in each prompt pulls
# the trained identity back out.
LORA = MODEL.get("lora_slug") or ""
if LORA:
    import glob as _glob
    # Search all of /kaggle/input recursively rather than assuming the mount is
    # named after the dataset slug — it isn't always, and a wrong guess fails the
    # whole run after the model has already loaded.
    hits = (_glob.glob("/kaggle/input/" + LORA + "/**/*.safetensors", recursive=True)
            or _glob.glob("/kaggle/input/**/*.safetensors", recursive=True))
    if not hits:
        raise RuntimeError("no .safetensors anywhere under /kaggle/input; contents: "
                           + str(_glob.glob("/kaggle/input/*"))[:300])
    pipe.load_lora_weights(hits[0])
    pipe.fuse_lora(lora_scale=MODEL.get("lora_scale", 0.9))
    print("[esta] loaded LoRA", hits[0], "scale", MODEL.get("lora_scale", 0.9), flush=True)

results, errors = {}, {}
for job in JOBS:
    key = job["key"]
    try:
        gen = torch.Generator("cuda").manual_seed(job["seed"])
        img = pipe(prompt=job["prompt"], negative_prompt=NEG,
                   width=MODEL["width"], height=MODEL["height"],
                   num_inference_steps=MODEL["steps"],
                   guidance_scale=MODEL["guidance"], generator=gen).images[0]
        name = key + ".png"
        img.save(os.path.join(OUT, name))
        results[key] = {"file": name, "seed": job["seed"], "label": job.get("label", "")}
        print("OK", key, "seed", job["seed"], flush=True)
    except Exception as e:
        errors[key] = (str(e) or repr(e))[:250]
        traceback.print_exc()
        print("ERR", key, errors[key], flush=True)
    gc.collect(); torch.cuda.empty_cache()
    # Checkpoint every image so a timeout still yields what finished.
    finish(results, errors)

print("ESTA_CHAR_RESULT::" + json.dumps({"results": results, "errors": errors}))
'''


def build_jobs_explore(desc: str, count: int, base_seed: int) -> list[dict]:
    """N variations of one description — same prompt, different seeds.

    Varying only the seed is deliberate: it isolates "what does this description
    look like" from "what did I ask for", so the user is choosing a face rather
    than choosing between four different briefs.
    """
    prompt = f"{QUALITY_TAGS}, 1 character, original character, {desc}, simple background"
    return [{"key": f"v{i:02d}", "prompt": prompt, "seed": base_seed + i * 1000,
             "label": f"variation {i}"} for i in range(count)]


def build_jobs_sheet(desc: str, base_seed: int, count: int) -> list[dict]:
    """A pool of candidates for the user to cull into a LoRA training set.

    Views cycle so the pool covers angles, expressions and poses evenly, and the
    seed advances on every candidate so each is a genuinely different draw. Not
    all of them will be on-model — that's the point. `cull` is where taste picks.
    """
    jobs = []
    for i in range(count):
        name, view = SHEET_VIEWS[i % len(SHEET_VIEWS)]
        jobs.append({
            "key": f"c{i:03d}-{name}",
            "prompt": f"{QUALITY_TAGS}, 1 character, original character, {desc}, "
                      f"{view}, simple background, plain background",
            "seed": base_seed + i * 7919,   # prime stride: no accidental seed reuse
            "label": name,
        })
    return jobs


def push_job(name: str, jobs: list[dict], model: dict, mode: str,
             accelerator: str, dry_run: bool) -> dict:
    code = notebook_code(NOTEBOOK, env=ENV_PREAMBLE, jobs=repr(json.dumps(jobs)),
                         model=repr(json.dumps(model)), neg=repr(NEGATIVE))
    slug = slugify(name, mode, prefix="esta-char-")
    kernel_id = f"{kaggle_username()}/{slug}"
    build_dir = char_dir(name) / "_kernel"
    write_kernel_dir(build_dir, code, kernel_id, ACCELERATORS.get(accelerator, "NvidiaTeslaT4"))

    out = {"ok": True, "kernel": kernel_id, "count": len(jobs), "mode": mode,
           "url": f"https://www.kaggle.com/code/{kernel_id}"}
    if dry_run:
        out["dry_run"] = True
        out["jobs"] = [{"key": j["key"], "seed": j["seed"], "prompt": j["prompt"][:120]}
                       for j in jobs]
        return out
    ok, blob = push_kernel(build_dir)
    out["ok"] = ok
    out["log"] = blob[-300:]
    return out


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_explore(args: argparse.Namespace) -> None:
    model = dict(MODELS[args.model])
    jobs = build_jobs_explore(args.desc, args.count, args.seed)
    res = push_job(args.name, jobs, model, "explore", args.accelerator, args.dry_run)
    if not args.dry_run and res["ok"]:
        save_char(args.name, {"name": args.name, "desc": args.desc, "model": args.model,
                              "stage": "explore", "kernel": res["kernel"],
                              "base_seed": args.seed, "chosen_seed": None})
    print(json.dumps(res, ensure_ascii=False))


def cmd_pick(args: argparse.Namespace) -> None:
    """Record the variation the user chose; `sheet` builds on its seed."""
    data = load_char(args.name)
    results = json.loads((char_dir(args.name) / "explore" / "results.json")
                         .read_text(encoding="utf-8")).get("results", {})
    if args.variation not in results:
        raise ValueError(f"no variation {args.variation!r}; have: {', '.join(sorted(results))}")
    data["chosen_seed"] = results[args.variation]["seed"]
    data["chosen_variation"] = args.variation
    data["stage"] = "picked"
    save_char(args.name, data)
    print(json.dumps({"ok": True, "name": args.name, "variation": args.variation,
                      "seed": data["chosen_seed"]}, ensure_ascii=False))


def cmd_sheet(args: argparse.Namespace) -> None:
    data = load_char(args.name)
    seed = data.get("chosen_seed")
    if seed is None:
        raise ValueError(f"no variation picked yet — run `pick --name {args.name} --variation vNN`")
    model = dict(MODELS[data.get("model", DEFAULT_MODEL)])
    jobs = build_jobs_sheet(data["desc"], seed, args.count)
    res = push_job(args.name, jobs, model, "sheet", args.accelerator, args.dry_run)
    if not args.dry_run and res["ok"]:
        data["stage"] = "sheet"
        data["sheet_kernel"] = res["kernel"]
        save_char(args.name, data)
    print(json.dumps(res, ensure_ascii=False))


TRAIN_NOTEBOOK = '''# ESTA - character LoRA training on Kaggle's free GPU.
# Reads the image dataset mounted read-only at /kaggle/input, writes the trained
# LoRA + results.json to /kaggle/working for `kernels output`.
__ENV__

CFG = json.loads(__CFG__)
OUT = "/kaggle/working"
DATA = "/kaggle/input/" + CFG["dataset_slug"]

def finish(ok, detail):
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump({"ok": ok, "detail": detail, "trigger": CFG["trigger"]}, fh)
    print("ESTA_LORA_RESULT::" + json.dumps({"ok": ok, "detail": str(detail)[:300]}))

# Training also needs the optimiser and dataset loader.
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "bitsandbytes", "datasets"], check=False)

import torch
if not torch.cuda.is_available():
    finish(False, "no GPU on this kernel"); raise SystemExit
print("[esta] GPU:", torch.cuda.get_device_name(0), flush=True)

# Stage the dataset into a writable dir — /kaggle/input is read-only and the
# HF imagefolder loader wants to drop a cache beside the images.
WORKDIR = "/kaggle/tmp/train"
os.makedirs(WORKDIR, exist_ok=True)
for f in glob.glob(os.path.join(DATA, "*")):
    shutil.copy(f, WORKDIR)
n_imgs = len(glob.glob(os.path.join(WORKDIR, "*.png"))) + len(glob.glob(os.path.join(WORKDIR, "*.jpg")))
print("[esta] training images:", n_imgs, flush=True)
if n_imgs == 0:
    finish(False, "no images found in " + DATA); raise SystemExit

# Fetch the official SDXL DreamBooth-LoRA script rather than vendoring a copy.
# The ref MUST match the installed diffusers, not `main`: every example script
# starts with check_min_version() against the dev version of the branch it lives
# on, so main's copy hard-fails on any pip release ("requires a source install
# ... but the version found is 0.37.1"). "auto" pins to the installed tag.
import diffusers
ref = CFG["diffusers_ref"]
if ref == "auto":
    ref = "v" + diffusers.__version__
print("[esta] diffusers", diffusers.__version__, "-> script ref", ref, flush=True)
script = "/kaggle/tmp/train_dreambooth_lora_sdxl.py"
base = "https://raw.githubusercontent.com/huggingface/diffusers/"
tail_url = "/examples/dreambooth/train_dreambooth_lora_sdxl.py"
if subprocess.run(["wget", "-q", "-O", script, base + ref + tail_url]).returncode != 0 \\
        or os.path.getsize(script) < 1000:
    print("[esta] tag", ref, "not found, falling back to main", flush=True)
    subprocess.run(["wget", "-q", "-O", script, base + "main" + tail_url], check=True)

cmd = [
    # Kaggle's "GPU T4 x2" makes accelerate spawn one process per card by
    # default, which for a single LoRA just duplicates the work and doubles host
    # RAM pressure for no gain. Pin it to one process on one GPU.
    "accelerate", "launch", "--num_processes", "1", "--num_machines", "1",
    "--mixed_precision", "fp16", script,
    "--pretrained_model_name_or_path", CFG["base_model"],
    # SDXL's own VAE overflows in fp16; this drop-in fix is the standard remedy.
    # It matters here because Kaggle's T4 (Turing) and P100 (Pascal) have no
    # native bf16, so fp16 is the only mixed-precision option available.
    "--pretrained_vae_model_name_or_path", "madebyollin/sdxl-vae-fp16-fix",
    "--dataset_name", WORKDIR,
    "--caption_column", "text",
    "--instance_prompt", CFG["trigger"],
    "--output_dir", os.path.join(OUT, "lora"),
    "--mixed_precision", "fp16",
    "--resolution", str(CFG["resolution"]),
    "--train_batch_size", "1",
    "--gradient_accumulation_steps", str(CFG["grad_accum"]),
    "--gradient_checkpointing",          # trades speed for the VRAM headroom
    "--use_8bit_adam",                   # optimiser states are the other big cost
    "--learning_rate", str(CFG["lr"]),
    "--lr_scheduler", "constant",
    "--lr_warmup_steps", "0",
    "--max_train_steps", str(CFG["steps"]),
    "--rank", str(CFG["rank"]),
    "--checkpointing_steps", str(CFG["steps"] + 1),   # only the final weights
    "--seed", "0",
]
print("[esta] launching training:", " ".join(cmd[:6]), "...", flush=True)
proc = subprocess.run(cmd, capture_output=True, text=True)
tail = ((proc.stdout or "")[-3000:] + "\\n--- stderr ---\\n" + (proc.stderr or "")[-6000:])
print(tail, flush=True)

weights = glob.glob(os.path.join(OUT, "lora", "*.safetensors"))
if proc.returncode != 0 or not weights:
    finish(False, "training failed rc=" + str(proc.returncode) + " :: " + (proc.stderr or "")[-500:])
else:
    # Flatten to a predictable name at the root of /kaggle/working.
    dest = os.path.join(OUT, CFG["lora_name"])
    shutil.copy(sorted(weights)[0], dest)
    finish(True, {"file": CFG["lora_name"], "bytes": os.path.getsize(dest),
                  "images": n_imgs, "steps": CFG["steps"]})
'''


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    """ffmpeg via the esta conda env, with explicit utf-8 decoding.

    ffmpeg writes non-cp1252 bytes to stderr and the Windows locale codec raises
    on them — the same trap the genvideo seed extractor hit.
    """
    return subprocess.run(
        ["conda", "run", "--no-capture-output", "-n", "esta", "ffmpeg", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )


def cmd_contact(args: argparse.Namespace) -> None:
    """Build contact sheets of a run's images.

    This lives in the tool rather than being an ffmpeg incantation typed out each
    time because looking at the output IS the workflow — every run ends by
    showing the user a grid, so that has to be one command.
    """
    src = char_dir(args.name) / args.mode
    images = sorted(src.glob("*.png"))
    if not images:
        raise FileNotFoundError(f"no images in {src} — run `fetch` first")

    per_row = args.per_row
    rows = [images[i:i + per_row] for i in range(0, len(images), per_row)]
    out_dir = char_dir(args.name) / "contact"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for r, row in enumerate(rows):
        inputs, filters, labels = [], [], []
        for n, img in enumerate(row):
            inputs += ["-i", str(img)]
            filters.append(f"[{n}]scale={args.thumb}:-1[v{n}]")
            labels.append(f"[v{n}]")
        # A single image can't hstack, so pass it through untouched.
        chain = (";".join(filters) + ";" + "".join(labels) +
                 f"hstack=inputs={len(row)}") if len(row) > 1 else f"[0]scale={args.thumb}:-1"
        dest = out_dir / f"{args.mode}_row{r + 1}.png"
        res = _ffmpeg("-y", *inputs, "-filter_complex", chain, "-frames:v", "1", str(dest))
        if res.returncode == 0 and dest.exists():
            written.append({"file": str(dest),
                            "images": [p.stem for p in row]})
    print(json.dumps({"ok": True, "rows": len(written), "total_images": len(images),
                      "sheets": written}, ensure_ascii=False))


def cmd_cull(args: argparse.Namespace) -> None:
    """Record which candidates are on-model — the LoRA training set.

    Keeps are stored by key, not by moving files, so a cull is always reversible
    and re-cullable without regenerating anything.
    """
    data = load_char(args.name)
    src = char_dir(args.name) / "sheet"
    available = {p.stem for p in src.glob("*.png")}
    keep = [k.strip() for k in args.keep.replace(" ", ",").split(",") if k.strip()]

    # Accept bare indices ("7") as well as full keys ("c007-smile").
    resolved, missing = [], []
    by_index = {p.stem.split("-")[0].lstrip("c").lstrip("0") or "0": p.stem
                for p in src.glob("*.png")}
    for k in keep:
        if k in available:
            resolved.append(k)
        elif k.lstrip("0") in by_index:
            resolved.append(by_index[k.lstrip("0")])
        else:
            missing.append(k)
    if missing:
        raise ValueError(f"unknown candidates: {', '.join(missing)}")

    data["lora_set"] = sorted(set(resolved))
    data["stage"] = "culled"
    save_char(args.name, data)
    print(json.dumps({"ok": True, "name": args.name, "kept": len(data["lora_set"]),
                      "of": len(available), "set": data["lora_set"]}, ensure_ascii=False))


# Scenes deliberately absent from the training set. A LoRA that only reproduces
# its training images is worthless; the test is whether the character survives
# into situations it has never been drawn in.
TEST_SCENES = [
    ("cafe", "sitting in a cosy cafe, drinking coffee, warm afternoon light, window behind"),
    ("rain", "standing in heavy rain at night, city street, neon reflections on wet ground"),
    ("snow", "walking through a snowy pine forest, breath visible in cold air"),
    ("rooftop", "sitting on a rooftop at sunset, city skyline behind, legs dangling"),
    ("library", "reading a book in an old library, tall shelves, dusty sunbeams"),
    ("beach", "standing on a beach at sunset, waves at her feet, wind in hair"),
    ("battle", "mid-battle, sword raised, sparks and embers flying, dramatic lighting"),
    ("portrait", "close-up portrait, soft studio lighting, plain grey background"),
]


def cmd_render(args: argparse.Namespace) -> None:
    """Generate the character in new scenes using its trained LoRA.

    This is both the consistency test and, once trusted, the keyframe generator:
    the same call with per-shot prompts is how a plan's shots get their art.
    """
    data = load_char(args.name)
    slug = slugify(args.name)
    # `fetch --mode lora` lands the weights under lora/, but accept the character
    # root too so a hand-dropped LoRA works without moving files around.
    candidates = [char_dir(args.name) / "lora" / f"{slug}.safetensors",
                  char_dir(args.name) / f"{slug}.safetensors",
                  *sorted((char_dir(args.name) / "lora").rglob("*.safetensors"))]
    lora_path = next((p for p in candidates if p.exists()), None)
    if lora_path is None:
        raise FileNotFoundError(
            f"no trained LoRA under {char_dir(args.name)} — run `train` first")
    trigger = data.get("trigger") or f"esta{slug.replace('-', '')}"

    scenes = ([(f"s{i:02d}", p) for i, p in enumerate(
        [s.strip() for s in args.prompts.split("|") if s.strip()])]
        if args.prompts else TEST_SCENES)

    model = dict(MODELS[data.get("model", DEFAULT_MODEL)])
    # Datasets and notebooks share one namespace per user, so this must not
    # collide with the training kernel's own slug (esta-char-<name>-lora) —
    # Kaggle rejects the create with "already in use by a notebook".
    lora_slug = slugify(args.name, "loradata", prefix="esta-char-")
    model["lora_slug"] = lora_slug
    model["lora_scale"] = args.lora_scale

    jobs = [{"key": f"r{i:02d}-{name}",
             "prompt": f"{QUALITY_TAGS}, {trigger}, {data['desc']}, {scene}",
             "seed": args.seed + i * 7919, "label": name}
            for i, (name, scene) in enumerate(scenes)]

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "count": len(jobs),
                          "trigger": trigger, "lora": str(lora_path),
                          "sample": jobs[0]["prompt"]}, ensure_ascii=False))
        return

    # Ship the LoRA as its own dataset — 90 MB is far past what a notebook holds.
    stage = char_dir(args.name) / "_lora_dataset"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy(lora_path, stage / lora_path.name)
    lora_dataset = f"{kaggle_username()}/{lora_slug}"
    ds_ok, ds_log = ensure_dataset(stage, lora_dataset, f"ESTA character LoRA — {args.name}")
    if not ds_ok:
        raise RuntimeError(f"lora dataset upload failed: {ds_log}")
    if not wait_dataset_ready(lora_dataset):
        raise RuntimeError(f"lora dataset {lora_dataset} never became ready")

    code = notebook_code(NOTEBOOK, env=ENV_PREAMBLE, jobs=repr(json.dumps(jobs)),
                         model=repr(json.dumps(model)), neg=repr(NEGATIVE))
    kernel_id = f"{kaggle_username()}/{slugify(args.name, 'render', prefix='esta-char-')}"
    build_dir = char_dir(args.name) / "_kernel_render"
    write_kernel_dir(build_dir, code, kernel_id,
                     ACCELERATORS.get(args.accelerator, "NvidiaTeslaT4"))
    meta_path = build_dir / "kernel-metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["dataset_sources"] = [lora_dataset]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    ok, log = push_kernel(build_dir)
    if ok:
        data["render_kernel"] = kernel_id
        save_char(args.name, data)
    print(json.dumps({"ok": ok, "kernel": kernel_id, "count": len(jobs),
                      "lora_dataset": lora_dataset, "trigger": trigger,
                      "url": f"https://www.kaggle.com/code/{kernel_id}",
                      "log": log[-250:]}, ensure_ascii=False))


ANIMATE_NOTEBOOK = '''# ESTA - animate character stills (image-to-video) on Kaggle's free GPU.
__ENV__
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "imageio[ffmpeg]"], check=False)

import torch, diffusers, base64, io
from diffusers.utils import export_to_video
from PIL import Image

JOBS  = json.loads(__JOBS__)
MODEL = json.loads(__MODEL__)
NEG   = __NEG__
OUT   = "/kaggle/working"

def finish(results, errors):
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump({"results": results, "errors": errors}, fh)

if not torch.cuda.is_available():
    finish({}, {"_": "no GPU"}); raise SystemExit
print("[esta] GPU:", torch.cuda.get_device_name(0), flush=True)

cls = getattr(diffusers, MODEL["pipeline"])
pipe = cls.from_pretrained(MODEL["repo"], torch_dtype=getattr(torch, MODEL["dtype"]))
# The video model is far larger than SDXL, so offload rather than keeping it
# resident — same trade the genvideo lane makes on this GPU.
pipe.enable_sequential_cpu_offload()
try:
    pipe.vae.enable_tiling(); pipe.vae.enable_slicing()
except Exception:
    pass
pipe.set_progress_bar_config(disable=True)

results, errors = {}, {}
for job in JOBS:
    key = job["key"]
    try:
        img = Image.open(io.BytesIO(base64.b64decode(job["image_b64"]))).convert("RGB")
        frames = pipe(image=img, prompt=job["prompt"], negative_prompt=NEG,
                      num_frames=MODEL["frames"], width=MODEL["width"],
                      height=MODEL["height"], num_inference_steps=MODEL["steps"],
                      guidance_scale=MODEL["guidance"]).frames[0]
        path = os.path.join(OUT, key + ".mp4")
        export_to_video(frames, path, fps=MODEL["fps"])
        results[key] = {"file": key + ".mp4", "frames": len(frames), "fps": MODEL["fps"]}
        print("OK", key, len(frames), "frames", flush=True)
    except Exception as e:
        errors[key] = (str(e) or repr(e))[:250]
        traceback.print_exc(); print("ERR", key, errors[key], flush=True)
    gc.collect(); torch.cuda.empty_cache()
    finish(results, errors)
'''

# Image-to-video model for character stills. Same LTX config the genvideo lane
# proved on this hardware — see tools/genvideo/run.py's MODELS registry.
ANIMATE_MODEL = {
    "repo": "Lightricks/LTX-Video",
    "pipeline": "LTXImageToVideoPipeline",
    "dtype": "float16",
    "frames": 121, "fps": 24, "width": 704, "height": 480,
    "steps": 40, "guidance": 3.0,
}

# Motion that suits a character portrait: gentle enough that the face survives.
# Big camera moves and full-body action are what drift fastest.
ANIMATE_MOTION = ("subtle natural motion, hair and clothing shifting gently, "
                  "slow breathing, eyes blinking, the camera drifts almost imperceptibly")


def cmd_animate(args: argparse.Namespace) -> None:
    """Turn rendered character stills into short video clips.

    This is the bridge between the character lane and the video lane: the stills
    already carry the character (via its LoRA), so image-to-video only has to add
    movement rather than invent a subject.
    """
    import base64
    data = load_char(args.name)
    src = char_dir(args.name) / args.mode
    images = sorted(src.glob("*.png"))
    if args.images:
        wanted = {w.strip() for w in args.images.split(",") if w.strip()}
        images = [p for p in images if p.stem in wanted or p.stem.split("-")[0] in wanted]
    images = images[:args.limit]
    if not images:
        raise FileNotFoundError(f"no images in {src} — run `render` first")

    model = dict(ANIMATE_MODEL)
    jobs = []
    for img in images:
        # Scale to the model's exact size before embedding: the pipeline would
        # resize anyway and this keeps the notebook small enough to push.
        tmp = src / f"_anim_{img.stem}.jpg"
        _ffmpeg("-y", "-i", str(img), "-vf",
                f"scale={model['width']}:{model['height']}:force_original_aspect_ratio=increase,"
                f"crop={model['width']}:{model['height']}", "-q:v", "4", str(tmp))
        if not tmp.exists():
            continue
        jobs.append({"key": f"a-{img.stem}", "prompt": f"{data['desc']}, {ANIMATE_MOTION}",
                     "image_b64": base64.b64encode(tmp.read_bytes()).decode("ascii")})
        tmp.unlink()
    if not jobs:
        raise RuntimeError("could not prepare any frames")

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "clips": len(jobs),
                          "sources": [j["key"] for j in jobs]}, ensure_ascii=False))
        return

    code = notebook_code(ANIMATE_NOTEBOOK, env=ENV_PREAMBLE,
                         jobs=repr(json.dumps(jobs)), model=repr(json.dumps(model)),
                         neg=repr("blurry, distorted face, warping, flickering, morphing"))
    kernel_id = f"{kaggle_username()}/{slugify(args.name, 'anim', prefix='esta-char-')}"
    build_dir = char_dir(args.name) / "_kernel_anim"
    write_kernel_dir(build_dir, code, kernel_id,
                     ACCELERATORS.get(args.accelerator, "NvidiaTeslaT4"))
    size = (build_dir / "kernel.ipynb").stat().st_size
    ok, log = push_kernel(build_dir)
    if ok:
        data["anim_kernel"] = kernel_id
        save_char(args.name, data)
    print(json.dumps({"ok": ok, "kernel": kernel_id, "clips": len(jobs),
                      "notebook_bytes": size, "log": log[-200:]}, ensure_ascii=False))


def _view_caption(stem: str) -> str:
    """Recover the view label from a candidate key like 'c007-smile'."""
    parts = stem.split("-", 1)
    return parts[1].replace("-", " ") if len(parts) > 1 else ""


def cmd_train(args: argparse.Namespace) -> None:
    """Train a character LoRA from the culled set (or everything, if not culled).

    Captions matter more than they look: each image is labelled `<trigger>, <view>`
    so the LoRA learns the *character* as the trigger and treats pose/expression
    as separable. Train on a bare trigger alone and the model fuses the character
    with whatever framing dominated the training set.
    """
    data = load_char(args.name)
    src = char_dir(args.name) / "sheet"
    keep = data.get("lora_set") or []
    images = ([src / f"{k}.png" for k in keep] if keep
              else sorted(src.glob("*.png")))
    images = [p for p in images if p.exists()]
    if len(images) < 5:
        raise ValueError(f"only {len(images)} training images — generate a pool with "
                         f"`sheet` first (15-25 on-model images is the useful range)")

    slug = slugify(args.name)
    trigger = args.trigger or f"esta{slug.replace('-', '')}"

    # Stage images + an imagefolder metadata.jsonl (the caption source).
    stage = char_dir(args.name) / "_dataset"
    if stage.exists():
        for old in stage.iterdir():
            old.unlink()
    stage.mkdir(parents=True, exist_ok=True)
    lines = []
    for img in images:
        shutil.copy(img, stage / img.name)
        view = _view_caption(img.stem)
        lines.append({"file_name": img.name,
                      "text": f"{trigger}, {data['desc']}" + (f", {view}" if view else "")})
    (stage / "metadata.jsonl").write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8")

    dataset_slug = slugify(args.name, "imgs", prefix="esta-char-")
    dataset_id = f"{kaggle_username()}/{dataset_slug}"
    cfg = {
        "dataset_slug": dataset_slug,
        "base_model": MODELS[data.get("model", DEFAULT_MODEL)]["repo"],
        "trigger": trigger,
        "lora_name": f"{slug}.safetensors",
        "resolution": args.resolution,
        "steps": args.steps,
        "rank": args.rank,
        "lr": args.lr,
        "grad_accum": args.grad_accum,
        "diffusers_ref": args.diffusers_ref,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "images": len(images),
                          "trigger": trigger, "dataset": dataset_id,
                          "sample_caption": lines[0]["text"], "config": cfg},
                         ensure_ascii=False))
        return

    ds_ok, ds_log = ensure_dataset(stage, dataset_id, f"ESTA character images — {args.name}")
    if not ds_ok:
        raise RuntimeError(f"dataset upload failed: {ds_log}")
    # Must be processed before the kernel push, or Kaggle drops the source with
    # only a warning and the run starts with no images.
    if not wait_dataset_ready(dataset_id):
        raise RuntimeError(f"dataset {dataset_id} never became ready — retry `train`")

    code = notebook_code(TRAIN_NOTEBOOK, env=ENV_PREAMBLE, cfg=repr(json.dumps(cfg)))
    kernel_id = f"{kaggle_username()}/{slugify(args.name, 'lora', prefix='esta-char-')}"
    build_dir = char_dir(args.name) / "_kernel_lora"
    write_kernel_dir(build_dir, code, kernel_id,
                     ACCELERATORS.get(args.accelerator, "NvidiaTeslaT4"))
    # The kernel needs the images mounted, which is what dataset_sources does.
    meta_path = build_dir / "kernel-metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["dataset_sources"] = [dataset_id]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    ok, log = push_kernel(build_dir)
    if ok:
        data.update({"stage": "training", "lora_kernel": kernel_id,
                     "trigger": trigger, "lora_dataset": dataset_id})
        save_char(args.name, data)
    print(json.dumps({"ok": ok, "kernel": kernel_id, "dataset": dataset_id,
                      "images": len(images), "trigger": trigger,
                      "url": f"https://www.kaggle.com/code/{kernel_id}",
                      "log": log[-300:]}, ensure_ascii=False))


def cmd_status(args: argparse.Namespace) -> None:
    data = load_char(args.name)
    ref = args.kernel or data.get(
        {"sheet": "sheet_kernel", "lora": "lora_kernel",
         "render": "render_kernel", "anim": "anim_kernel"}.get(args.mode, "kernel"), "")
    if not ref:
        raise ValueError("no kernel recorded for that mode yet")
    state, raw = kernel_status(ref)
    print(json.dumps({"ok": True, "kernel": ref, "state": state, "raw": raw},
                     ensure_ascii=False))


def cmd_fetch(args: argparse.Namespace) -> None:
    """Download a finished run's images into characters/<name>/<mode>/."""
    data = load_char(args.name)
    ref = args.kernel or data.get(
        {"sheet": "sheet_kernel", "lora": "lora_kernel",
         "render": "render_kernel", "anim": "anim_kernel"}.get(args.mode, "kernel"), "")
    if not ref:
        raise ValueError("no kernel recorded for that mode yet")
    out_dir = char_dir(args.name) / args.mode
    fetch_output(ref, out_dir)
    images = sorted(p.name for p in out_dir.glob("*.png"))
    results_path = out_dir / "results.json"
    errors = {}
    if results_path.exists():
        errors = json.loads(results_path.read_text(encoding="utf-8")).get("errors", {})
    print(json.dumps({"ok": True, "kernel": ref, "dir": str(out_dir),
                      "images": images, "count": len(images), "errors": errors},
                     ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA original-character design on Kaggle")
    sub = parser.add_subparsers(dest="mode_cmd", required=True)

    e = sub.add_parser("explore", help="Generate N variations of a character description")
    e.add_argument("--name", required=True, help="Character name (becomes characters/<slug>/)")
    e.add_argument("--desc", required=True, help="What the character looks like")
    e.add_argument("--count", type=int, default=8)
    e.add_argument("--seed", type=int, default=1000)
    e.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))
    e.add_argument("--accelerator", default="t4", choices=list(ACCELERATORS))
    e.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("pick", help="Record which variation to build the model sheet from")
    p.add_argument("--name", required=True)
    p.add_argument("--variation", required=True, help="e.g. v03")

    s = sub.add_parser("sheet", help="Generate a candidate pool to cull into a LoRA set")
    s.add_argument("--name", required=True)
    s.add_argument("--count", type=int, default=40,
                   help="How many varied candidates to generate")
    s.add_argument("--accelerator", default="t4", choices=list(ACCELERATORS))
    s.add_argument("--dry-run", action="store_true")

    st = sub.add_parser("status", help="Poll a run")
    st.add_argument("--name", required=True)
    st.add_argument("--mode", default="explore", choices=["explore", "sheet", "lora", "render", "anim"])
    st.add_argument("--kernel", default="")

    f = sub.add_parser("fetch", help="Download a finished run's images")
    f.add_argument("--name", required=True)
    f.add_argument("--mode", default="explore", choices=["explore", "sheet", "lora", "render", "anim"])
    f.add_argument("--kernel", default="")

    c = sub.add_parser("contact", help="Build contact sheets of a run's images")
    c.add_argument("--name", required=True)
    c.add_argument("--mode", default="sheet", choices=["explore", "sheet", "render"])
    c.add_argument("--per-row", type=int, default=8)
    c.add_argument("--thumb", type=int, default=220)

    k = sub.add_parser("cull", help="Record which candidates are on-model")
    k.add_argument("--name", required=True)
    k.add_argument("--keep", required=True,
                   help="Comma-separated keys or indices, e.g. 'c003-front,7,12'")

    t = sub.add_parser("train", help="Train the character LoRA from the culled set")
    t.add_argument("--name", required=True)
    t.add_argument("--trigger", default="", help="Token that summons the character")
    t.add_argument("--steps", type=int, default=1200)
    t.add_argument("--rank", type=int, default=16)
    t.add_argument("--lr", type=float, default=1e-4)
    t.add_argument("--resolution", type=int, default=768,
                   help="768 is the safe T4 default; 1024 is native SDXL but tight on 16 GB")
    t.add_argument("--grad-accum", type=int, default=4)
    t.add_argument("--diffusers-ref", default="auto",
                   help="'auto' pins the training script to the installed diffusers tag")
    t.add_argument("--accelerator", default="t4", choices=list(ACCELERATORS))
    t.add_argument("--dry-run", action="store_true")

    r = sub.add_parser("render", help="Generate the character in new scenes with its LoRA")
    r.add_argument("--name", required=True)
    r.add_argument("--prompts", default="",
                   help="Pipe-separated scenes; default is a fixed unseen-scene test set")
    r.add_argument("--lora-scale", type=float, default=0.9)
    r.add_argument("--seed", type=int, default=777)
    r.add_argument("--accelerator", default="t4", choices=list(ACCELERATORS))
    r.add_argument("--dry-run", action="store_true")

    an = sub.add_parser("animate", help="Turn rendered character stills into video clips")
    an.add_argument("--name", required=True)
    an.add_argument("--mode", default="render", choices=["render", "sheet", "explore"],
                    help="Which image set to animate")
    an.add_argument("--images", default="", help="Specific image stems, comma separated")
    an.add_argument("--limit", type=int, default=3,
                    help="Clips per run — each is ~7 min of GPU, so keep it small")
    an.add_argument("--accelerator", default="t4", choices=list(ACCELERATORS))
    an.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    try:
        {"explore": cmd_explore, "train": cmd_train, "render": cmd_render,
         "animate": cmd_animate, "pick": cmd_pick, "sheet": cmd_sheet,
         "status": cmd_status, "fetch": cmd_fetch,
         "contact": cmd_contact, "cull": cmd_cull}[args.mode_cmd](args)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
