"""Image-to-video bake-off on Kaggle's free T4: the same styled keyframes through several models, side by side.

    python tools/genvideo/bakeoff/run.py prep   --session sessions/<id>       # keyframes + prompts -> Kaggle dataset
    python tools/genvideo/bakeoff/run.py prep   --set real --spec spec.json   # any images: [{key, image, prompt, seconds}]
    (every command takes --set; each set has its own dataset, kernels and work/<set>/ folder)
    python tools/genvideo/bakeoff/run.py push   --model anisora|hunyuan|wan5b
    python tools/genvideo/bakeoff/run.py status --model ...
    python tools/genvideo/bakeoff/run.py fetch  --model ...
    python tools/genvideo/bakeoff/run.py page   --session sessions/<id>       # drift/darkness scores + side-by-side page

Experiment only: nothing in the pipeline reads this. System python (the Kaggle CLI lives there).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, ensure_dataset, fetch_output, kaggle_username, kernel_status, push_kernel, use_utf8_stdout,
    wait_dataset_ready, write_kernel_dir,
)

use_utf8_stdout()
HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
W, H = 832, 480
NEG = "blurry, distorted, morphing, melting, deformed, fade to black, black frame, static image, watermark, text"

COMMON = r'''
import os, sys, json, time, glob, gc, subprocess, traceback
# Reserved-but-fragmented memory (4.9 GB) is what made Hunyuan's 2.66 GB decode allocation fail; let segments grow.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers", "transformers", "accelerate",
                "gguf", "bitsandbytes", "imageio", "imageio-ffmpeg", "sentencepiece", "ftfy"], check=False)
import torch
from PIL import Image, ImageOps
from diffusers.utils import export_to_video
OUT = "/kaggle/working"
hits = glob.glob("/kaggle/input/**/inputs.json", recursive=True)
IN = os.path.dirname(hits[0])
INPUTS = json.load(open(os.path.join(IN, "inputs.json")))
W, H, NEG = __W__, __H__, __NEG__
print("[bo] GPU:", torch.cuda.get_device_name(0), "| shots:", [s["key"] for s in INPUTS], flush=True)
results = {"model": __MODEL__, "shots": {}, "errors": {}}
def finish():
    json.dump(results, open(os.path.join(OUT, "bo_results.json"), "w"), indent=1)
def image_for(s):
    return ImageOps.fit(Image.open(os.path.join(IN, s["image"])).convert("RGB"), (W, H))
def free():
    gc.collect(); torch.cuda.empty_cache()

# Wan's UMT5 prompt encoding (diffusers' _get_t5_prompt_embeds), run once per prompt before the
# transformer loads, so the 11 GB encoder and the denoisers are never resident together.
def wan_embeds(repo, texts):
    from transformers import AutoTokenizer, UMT5EncoderModel
    tok = AutoTokenizer.from_pretrained(repo, subfolder="tokenizer")
    out = None
    for dev, dt in (("cuda", torch.bfloat16), ("cpu", torch.float32)):
        try:
            te = UMT5EncoderModel.from_pretrained(repo, subfolder="text_encoder", torch_dtype=dt).to(dev)
            res = []
            for t in texts:
                ids = tok([t], padding="max_length", max_length=512, truncation=True, add_special_tokens=True,
                          return_attention_mask=True, return_tensors="pt")
                n = int(ids.attention_mask.sum())
                with torch.no_grad():
                    h = te(ids.input_ids.to(dev), ids.attention_mask.to(dev)).last_hidden_state[0, :n]
                h = torch.cat([h, h.new_zeros(512 - n, h.size(1))])[None].float().cpu()
                if not torch.isfinite(h).all():
                    raise ValueError("non-finite embeddings")
                res.append(h)
            out = res
            print("[bo] encoded on", dev, dt, flush=True)
        except Exception as e:
            print("[bo] encode on", dev, "failed:", str(e)[:200], flush=True)
        finally:
            te = None; free()
        if out is not None:
            return out
    raise RuntimeError("prompt encoding failed on cuda and cpu")

def run_all(gen):
    for s in INPUTS:
        k = s["key"]
        try:
            torch.cuda.reset_peak_memory_stats(); t0 = time.time()
            frames = gen(s)
            path = os.path.join(OUT, "bo_" + k + ".mp4")
            export_to_video(frames, path, fps=FPS)
            results["shots"][k] = {"file": os.path.basename(path), "frames": len(frames), "fps": FPS,
                                   "secs": round(time.time() - t0, 1),
                                   "peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)}
            print("[bo] OK", k, results["shots"][k], flush=True)
        except Exception as e:
            results["errors"][k] = (str(e) or repr(e))[:300]
            traceback.print_exc()
            print("[bo] ERR", k, results["errors"][k], flush=True)
        # A failed shot can leave a 9 GB transformer on the card; release every hook before the next one.
        if "pipe" in globals():
            pipe.maybe_free_model_hooks()
        free(); finish()
'''

# AniSora V3.2 (Wan2.2 I2V A14B: a high-noise and a low-noise expert), Q4 GGUF, 8-step distilled.
ANISORA = r'''
from huggingface_hub import hf_hub_download
from diffusers import WanImageToVideoPipeline, WanTransformer3DModel, GGUFQuantizationConfig, AutoencoderKLWan
BASE = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"
FPS, FRAMES = 16, 57
EMB = wan_embeds(BASE, [s["prompt"] for s in INPUTS])
q = GGUFQuantizationConfig(compute_dtype=torch.float16)
def gguf(fn, sub):
    p = hf_hub_download("youcef079/Index-Anisora-V3.2-GGUF", fn)
    return WanTransformer3DModel.from_single_file(p, quantization_config=q, config=BASE, subfolder=sub,
                                                  torch_dtype=torch.float16)
t1 = gguf("High/Index-Anisora-V3.2-High-Q4_0.gguf", "transformer")
t2 = gguf("Low/Index-Anisora-V3.2-Low-Q4_K_S.gguf", "transformer_2")
vae = AutoencoderKLWan.from_pretrained(BASE, subfolder="vae", torch_dtype=torch.float32)
pipe = WanImageToVideoPipeline.from_pretrained(BASE, transformer=t1, transformer_2=t2, vae=vae,
                                               text_encoder=None, torch_dtype=torch.float16)
pipe.enable_model_cpu_offload()
idx = {s["key"]: i for i, s in enumerate(INPUTS)}
def gen(s):
    e = EMB[idx[s["key"]]].to("cuda", torch.float16)
    return pipe(image=image_for(s), prompt_embeds=e, height=H, width=W, num_frames=FRAMES,
                num_inference_steps=8, guidance_scale=1.0, guidance_scale_2=1.0,
                generator=torch.Generator("cpu").manual_seed(42)).frames[0]
run_all(gen)
'''

# HunyuanVideo 1.5 480p I2V step-distilled. The 7B Qwen2.5-VL encoder loads quantized for encoding only:
# in fp16 it plus the transformer overran Kaggle's host RAM (ESTA genvideo runs, 2026-10-03).
HUNYUAN = r'''
from diffusers import HunyuanVideo15ImageToVideoPipeline, PipelineQuantizationConfig
REPO = "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v_step_distilled"
FPS, FRAMES = 24, 85
# 4-bit NF4 (~4.5 GB): the 8-bit attempt still filled the 14.56 GB card while encoding (first bake-off run).
qc = PipelineQuantizationConfig(quant_backend="bitsandbytes_4bit",
                                quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4",
                                              "bnb_4bit_compute_dtype": torch.float16},
                                components_to_quantize=["text_encoder"])
enc = HunyuanVideo15ImageToVideoPipeline.from_pretrained(REPO, transformer=None, torch_dtype=torch.float16,
                                                         quantization_config=qc)
print("[bo] encoder loaded, cuda GB:", round(torch.cuda.memory_allocated() / 1e9, 2), flush=True)
enc.text_encoder_2.to("cuda")
EMB = {}
for s in INPUTS:
    # no_grad: without it each prompt's whole activation graph stayed on the card and the second prompt OOMed.
    with torch.no_grad():
        out = enc.encode_prompt(s["prompt"], device="cuda")
    out = out if isinstance(out, (list, tuple)) else (out,)
    EMB[s["key"]] = [t.detach().cpu() if torch.is_tensor(t) else t for t in out]
    out = None; free()
    print("[bo] encoded", s["key"], [tuple(t.shape) for t in EMB[s["key"]] if torch.is_tensor(t)], flush=True)
del enc; free()
pipe = HunyuanVideo15ImageToVideoPipeline.from_pretrained(REPO, text_encoder=None, text_encoder_2=None,
                                                          torch_dtype=torch.float16)
# SigLIP's MultiheadAttention reads its weights directly, so sequential offload leaves them on the meta device
# ("Tensor on device meta", third bake-off run). It is small: keep it out of the offload, resident on the card.
ie = pipe.image_encoder
pipe.image_encoder = None
pipe.enable_sequential_cpu_offload()
pipe.image_encoder = ie.to("cuda", torch.float16)
# Tiles split the frame only, each still decoding every frame: 256 px tiles OOMed on the T4 at 85 frames.
pipe.vae.enable_tiling(tile_sample_min_height=128, tile_sample_min_width=128)
if getattr(pipe, "guider", None) is not None:
    pipe.guider = pipe.guider.new(enabled=False)
KEYS = ("prompt_embeds", "prompt_embeds_mask", "prompt_embeds_2", "prompt_embeds_mask_2")
def gen(s):
    kw = {k: (v.to("cuda") if torch.is_tensor(v) else v) for k, v in zip(KEYS, EMB[s["key"]])}
    return pipe(image=image_for(s), num_frames=FRAMES, num_inference_steps=8,
                generator=torch.Generator("cpu").manual_seed(42), **kw).frames[0]
run_all(gen)
'''

# Wan2.2 TI2V-5B: dense 5B, 30 steps with CFG.
WAN5B = r'''
from diffusers import WanImageToVideoPipeline, AutoencoderKLWan
REPO = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
FPS, FRAMES = 24, 85
EMB = wan_embeds(REPO, [s["prompt"] for s in INPUTS] + [NEG])
vae = AutoencoderKLWan.from_pretrained(REPO, subfolder="vae", torch_dtype=torch.float32)
pipe = WanImageToVideoPipeline.from_pretrained(REPO, vae=vae, text_encoder=None, torch_dtype=torch.float16)
pipe.enable_model_cpu_offload()
idx = {s["key"]: i for i, s in enumerate(INPUTS)}
def gen(s):
    return pipe(image=image_for(s), prompt_embeds=EMB[idx[s["key"]]].to("cuda", torch.float16),
                negative_prompt_embeds=EMB[-1].to("cuda", torch.float16), height=H, width=W, num_frames=FRAMES,
                num_inference_steps=30, guidance_scale=5.0,
                generator=torch.Generator("cpu").manual_seed(42)).frames[0]
run_all(gen)
'''

MODELS = {"anisora": ANISORA, "hunyuan": HUNYUAN, "wan5b": WAN5B}


SET = ""


def dataset_id() -> str:
    return f"{kaggle_username()}/esta-i2v-bakeoff-inputs" + (f"-{SET}" if SET else "")


def kernel_id(model: str) -> str:
    return f"{kaggle_username()}/esta-i2v-bakeoff-{model}" + (f"-{SET}" if SET else "")


def cmd_prep(a) -> None:
    build = WORK / "dataset"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    inputs = []
    if a.spec:
        for s in json.loads(Path(a.spec).read_text(encoding="utf-8")):
            src = Path(s["image"])
            name = f"in_{s['key']}{src.suffix.lower()}"
            shutil.copy(src, build / name)
            inputs.append({"key": str(s["key"]), "image": name, "prompt": s["prompt"], "seconds": float(s["seconds"])})
    else:
        from tools.genvideo.run import collect_slots, load_presets, MODELS as GEN_MODELS
        session = Path(a.session)
        slots = collect_slots(session, load_presets(), GEN_MODELS["ltx"], "push_in", "cinematic", None, 1)
        for s in slots:
            kf = session / "assets" / "gen_out" / f"kf_{s['key']}.png"
            if not kf.exists():
                continue
            shutil.copy(kf, build / kf.name)
            inputs.append({"key": s["key"], "image": kf.name, "prompt": s["prompt"], "seconds": s["duration"]})
    (build / "inputs.json").write_text(json.dumps(inputs, indent=1), encoding="utf-8")
    ok, log = ensure_dataset(build, dataset_id(), dataset_id().split("/", 1)[1])
    if not ok or not wait_dataset_ready(dataset_id(), timeout=1200):
        raise SystemExit(f"dataset upload failed: {log}")
    (WORK / "inputs.json").write_text(json.dumps(inputs, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "dataset": dataset_id(), "shots": [i["key"] for i in inputs]}))


def cmd_push(a) -> None:
    code = (COMMON.replace("__W__", str(W)).replace("__H__", str(H)).replace("__NEG__", repr(NEG))
            .replace("__MODEL__", repr(a.model)) + MODELS[a.model])
    kbuild = WORK / f"kernel_{a.model}"
    WORK.mkdir(parents=True, exist_ok=True)
    write_kernel_dir(kbuild, code, kernel_id(a.model), ACCELERATORS["t4"])
    meta = json.loads((kbuild / "kernel-metadata.json").read_text(encoding="utf-8"))
    meta["dataset_sources"] = [dataset_id()]
    (kbuild / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if a.dry_run:
        import ast
        ast.parse(code)
        print(json.dumps({"ok": True, "dry_run": True, "kernel": kernel_id(a.model), "bytes": len(code)}))
        return
    ok, log = push_kernel(kbuild)
    print(json.dumps({"ok": ok, "kernel": kernel_id(a.model), "log": log[-300:]}))


def cmd_status(a) -> None:
    state, raw = kernel_status(kernel_id(a.model))
    print(json.dumps({"model": a.model, "state": state, "raw": raw[-200:]}))


def cmd_fetch(a) -> None:
    out = WORK / f"out_{a.model}"
    fetch_output(kernel_id(a.model), out)
    res = json.loads((out / "bo_results.json").read_text(encoding="utf-8")) if (out / "bo_results.json").exists() else {}
    print(json.dumps({"model": a.model, "shots": res.get("shots", {}), "errors": res.get("errors", {})}))


def drift(path: Path, seconds: float) -> dict:
    """Mean pixel change from frame 0 and mean brightness, sampled every 0.25 s over the shot's own length."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(path))
    ok, f0 = cap.read()
    if not ok:
        return {}
    f0 = cv2.resize(f0, (W, H)).astype(np.float32)
    rows = []
    t = 0.25
    while t <= seconds + 1e-6:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        if not ok:
            break
        f = cv2.resize(f, (W, H)).astype(np.float32)
        rows.append((float(np.abs(f - f0).mean()), float(f.mean())))
        t += 0.25
    if not rows:
        return {}
    return {"max_drift": round(max(r[0] for r in rows), 1), "min_light": round(min(r[1] for r in rows), 1),
            "end_drift": round(rows[-1][0], 1)}


def cmd_page(a) -> None:
    import html
    session = Path(a.session).resolve() if a.session else None
    inputs = json.loads((WORK / "inputs.json").read_text(encoding="utf-8"))
    cols = [("ltx (current)", lambda k: session / "assets" / "source_pool" / f"gen_{k}.mp4")] if session else []
    for m in MODELS:
        cols.append((m, lambda k, m=m: WORK / f"out_{m}" / f"bo_{k}.mp4"))
    res = {m: (json.loads((WORK / f"out_{m}" / "bo_results.json").read_text(encoding="utf-8"))
               if (WORK / f"out_{m}" / "bo_results.json").exists() else {}) for m in MODELS}
    scores, rows = {}, []
    for s in inputs:
        k = s["key"]
        cells = [f"<td><img src='{(WORK / 'dataset' / s['image']).resolve().as_uri()}'><p class=m>shot {k} &middot; "
                 f"{s['seconds']}s<br>{html.escape(s['prompt'][:110])}</p></td>"]
        for name, f in cols:
            p = f(k)
            if p.exists():
                d = drift(p, float(s["seconds"]))
                scores.setdefault(name, []).append(d)
                info = res.get(name, {}).get("shots", {}).get(k, {})
                bad = d and (d["max_drift"] > 45 or d["min_light"] < 30)
                cells.append(f"<td><video src='{p.resolve().as_uri()}' autoplay loop muted playsinline></video>"
                             f"<p class='m{' bad' if bad else ''}'>drift {d.get('max_drift')} &middot; light {d.get('min_light')}"
                             + (f" &middot; {info.get('secs')}s, {info.get('peak_gb')} GB" if info else "") + "</p></td>")
            else:
                err = res.get(name, {}).get("errors", {}).get(k, "not run")
                cells.append(f"<td class=m>{html.escape(err[:160])}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    summary = "".join(f"<li><b>{n}</b>: {sum(1 for d in v if d and d['max_drift'] <= 45 and d['min_light'] >= 30)}/{len(inputs)} "
                      f"hold (drift &le; 45, never dark)</li>" for n, v in scores.items())
    head = "".join(f"<th>{html.escape(n)}</th>" for n, _ in cols)
    page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>I2V Bake-off</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--bad:#dc2626}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--line:#44403c;--bad:#f87171}}}}
:root[data-theme=dark]{{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--line:#44403c;--bad:#f87171}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 6px}} .wrap{{overflow-x:auto}} table{{border-collapse:collapse;min-width:1100px}}
td,th{{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left;width:240px}}
img,video{{width:240px;border-radius:4px;display:block}} .m{{color:var(--muted);font-size:12px;margin:4px 0 0}} .bad{{color:var(--bad)}}
</style></head><body><h1>Image-to-video bake-off, free Kaggle T4</h1>
<p class=m>Same styled keyframe and prompt per row. Drift = mean pixel change from frame 0 within the shot's own length (red over 45);
light = darkest sampled frame (red under 30).</p><ul>{summary}</ul>
<div class=wrap><table><tr><th>keyframe</th>{head}</tr>{''.join(rows)}</table></div></body></html>"""
    out = WORK / "bakeoff.html"
    out.write_text(page, encoding="utf-8")
    print(json.dumps({"ok": True, "page": str(out)}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep"); p.add_argument("--session"); p.add_argument("--spec"); p.add_argument("--set", default="")
    for c in ("push", "status", "fetch"):
        q = sub.add_parser(c); q.add_argument("--model", required=True, choices=sorted(MODELS))
        q.add_argument("--set", default="")
        if c == "push":
            q.add_argument("--dry-run", action="store_true")
    g = sub.add_parser("page"); g.add_argument("--session"); g.add_argument("--set", default="")
    a = ap.parse_args()
    global SET, WORK
    if a.set:
        SET, WORK = a.set, WORK / a.set
    {"prep": cmd_prep, "push": cmd_push, "status": cmd_status, "fetch": cmd_fetch, "page": cmd_page}[a.cmd](a)


if __name__ == "__main__":
    main()
