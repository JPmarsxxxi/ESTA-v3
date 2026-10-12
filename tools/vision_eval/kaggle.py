"""Replay an eval sample on a larger open VLM on Kaggle's free 2xT4 (SPEC.md Part 8, handoff P1.6).

    python tools/vision_eval/kaggle.py push   --set <set> --model Qwen/Qwen3.5-9B --sample haiku-lean
    python tools/vision_eval/kaggle.py status --set <set> --model Qwen/Qwen3.5-9B
    python tools/vision_eval/kaggle.py apply  --set <set> --model Qwen/Qwen3.5-9B   # -> results_<slug>.jsonl

`--sample <results name>` replays exactly the items of results_<name>.jsonl, so the open
model is scored on the same items as that Haiku run. Transformers, fp16 (the T4 has no
bf16), device_map="auto" across both GPUs, thinking off, greedy. Interleaved text and
images, as the original calls sent them. System python (the Kaggle CLI lives there).
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, ensure_dataset, fetch_output, kaggle_username, kernel_status, push_kernel,
    slugify, use_utf8_stdout, wait_dataset_ready, write_kernel_dir,
)
from tools.match.common import load_config  # noqa: E402

use_utf8_stdout()
SYSTEM = "You check footage for a video editor. Reply with only the requested JSON."

NOTEBOOK = r'''# ESTA - vision eval replay (SPEC.md Part 8) on Kaggle's free 2xT4.
import subprocess, sys, json, os, glob, time, traceback, zipfile
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "transformers", "accelerate"], check=False)
import torch
from PIL import Image

MODEL = __MODEL__
HF_TOKEN = __HF_TOKEN__
PROBE = __PROBE__
SYSTEM = __SYSTEM__
OUT = "/kaggle/working"
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
os.environ["HF_HOME"] = "/kaggle/temp/hf"
print("gpus", torch.cuda.device_count(), [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())], flush=True)

hits = glob.glob(os.path.join("/kaggle/input", "**", PROBE), recursive=True)
IN = os.path.dirname(hits[0]) if hits else "/kaggle/input"
REQ = json.load(open(os.path.join(IN, "requests.json")))
for z in glob.glob(os.path.join("/kaggle/input", "**", "images.zip"), recursive=True):
    zipfile.ZipFile(z).extractall("/kaggle/temp/img")
PATHS = {}
for root in ("/kaggle/input", "/kaggle/temp/img"):
    for f in glob.glob(os.path.join(root, "**", "*.jpg"), recursive=True):
        PATHS.setdefault(os.path.basename(f), f)
results, info = {}, {"model": MODEL}

def finish(done=False):
    info["done"] = done
    json.dump({"results": results, "info": info}, open(os.path.join(OUT, "eval_results.json"), "w"))

t_load = time.time()
try:
    from transformers import AutoModelForImageTextToText, AutoProcessor
    processor = AutoProcessor.from_pretrained(MODEL)
    model = AutoModelForImageTextToText.from_pretrained(MODEL, dtype=torch.float16, device_map="auto")
    model.eval()
except Exception as e:
    info["load_error"] = traceback.format_exc()[-2000:]
    finish(done=True)
    raise
info["load_secs"] = round(time.time() - t_load, 1)
print("loaded in", info["load_secs"], "s", flush=True)

t0 = time.time()
for i, r in enumerate(REQ["requests"]):
    t = time.time()
    try:
        content = []
        for part in r["parts"]:
            if part[0] == "text":
                content.append({"type": "text", "text": part[1]})
            else:
                content.append({"type": "image", "image": Image.open(PATHS[part[1]]).convert("RGB")})
        msgs = [{"role": "system", "content": [{"type": "text", "text": SYSTEM}]}, {"role": "user", "content": content}]
        try:
            inputs = processor.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_tensors="pt",
                                                   return_dict=True, enable_thinking=False)
        except TypeError:
            inputs = processor.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_tensors="pt",
                                                   return_dict=True)
        inputs = inputs.to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=400, do_sample=False, repetition_penalty=1.05)
        text = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        results[r["id"]] = {"raw": text, "secs": round(time.time() - t, 2)}
    except Exception as e:
        results[r["id"]] = {"raw": "", "secs": None, "error": str(e)[:300]}
        traceback.print_exc()
    if i % 10 == 9:
        finish()
        print("[eval] %d/%d in %.0fs" % (i + 1, len(REQ["requests"]), time.time() - t0), flush=True)
info["run_secs"] = round(time.time() - t0, 1)
finish(done=True)
print("ESTA_EVAL_DONE", len(results), flush=True)
'''


def _slug(model: str) -> str:
    return slugify(model.split("/")[-1]).lower()


def _job(root: Path, model: str) -> Path:
    return root / "kaggle" / _slug(model)


def _names(root: Path, model: str) -> tuple[str, str]:
    h = hashlib.sha1(f"{root.resolve()}|{model}".encode()).hexdigest()[:6]
    base = slugify("esta-veval", _slug(model))[:34].rstrip("-")
    # Datasets and kernels share one slug namespace: different prefixes (kaggle-lane-gotchas).
    return f"{base}-in-{h}", f"{base}-run-{h}"


def cmd_push(root: Path, model: str, sample: str, kinds: list[str]) -> dict:
    items = {json.loads(x)["id"]: json.loads(x) for x in (root / "items.jsonl").read_text(encoding="utf-8").splitlines()}
    ids = [json.loads(x)["id"] for x in (root / f"results_{sample}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    chosen = [items[i] for i in ids if i in items and items[i]["kind"] in kinds]
    job = _job(root, model)
    if job.exists():
        shutil.rmtree(job)
    build = job / "dataset_build"
    build.mkdir(parents=True)
    requests = []
    with zipfile.ZipFile(build / "images.zip", "w", zipfile.ZIP_STORED) as z:
        for it in chosen:
            flat = [f"{it['id']}__{Path(p).name}" for p in it["images"]]
            for p, f in zip(it["images"], flat):
                z.write(root / p, f)
            if it["kind"] == "judge":
                parts = [["text", s] if isinstance(s, str) else ["image", flat[s["image"]]] for s in it["sequence"]]
            else:
                parts = []
                for k, f in enumerate(flat):
                    if it.get("labels"):
                        parts.append(["text", it["labels"][k]])
                    parts.append(["image", f])
            parts.append(["text", it["prompt"]])
            requests.append({"id": it["id"], "parts": parts})
    (build / "requests.json").write_text(json.dumps({"requests": requests}), encoding="utf-8")
    ds_name, k_name = _names(root, model)
    probe = f"{ds_name}-requests.json"
    (build / probe).write_text("{}", encoding="utf-8")
    user = kaggle_username()
    dataset = f"{user}/{ds_name}"
    for attempt in range(4):
        ok, log = ensure_dataset(build, dataset, ds_name)
        if ok:
            break
        time.sleep(20 * (attempt + 1))
    if not ok:
        raise RuntimeError(f"dataset upload failed: {log}")
    if not wait_dataset_ready(dataset, timeout=1200):
        raise RuntimeError("dataset never reached ready state")
    token = (load_config().get("apis") or {}).get("hf_token") or ""
    code = (NOTEBOOK.replace("__MODEL__", repr(model)).replace("__HF_TOKEN__", repr(token))
            .replace("__PROBE__", repr(probe)).replace("__SYSTEM__", repr(SYSTEM)))
    kernel = f"{user}/{k_name}"
    kbuild = job / "kernel_build"
    write_kernel_dir(kbuild, code, kernel, ACCELERATORS["t4"])
    meta = json.loads((kbuild / "kernel-metadata.json").read_text(encoding="utf-8"))
    meta["dataset_sources"] = [dataset]
    (kbuild / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    ok, log = push_kernel(kbuild)
    if not ok:
        raise RuntimeError(f"kernel push failed: {log}")
    state = {"kernel": kernel, "dataset": dataset, "model": model, "pushed_at": time.time(), "requests": len(requests)}
    (job / "kernel.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"ok": True, **state, "url": f"https://www.kaggle.com/code/{kernel}"}


def cmd_status(root: Path, model: str) -> dict:
    st = json.loads((_job(root, model) / "kernel.json").read_text(encoding="utf-8"))
    state, raw = kernel_status(st["kernel"])
    return {"ok": bool(state), "state": state, "raw": raw[-200:],
            "minutes": round((time.time() - st["pushed_at"]) / 60, 1)}


def cmd_apply(root: Path, model: str) -> dict:
    from tools.vision_eval.replay import parse_json
    job = _job(root, model)
    st = json.loads((job / "kernel.json").read_text(encoding="utf-8"))
    out = job / "kernel_out"
    fetch_output(st["kernel"], out)
    raw = json.loads((out / "eval_results.json").read_text(encoding="utf-8"))
    name = "kaggle-" + _slug(model)
    with open(root / f"results_{name}.jsonl", "w", encoding="utf-8") as fh:
        for iid, r in raw["results"].items():
            fh.write(json.dumps({"id": iid, "raw": r["raw"], "parsed": parse_json(r["raw"]), "secs": r.get("secs"),
                                 **({"error": r["error"]} if r.get("error") else {})}, ensure_ascii=False) + "\n")
    return {"ok": True, "results": len(raw["results"]), "info": raw["info"], "name": name}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["push", "status", "apply"])
    ap.add_argument("--set", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--sample", default="haiku-lean")
    ap.add_argument("--kinds", default="validate,frame_search,judge")
    a = ap.parse_args()
    root = Path(a.set)
    try:
        if a.mode == "push":
            out = cmd_push(root, a.model, a.sample, a.kinds.split(","))
        elif a.mode == "status":
            out = cmd_status(root, a.model)
        else:
            out = cmd_apply(root, a.model)
        print(json.dumps(out, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
