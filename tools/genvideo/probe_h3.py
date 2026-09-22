"""Feasibility probe for the MiniMax H3 lane on Kaggle.

Why this exists as a separate script: H3 has no usable diffusers path (the
quantized formats that make it fit a 16 GB card are ComfyUI-only), so this lane
can't be a registry edit the way `hunyuan` was. It needs ComfyUI running headless
inside the kernel, driven by an API-format workflow — and writing that workflow
blind is guesswork. So we probe first.

Two steps, deliberately:

  step1 — CPU kernel, zero GPU quota. Installs ComfyUI + ComfyUI-GGUF, starts the
          server with no models at all, and dumps (a) the node schemas for every
          H3/GGUF-related node and (b) any H3 workflow template ComfyUI ships.
          That is everything needed to author a correct API graph.

  step2 — GPU kernel. Downloads the GGUF stack and actually generates a clip.
          Written once step1 tells us what the graph looks like.

Kept out of run.py because that file's contract is "a model is a registry entry";
H3 breaks that contract and pretending otherwise would rot the abstraction.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    fetch_output, kaggle_username, kernel_status, push_kernel, slugify,
    use_utf8_stdout,
)

use_utf8_stdout()

HERE = Path(__file__).resolve().parent
BUILD = HERE / "_h3_probe"

# The stack that actually fits 16 GB VRAM + 32 GB host RAM, chosen from the
# published blob sizes. Pruned + Q4 denoiser and a Q2 text encoder because the
# encoder is Qwen3-VL *32B* — at int8 it is 27 GB and alone eats the kernel.
STACK = {
    "unet": ("unsloth/MiniMax-H3-GGUF", "minimax_h3_fl2va_pruned-Q4_K.gguf", 11.4),
    "text_encoder": ("unsloth/MiniMax-H3-GGUF", "qwen3vl_32b_minimax_h3-Q2_K_M.gguf", 13.1),
    "vae": ("Comfy-Org/MiniMax-H3", "vae/minimax_h3_video_vae_fp16.safetensors", 5.2),
    "audio_vae": ("Comfy-Org/MiniMax-H3", "vae/minimax_h3_audio_vae_fp32.safetensors", 0.6),
    "lora": ("lightx2v/Minimax-h3-Turbo",
             "minimax_h3_fl2v_turbo_4step_v1.1_768p_comfyui_bf16.safetensors", 2.0),
}


STEP1_CODE = r'''# ESTA - H3 feasibility probe, step 1 (CPU kernel, no GPU quota burned).
# Goal: learn the exact ComfyUI node graph H3 needs. Downloads no model weights.
import subprocess, sys, os, json, time, glob, shutil, traceback

OUT = "/kaggle/working"
ROOT = "/kaggle/temp/ComfyUI"
os.makedirs("/kaggle/temp", exist_ok=True)

report = {"ok": False, "steps": []}
def note(k, v):
    report["steps"].append({k: v}); print(f"[esta] {k}: {v}", flush=True)

def finish():
    with open(os.path.join(OUT, "probe_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print("ESTA_PROBE_RESULT::" + json.dumps(report)[:2000], flush=True)

try:
    import psutil
    note("host_ram_gb", round(psutil.virtual_memory().total / 1e9, 1))
    note("disk_free_gb", round(shutil.disk_usage("/kaggle/temp").free / 1e9, 1))

    subprocess.run(["git", "clone", "--depth", "1",
                    "https://github.com/comfyanonymous/ComfyUI", ROOT], check=True)
    ver = subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%H %cd"],
                         capture_output=True, text=True).stdout.strip()
    note("comfyui_commit", ver)

    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    os.path.join(ROOT, "requirements.txt")], check=False)
    subprocess.run(["git", "clone", "--depth", "1",
                    "https://github.com/city96/ComfyUI-GGUF",
                    os.path.join(ROOT, "custom_nodes", "ComfyUI-GGUF")], check=False)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gguf"], check=False)

    # Ship every H3 workflow template ComfyUI bundles - converting one of these
    # beats authoring a graph from scratch.
    tpl_hits = []
    try:
        import comfyui_workflow_templates as T
        tdir = os.path.join(os.path.dirname(T.__file__), "templates")
        for pat in ("*h3*", "*H3*", "*minimax*", "*MiniMax*"):
            tpl_hits += glob.glob(os.path.join(tdir, pat))
        os.makedirs(os.path.join(OUT, "templates"), exist_ok=True)
        for f in set(tpl_hits):
            if f.endswith(".json"):
                shutil.copy(f, os.path.join(OUT, "templates", os.path.basename(f)))
        note("templates_found", [os.path.basename(f) for f in set(tpl_hits)][:40])
    except Exception as e:
        note("templates_error", str(e)[:200])

    # Start headless on CPU with no models present; /object_info still enumerates
    # every node class and its exact input names, which is the whole point.
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "main.py"), "--cpu", "--port", "8188",
         "--disable-auto-launch"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    import urllib.request
    info = None
    for i in range(90):
        time.sleep(2)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=10) as r:
                info = json.loads(r.read().decode("utf-8"))
            break
        except Exception:
            if proc.poll() is not None:
                note("server_died_after_s", i * 2)
                break
    if info is None:
        out = ""
        try:
            proc.kill(); out = (proc.stdout.read() or "")[-3000:]
        except Exception:
            pass
        note("server_log_tail", out)
        raise RuntimeError("ComfyUI never answered /object_info")

    note("node_class_count", len(info))
    keys = [k for k in info
            if any(s in k.lower() for s in ("minimax", "h3", "gguf", "unetloader",
                                            "cliploader", "vaeloader", "loraloader"))]
    note("relevant_nodes", keys[:60])
    with open(os.path.join(OUT, "object_info_h3.json"), "w") as fh:
        json.dump({k: info[k] for k in keys}, fh, indent=2)
    # Full dump too - cheap, and saves a second round trip if I guessed the filter wrong.
    with open(os.path.join(OUT, "object_info_all_keys.json"), "w") as fh:
        json.dump(sorted(info.keys()), fh, indent=2)

    report["ok"] = True
    try:
        proc.kill()
    except Exception:
        pass
except Exception as e:
    note("fatal", str(e)[:300])
    traceback.print_exc()
finish()
'''


STEP2_CODE = '''# ESTA - H3 feasibility probe, step 2 (GPU kernel). Downloads the GGUF stack and
# generates one clip, instrumented. Writes h3_probe.json + the mp4 to /kaggle/working.
import subprocess, sys, os, json, time, shutil, traceback, urllib.request, urllib.error

OUT = "/kaggle/working"
ROOT = "/kaggle/temp/ComfyUI"
os.makedirs("/kaggle/temp", exist_ok=True)
os.environ["HF_HOME"] = "/kaggle/temp/hf"

WIDTH, HEIGHT, LENGTH, STEPS = __WH__
PROMPT = __PROMPT__

report = {"ok": False, "phases": {}, "notes": []}
t0 = time.time()
# Hard wall for the whole kernel. Kaggle's own cap is 12 h and it bills every one
# of those hours against a 30 h/week quota, so an unattended hang is expensive.
# Nothing here should ever take this long; if it does, we want the report, not the wait.
DEADLINE_S = __DEADLINE__

def check_deadline(where):
    if time.time() - t0 > DEADLINE_S:
        raise TimeoutError(f"global deadline {DEADLINE_S}s exceeded at {where}")

def note(k, v):
    report["notes"].append({k: v}); print(f"[esta] {k}: {v}", flush=True)

def phase(name, start):
    dt = round(time.time() - start, 1)
    report["phases"][name] = dt
    print(f"[esta] PHASE {name}: {dt}s", flush=True)
    return time.time()

def finish():
    report["total_s"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT, "h3_probe.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print("ESTA_PROBE_RESULT::" + json.dumps(report)[:3000], flush=True)

try:
    import torch, psutil
    note("gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE")
    note("vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
         if torch.cuda.is_available() else 0)
    note("host_ram_gb", round(psutil.virtual_memory().total / 1e9, 1))
    if not torch.cuda.is_available():
        raise RuntimeError("no GPU on this kernel")

    t = time.time()
    subprocess.run(["git", "clone", "--depth", "1",
                    "https://github.com/comfyanonymous/ComfyUI", ROOT], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    os.path.join(ROOT, "requirements.txt")], check=False)
    subprocess.run(["git", "clone", "--depth", "1",
                    "https://github.com/city96/ComfyUI-GGUF",
                    os.path.join(ROOT, "custom_nodes", "ComfyUI-GGUF")], check=False)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gguf"], check=False)
    t = phase("install", t)

    # --- weights -------------------------------------------------------------
    # The whole feasibility question in one place: these are the smallest quants
    # that keep the 32B text encoder and the denoiser inside 16 GB VRAM / 32 GB RAM.
    # Auth comes from a Kaggle Secret, never from the notebook source - the source
    # is uploaded to Kaggle and stored there, so a pasted token would leak.
    # Absent secret is fine; it just means the throttled anonymous path.
    try:
        from kaggle_secrets import UserSecretsClient
        _tok = UserSecretsClient().get_secret("HF_TOKEN")
        if _tok:
            os.environ["HF_TOKEN"] = _tok
            os.environ["HUGGING_FACE_HUB_TOKEN"] = _tok
            note("hf_auth", "authenticated via kaggle secret")
        else:
            note("hf_auth", "secret empty - anonymous")
    except Exception as e:
        note("hf_auth", f"no kaggle secret ({str(e)[:80]}) - anonymous")

    from huggingface_hub import hf_hub_download
    WANT = [tuple(x) for x in json.loads(__WANT__)]
    local = {}
    DL_TIMEOUT_S = 1200
    for repo, fname, kind in WANT:
        check_deadline("download")
        dest_dir = os.path.join(ROOT, "models", kind)
        os.makedirs(dest_dir, exist_ok=True)
        # Downloading in a child process is the only way to bound it: an
        # unauthenticated HF pull that gets rate-limited retries forever inside
        # hf_hub_download, and that is exactly what ate a 12 h kernel once.
        dl_start = time.time()
        code = ("from huggingface_hub import hf_hub_download;"
                f"print(hf_hub_download(repo_id={repo!r}, filename={fname!r}))")
        try:
            r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True, timeout=DL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            note("download_timeout", f"{repo}/{fname} exceeded {DL_TIMEOUT_S}s")
            raise TimeoutError(f"download stalled: {fname}")
        if r.returncode != 0:
            note("download_failed", f"{repo}/{fname}: {(r.stderr or '')[-400:]}")
            raise RuntimeError(f"download failed: {fname}")
        p = (r.stdout or "").strip().splitlines()[-1]
        note("download_seconds", f"{os.path.basename(fname)} {round(time.time()-dl_start,1)}s")
        base = os.path.basename(fname)
        link = os.path.join(dest_dir, base)
        if not os.path.exists(link):
            os.symlink(p, link)
        local[kind] = base
        note("downloaded", f"{base} {round(os.path.getsize(p)/1e9,2)}GB")
    t = phase("download", t)

    # --- server --------------------------------------------------------------
    # Tee to disk rather than a pipe nobody reads: ComfyUI's banner states which
    # device it selected, and its per-step output is the only progress signal.
    comfy_log = open(os.path.join(OUT, "comfyui.log"), "w", buffering=1)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "main.py"), "--port", "8188",
         "--disable-auto-launch"],
        cwd=ROOT, stdout=comfy_log, stderr=subprocess.STDOUT, text=True)

    def up():
        try:
            urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=5)
            return True
        except Exception:
            return False

    for i in range(120):
        if up():
            break
        if proc.poll() is not None:
            note("server_exit_code", proc.returncode)
            raise RuntimeError("ComfyUI died on startup")
        time.sleep(2)
    t = phase("server_start", t)

    # Ask the server what it is running on. This is the authoritative answer -
    # the parent process's torch handle says nothing about ComfyUI's choice.
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=15) as r:
            stats = json.loads(r.read().decode())
        devs = [{k: d.get(k) for k in ("name", "type", "vram_total", "vram_free")}
                for d in stats.get("devices", [])]
        note("comfy_devices", devs)
        report["comfy_on_cpu"] = all(
            str(d.get("type", "")).lower() == "cpu" for d in devs) if devs else None
    except Exception as e:
        note("system_stats_failed", str(e)[:200])

    # --- graph ---------------------------------------------------------------
    # Authored from the step-1 /object_info dump, not guessed. MiniMaxH3ImageToVideo
    # emits BOTH the positive conditioning and the AV latent, and doubles as the
    # t2v node when first_frame is omitted.
    G = {
        "1": {"class_type": ("UnetLoaderGGUF" if local["unet"].endswith(".gguf")
                             else "UNETLoader"),
              "inputs": ({"unet_name": local["unet"]} if local["unet"].endswith(".gguf")
                         else {"unet_name": local["unet"], "weight_dtype": "default"})},
        "2": {"class_type": "MiniMaxH3SigmaShift",
              "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "3": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["2", 0], "lora_name": local["loras"],
                         "strength_model": 1.0}},
        "4": {"class_type": ("CLIPLoaderGGUF" if local["clip"].endswith(".gguf")
                             else "CLIPLoader"),
              "inputs": {"clip_name": local["clip"], "type": "minimax"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": local["vae"]}},
        "6": {"class_type": "MiniMaxH3ImageToVideo",
              "inputs": {"clip": ["4", 0], "vae": ["5", 0], "prompt": PROMPT,
                         "width": WIDTH, "height": HEIGHT, "length": LENGTH}},
        "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["3", 0], "seed": 12345, "steps": STEPS, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["6", 1], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["5", 0]}},
        "10": {"class_type": "CreateVideo", "inputs": {"images": ["9", 0], "fps": 24}},
        "11": {"class_type": "SaveVideo",
               "inputs": {"video": ["10", 0], "filename_prefix": "h3_probe",
                          "format": "mp4", "codec": "h264"}},
    }
    with open(os.path.join(OUT, "graph_sent.json"), "w") as fh:
        json.dump(G, fh, indent=2)

    body = json.dumps({"prompt": G, "client_id": "esta"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:4000]
        note("prompt_rejected", detail)
        with open(os.path.join(OUT, "prompt_error.json"), "w") as fh:
            fh.write(detail)
        raise RuntimeError("ComfyUI rejected the graph - see prompt_error.json")
    pid = resp.get("prompt_id")
    note("prompt_id", pid)

    # --- wait ----------------------------------------------------------------
    hist, waited = None, 0
    while waited < 5400 and time.time() - t0 < DEADLINE_S:
        time.sleep(10); waited += 10
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:8188/history/{pid}", timeout=15) as r:
                h = json.loads(r.read().decode())
            if pid in h:
                hist = h[pid]
                break
        except Exception:
            pass
        if waited % 120 == 0:
            print(f"[esta] still sampling, {waited}s", flush=True)
    t = phase("generate", t)

    if hist is None:
        note("timeout", "no history after 90 min")
    else:
        status = (hist.get("status") or {})
        note("run_status", status.get("status_str"))
        if status.get("status_str") != "success":
            with open(os.path.join(OUT, "run_error.json"), "w") as fh:
                json.dump(hist, fh, indent=2)
            note("run_messages", json.dumps(status.get("messages", []))[:1500])

    for root, _, files in os.walk(os.path.join(ROOT, "output")):
        for f in files:
            if f.endswith((".mp4", ".webm", ".png")):
                shutil.copy(os.path.join(root, f), os.path.join(OUT, f))
                note("artifact", f"{f} {round(os.path.getsize(os.path.join(root,f))/1e6,2)}MB")
                report["ok"] = True

    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=15) as r:
            end_stats = json.loads(r.read().decode())
        note("devices_after_run", [
            {k: d.get(k) for k in ("name", "type", "vram_total", "vram_free")}
            for d in end_stats.get("devices", [])])
    except Exception as e:
        note("end_stats_failed", str(e)[:200])
    note("host_ram_used_gb", round(psutil.virtual_memory().used / 1e9, 2))
    try:
        comfy_log.flush()
        tail = open(os.path.join(OUT, "comfyui.log"), errors="replace").read()[-4000:]
        note("comfy_log_tail", tail[-1500:])
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
except Exception as e:
    note("fatal", str(e)[:400])
    traceback.print_exc()
finish()
'''


def write_probe_kernel(code: str, kernel_id: str, gpu: bool) -> Path:
    """Like kaggle_lane.write_kernel_dir but able to ask for a CPU-only kernel."""
    BUILD.mkdir(parents=True, exist_ok=True)
    slug = kernel_id.split("/", 1)[-1]
    nb = {
        "cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
                   "outputs": [], "source": code.splitlines(keepends=True)}],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10.0"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    nb_path = BUILD / "kernel.ipynb"
    nb_path.write_text(json.dumps(nb), encoding="utf-8")
    meta = {
        "id": kernel_id,
        "title": slug,                 # title *is* the slug - see kaggle_lane docstring
        "code_file": "kernel.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": "true",
        "enable_gpu": "true" if gpu else "false",
        "enable_internet": "true",
        "dataset_sources": [], "competition_sources": [], "kernel_sources": [],
    }
    if gpu:
        meta["machine_shape"] = "NvidiaTeslaT4"
    (BUILD / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return nb_path


def kernel_ref(which: str = "probe") -> str:
    name = "h3-probe" if which == "probe" else "h3-run"
    return f"{kaggle_username()}/{slugify(name, prefix='esta-')}"


def cmd_plan(_args) -> None:
    total = sum(v[2] for v in STACK.values())
    print(json.dumps({
        "stack": {k: {"repo": v[0], "file": v[1], "gb": v[2]} for k, v in STACK.items()},
        "download_gb": round(total, 1),
        "peak_resident_gb": round(
            max(STACK["text_encoder"][2],
                STACK["unet"][2] + STACK["vae"][2] + STACK["lora"][2]), 1),
        "kaggle_budget": {"vram_gb": 16, "host_ram_gb": 32},
    }, indent=2))


def cmd_step1(args) -> None:
    ref = kernel_ref()
    write_probe_kernel(STEP1_CODE, ref, gpu=False)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "kernel": ref,
                          "gpu": False, "bytes": (BUILD / "kernel.ipynb").stat().st_size}))
        return
    ok, log = push_kernel(BUILD)
    print(json.dumps({"ok": ok, "kernel": ref, "gpu": False,
                      "url": f"https://www.kaggle.com/code/{ref}", "log": log[-400:]}))


def cmd_step2(args) -> None:
    ref = kernel_ref("run")
    want = [
        [args.unet_repo, args.unet_file, "unet"],
        [args.clip_repo, args.clip_file, "clip"],
        ["Comfy-Org/MiniMax-H3", "vae/minimax_h3_video_vae_fp16.safetensors", "vae"],
        [args.lora_repo, args.lora_file, "loras"],
    ]
    code = (STEP2_CODE
            .replace("__WH__", repr((args.width, args.height, args.length, args.steps)))
            .replace("__WANT__", repr(json.dumps(want)))
            .replace("__DEADLINE__", str(args.deadline_min * 60))
            .replace("__PROMPT__", repr(args.prompt)))
    write_probe_kernel(code, ref, gpu=True)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "kernel": ref, "gpu": True,
                          "shape": [args.width, args.height, args.length, args.steps],
                          "bytes": (BUILD / "kernel.ipynb").stat().st_size}))
        return
    ok, log = push_kernel(BUILD)
    print(json.dumps({"ok": ok, "kernel": ref, "gpu": True,
                      "url": f"https://www.kaggle.com/code/{ref}", "log": log[-400:]}))


def cmd_status(_args) -> None:
    ref = kernel_ref(_args.which)
    state, raw = kernel_status(ref)
    print(json.dumps({"kernel": ref, "state": state, "raw": raw}))


def cmd_pull(args) -> None:
    ref = kernel_ref(args.which)
    out = Path(args.output_dir) if args.output_dir else BUILD / "out"
    out.mkdir(parents=True, exist_ok=True)
    fetch_output(ref, out)
    rep = out / ("probe_report.json" if args.which == "probe" else "h3_probe.json")
    print(json.dumps({"kernel": ref, "dir": str(out),
                      "report": json.loads(rep.read_text(encoding="utf-8"))
                      if rep.exists() else None}, indent=2)[:4000])


def main() -> None:
    p = argparse.ArgumentParser(description="MiniMax H3 Kaggle feasibility probe")
    sub = p.add_subparsers(dest="mode", required=True)
    sub.add_parser("plan", help="Print the model stack and memory budget, push nothing")
    s1 = sub.add_parser("step1", help="Push the CPU introspection kernel")
    s1.add_argument("--dry-run", action="store_true")
    s2 = sub.add_parser("step2", help="Push the GPU generation kernel")
    s2.add_argument("--dry-run", action="store_true")
    # Defaults are the ComfyUI-format quants. unsloth's are llama.cpp-format and
    # ComfyUI-GGUF rejects them outright - that cost us run 2.
    s2.add_argument("--unet-repo", default="Abiray/MiniMax-H3-Pruned-GGUF")
    s2.add_argument("--unet-file", default="MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf")
    s2.add_argument("--clip-repo", default="Abiray/MiniMax-H3-GGUF")
    s2.add_argument("--clip-file", default="text_encoders/qwen3vl_32b_minimax_h3-Q4_K_M.gguf")
    s2.add_argument("--lora-repo", default="lightx2v/Minimax-h3-Turbo")
    s2.add_argument("--lora-file",
                    default="minimax_h3_fl2v_turbo_4step_v1.1_768p_comfyui_bf16.safetensors")
    s2.add_argument("--deadline-min", type=int, default=50,
                    help="Hard wall for the whole kernel. Kaggle bills all 12h of a "
                         "hang against a 30h/week quota; this is the guard against that.")
    s2.add_argument("--width", type=int, default=640)
    s2.add_argument("--height", type=int, default=384)
    s2.add_argument("--length", type=int, default=124,
                    help="Frames at 24fps on the model's 17k+5 grid. 124 = ~5s.")
    s2.add_argument("--steps", type=int, default=4,
                    help="4 is what the turbo LoRA is distilled for.")
    s2.add_argument("--prompt", default=(
        "a slow cinematic push in on a trading desk at night, three monitors "
        "glowing with red and green candlestick charts, shallow depth of field, "
        "shot on film, natural light"))
    st = sub.add_parser("status", help="Poll a probe kernel")
    st.add_argument("--which", default="probe", choices=["probe", "run"])
    pl = sub.add_parser("pull", help="Download probe output")
    pl.add_argument("--output-dir", default="")
    pl.add_argument("--which", default="probe", choices=["probe", "run"])
    args = p.parse_args()
    try:
        {"plan": cmd_plan, "step1": cmd_step1, "step2": cmd_step2,
         "status": cmd_status, "pull": cmd_pull}[args.mode](args)
    except Exception as exc:  # noqa: BLE001 - CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
