"""The M5 vision-language lane: a batch of image+prompt requests answered by
Gemma 4 (or another bake-off tag model) on Kaggle's free T4.

Both inspo tagging and auto-pick use it, so there is one notebook to keep
working. A job is a folder holding `requests.json` and an `images/` directory:

    {"model": "gemma4-e4b", "requests": [{"id": "s12", "images": ["a.jpg", "b.jpg"],
      "prompt": "...", "max_new_tokens": 200}]}

    python tools/match/vlm_kaggle.py push   --job <dir>
    python tools/match/vlm_kaggle.py status --job <dir>
    python tools/match/vlm_kaggle.py apply  --job <dir>     # -> <dir>/results.json {id: text}
    python tools/match/vlm_kaggle.py run    --job <dir>     # push, wait, apply

System python (the Kaggle CLI lives there), like the other Kaggle lanes.
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, ensure_dataset, fetch_output, kaggle_username, kernel_status, push_kernel,
    slugify, use_utf8_stdout, wait_dataset_ready, write_kernel_dir,
)
from tools.match.common import MODEL_IDS, load_config  # noqa: E402

use_utf8_stdout()

NOTEBOOK = r'''# ESTA - M5 vision-language batch (tagging / auto-pick) on Kaggle's free GPU.
import subprocess, sys, json, os, glob, time, traceback
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "transformers", "accelerate"], check=False)
import torch
from PIL import Image

MODEL = __MODEL__
HF_TOKEN = __HF_TOKEN__
PROBE = __PROBE__
OUT = "/kaggle/working"
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
os.environ["HF_HOME"] = "/kaggle/temp/hf"

hits = glob.glob(os.path.join("/kaggle/input", "**", PROBE), recursive=True)
IN = os.path.dirname(hits[0]) if hits else "/kaggle/input"
REQ = json.load(open(os.path.join(IN, "requests.json")))
results, errors = {}, {}

def finish(done=False):
    json.dump({"results": results, "errors": errors, "done": done}, open(os.path.join(OUT, "vlm_results.json"), "w"))

from transformers import AutoProcessor
if "qwen" in MODEL.lower():
    from transformers import BitsAndBytesConfig, Qwen3VLForConditionalGeneration
    processor = AutoProcessor.from_pretrained(MODEL)
    model = Qwen3VLForConditionalGeneration.from_pretrained(MODEL, dtype=torch.bfloat16, device_map="auto",
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16))
else:
    from transformers import AutoModelForImageTextToText
    processor = AutoProcessor.from_pretrained(MODEL, padding_side="left")
    model = AutoModelForImageTextToText.from_pretrained(MODEL, device_map="auto", attn_implementation="sdpa")

t0 = time.time()
for i, r in enumerate(REQ["requests"]):
    try:
        content = [{"type": "image", "image": Image.open(os.path.join(IN, p)).convert("RGB")} for p in r["images"]]
        content.append({"type": "text", "text": r["prompt"]})
        inputs = processor.apply_chat_template([{"role": "user", "content": content}], tokenize=True,
            add_generation_prompt=True, return_tensors="pt", return_dict=True).to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=int(r.get("max_new_tokens", 200)), do_sample=False)
        results[r["id"]] = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    except Exception as e:
        errors[r["id"]] = str(e)[:300]
        traceback.print_exc()
    if i % 20 == 19:
        finish()
        print("[vlm] %d/%d in %.0fs" % (i + 1, len(REQ["requests"]), time.time() - t0), flush=True)
finish(done=True)
print("ESTA_VLM_DONE", len(results), "ok,", len(errors), "errors")
'''


def _name(job: Path) -> str:
    # Kaggle caps slugs at 50 and the dataset adds "-data": 38 + 1 + 6 + 5 = 50.
    return slugify("esta-vlm", job.name)[:38].rstrip("-") + "-" + hashlib.sha1(str(job.resolve()).encode()).hexdigest()[:6]


def cmd_push(job: Path) -> dict:
    spec = json.loads((job / "requests.json").read_text(encoding="utf-8"))
    model_key = spec.get("model") or "gemma4-e4b"
    model_id = MODEL_IDS.get(model_key, model_key)
    user = kaggle_username()
    name = _name(job)

    build = job / "dataset_build"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    for r in spec["requests"]:
        for img in r["images"]:
            dst = build / img
            if not dst.exists():
                shutil.copy(job / "images" / img, dst)
    (build / "requests.json").write_text(json.dumps(spec), encoding="utf-8")
    probe = f"{name}-requests.json"
    (build / probe).write_text("{}", encoding="utf-8")

    dataset = f"{user}/{name}-data"
    # The upload drops on a flaky connection (SSL EOF mid-blob); retrying is enough.
    for attempt in range(4):
        ok, log = ensure_dataset(build, dataset, dataset.split("/", 1)[-1])
        if ok:
            break
        time.sleep(20 * (attempt + 1))
    if not ok:
        raise RuntimeError(f"dataset upload failed: {log}")
    if not wait_dataset_ready(dataset, timeout=1200):
        raise RuntimeError("dataset never reached ready state")

    token = (load_config().get("apis") or {}).get("hf_token") or ""
    code = (NOTEBOOK.replace("__MODEL__", repr(model_id)).replace("__HF_TOKEN__", repr(token))
            .replace("__PROBE__", repr(probe)))
    kernel = f"{user}/{name}"
    kbuild = job / "kernel_build"
    write_kernel_dir(kbuild, code, kernel, ACCELERATORS["t4"])
    meta = json.loads((kbuild / "kernel-metadata.json").read_text(encoding="utf-8"))
    meta["dataset_sources"] = [dataset]
    (kbuild / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    ok, log = push_kernel(kbuild)
    if not ok:
        raise RuntimeError(f"kernel push failed: {log}")
    state = {"kernel": kernel, "dataset": dataset, "pushed_at": time.time(), "requests": len(spec["requests"])}
    (job / "kernel.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"ok": True, **state, "url": f"https://www.kaggle.com/code/{kernel}"}


def _kernel(job: Path) -> str:
    return json.loads((job / "kernel.json").read_text(encoding="utf-8"))["kernel"]


def cmd_status(job: Path) -> dict:
    state, raw = kernel_status(_kernel(job))
    return {"ok": bool(state), "state": state, "raw": raw[-200:]}


def cmd_apply(job: Path) -> dict:
    out = job / "kernel_out"
    fetch_output(_kernel(job), out)
    raw = json.loads((out / "vlm_results.json").read_text(encoding="utf-8"))
    (job / "results.json").write_text(json.dumps(raw["results"], indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "results": len(raw["results"]), "errors": raw["errors"], "complete": raw.get("done", False)}


def run(job: Path, poll: int = 60, timeout: int = 4 * 3600, log=print) -> dict:
    """Push, wait for a terminal state, apply. Transport blips keep polling."""
    if (job / "results.json").exists():
        return {"ok": True, "cached": True, "results": len(json.loads((job / "results.json").read_text(encoding="utf-8")))}
    if not (job / "kernel.json").exists():
        log(json.dumps(cmd_push(job)))
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = cmd_status(job)
        log(f"[vlm] {job.name}: {st['state'] or 'unknown'}")
        if st["state"] in ("complete", "error", "cancel"):
            break
        time.sleep(poll)
    res = cmd_apply(job)
    if not res["results"]:
        raise RuntimeError(f"Kaggle run produced no results ({res['errors']})")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["push", "status", "apply", "run"])
    ap.add_argument("--job", required=True)
    ap.add_argument("--poll", type=int, default=60)
    a = ap.parse_args()
    job = Path(a.job)
    try:
        if a.mode == "run":
            out = run(job, a.poll, log=lambda m: print(m, flush=True))
        else:
            out = {"push": cmd_push, "status": cmd_status, "apply": cmd_apply}[a.mode](job)
        print(json.dumps(out, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
