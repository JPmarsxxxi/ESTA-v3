"""Replay an eval set (extract.py) through a vision backend and score it against Haiku's
original answers and any human labels (SPEC.md Part 8).

    python tools/vision_eval/replay.py --set D:/esta-perf/vision_eval/<name> --backend claude
    python tools/vision_eval/replay.py --set ... --backend openai --url http://localhost:8080/v1 --name qwen3vl-4b
    python tools/vision_eval/replay.py --set ... --backend clip      # frame_search only, local CLIP
    python tools/vision_eval/replay.py --set ... --backend qwen-live --per-kind 60 --workers 8   # the live Kaggle server (Part 10)
    python tools/vision_eval/replay.py --set ... --score             # metrics for every results_*.jsonl

Results go to <set>/results_<name>.jsonl (resumable: items already there are skipped).
`--kinds validate,frame_search,judge` and `--per-kind N` (a fixed sample) narrow a run.
The prompt text and images are exactly what the original call sent.
"""

import argparse
import base64
import collections
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

KINDS = ("validate", "frame_search", "judge")


def parse_json(text: str):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(m.group()) if m else None
    except ValueError:
        return None


def blocks(item: dict, root: Path) -> list[tuple[str, str]]:
    """The item as ordered ("text", s) / ("image", base64) parts, as the original call sent them."""
    img = [base64.b64encode((root / p).read_bytes()).decode("ascii") for p in item["images"]]
    if item["kind"] == "judge":
        out = [("text", s) if isinstance(s, str) else ("image", img[s["image"]]) for s in item["sequence"]]
        return out + [("text", item["prompt"])]
    out = []
    for i, b in enumerate(img):
        if item.get("labels"):
            out.append(("text", item["labels"][i]))
        out.append(("image", b))
    return out + [("text", item["prompt"])]


# ── backends: item -> (raw text, seconds, extra) ─────────────────────────────

def claude_backend(model: str, thinking: bool):
    import os
    import subprocess
    from tools.assets import llm

    if thinking:
        def spawn(argv, message, timeout):
            env = {k: v for k, v in os.environ.items() if k != "MAX_THINKING_TOKENS"}
            r = subprocess.run(argv, input=message + "\n", capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, env=env)
            return r.stdout or r.stderr
        llm._spawn = spawn

    def run(item, root):
        content = [{"type": "text", "text": v} if k == "text" else llm._image(v) for k, v in blocks(item, root)]
        t = time.time()
        return llm._ask(content, f"eval_{item['kind']}", model=model, timeout=120), time.time() - t, {}
    return run


def openai_backend(url: str, model: str, max_tokens: int, json_mode: bool):
    import requests

    def run(item, root):
        parts = [{"type": "text", "text": v} if k == "text" else
                 {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{v}"}} for k, v in blocks(item, root)]
        body = {"model": model, "temperature": 0.01, "max_tokens": max_tokens, "repeat_penalty": 1.1,
                "messages": [{"role": "system", "content": "You check footage for a video editor. Reply with only the requested JSON."},
                             {"role": "user", "content": parts}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t = time.time()
        r = requests.post(url.rstrip("/") + "/chat/completions", json=body, timeout=600)
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"], time.time() - t, {"usage": j.get("usage"), "timings": j.get("timings")}
    return run


def qwen_live_backend(max_tokens: int):
    """The live Kaggle server (SPEC.md Part 10) through the pipeline's own client, same system prompt as the
    Part 8 Kaggle replay."""
    from tools.vision_server import client

    def run(item, root):
        content = [{"type": "text", "text": v} if k == "text" else
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": v}} for k, v in blocks(item, root)]
        t = time.time()
        raw = client.chat(content, "You check footage for a video editor. Reply with only the requested JSON.",
                          f"eval_{item['kind']}", max_tokens=max_tokens)
        return raw, time.time() - t, {}
    return run


_EMB = {}


def embed_backend(kind: str):
    """frame_search only: rank the frames by similarity to the prompt's TARGET text."""
    import torch
    from PIL import Image
    lock = threading.Lock()

    def model():
        if not _EMB:
            from transformers import AutoModel, AutoProcessor
            mid = {"clip": "openai/clip-vit-base-patch32", "siglip": "google/siglip2-base-patch16-224"}[kind]
            _EMB["m"], _EMB["p"] = AutoModel.from_pretrained(mid).eval(), AutoProcessor.from_pretrained(mid)
        return _EMB["m"], _EMB["p"]

    def run(item, root):
        target = re.search(r'TARGET[^\n]*\n\s*"(.*?)"\n', item["prompt"], re.DOTALL)
        text = (target.group(1) if target else item["prompt"])[:300]
        ims = [Image.open(root / p).convert("RGB") for p in item["images"]]
        t = time.time()
        with lock, torch.no_grad():
            m, p = model()
            if kind == "siglip":
                x = p(text=[text], images=ims, return_tensors="pt", padding="max_length", max_length=64, truncation=True)
            else:
                x = p(text=[text], images=ims, return_tensors="pt", padding=True, truncation=True)
            out = m(**x)
            s = out.logits_per_image.squeeze(1).tolist()
        best = max(range(len(s)), key=s.__getitem__)
        return json.dumps({"best_index": best, "scores": [round(v, 3) for v in s]}), time.time() - t, {}
    return run


# ── scoring ──────────────────────────────────────────────────────────────────

def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def score(items: dict, results: list[dict], labels: dict) -> dict:
    by = collections.defaultdict(list)
    for r in results:
        it = items.get(r["id"])
        if it:
            by[it["kind"]].append((it, r))
    out = {}
    for kind, pairs in by.items():
        n = len(pairs)
        ok = [(it, r, r.get("parsed")) for it, r in pairs]
        valid = [(it, r, p) for it, r, p in ok if isinstance(p, dict)]
        secs = sorted(r["secs"] for _, r, _ in ok if r.get("secs") is not None)
        m = {"n": n, "json_valid": round(len(valid) / n, 3) if n else 0,
             "median_secs": round(secs[len(secs) // 2], 2) if secs else None}
        if kind == "validate":
            cm = collections.Counter()
            for it, r, p in valid:
                cm[(bool((it["baseline"]["parsed"] or {}).get("matches")), bool(p.get("matches")))] += 1
            m["agree_haiku"] = round((cm[(True, True)] + cm[(False, False)]) / max(1, len(valid)), 3)
            m["says_match_where_haiku_mismatch"] = round(cm[(False, True)] / max(1, cm[(False, True)] + cm[(False, False)]), 3)
            m["says_mismatch_where_haiku_match"] = round(cm[(True, False)] / max(1, cm[(True, True)] + cm[(True, False)]), 3)
            lab = [(labels[it["id"]], bool(p.get("matches"))) for it, r, p in valid if it["id"] in labels]
            if lab:
                neg = [s for t, s in lab if t == "mismatch"]
                pos = [s for t, s in lab if t == "match"]
                m["labelled"] = len(lab)
                m["false_match_rate"] = round(sum(neg) / len(neg), 3) if neg else None
                m["false_reject_rate"] = round(sum(not s for s in pos) / len(pos), 3) if pos else None
        elif kind == "frame_search":
            exact = near = 0
            for it, r, p in valid:
                b, h = _int(p.get("best_index")), _int((it["baseline"]["parsed"] or {}).get("best_index"))
                exact += b == h
                near += b is not None and h is not None and abs(b - h) <= 1
            m["same_frame_as_haiku"] = round(exact / max(1, len(valid)), 3)
            m["within_one_frame"] = round(near / max(1, len(valid)), 3)
            m["chance_same_frame"] = 0.2
        elif kind == "judge":
            same = rej = 0
            for it, r, p in valid:
                h = it["baseline"]["parsed"]
                if len(p) == 1 and isinstance(next(iter(p.values())), dict):
                    p = next(iter(p.values()))
                same += _int(p.get("best")) == _int(h.get("best"))
                hr = {_int(x) for x in h.get("reject") or []}
                pr = {_int(x) for x in p.get("reject") or []}
                rej += len(hr & pr) / max(1, len(hr | pr)) if (hr or pr) else 1
            m["same_best_as_haiku"] = round(same / max(1, len(valid)), 3)
            m["reject_overlap"] = round(rej / max(1, len(valid)), 3)
            # Human labels: best_<k> or none. A pick the human called unusable ships bad footage.
            lab = []
            for it, r, p in valid:
                if it["id"] not in labels:
                    continue
                if len(p) == 1 and isinstance(next(iter(p.values())), dict):
                    p = next(iter(p.values()))
                lab.append((labels[it["id"]], _int(p.get("best"))))
            if lab:
                m["labelled"] = len(lab)
                m["same_best_as_human"] = round(sum(t == f"best_{b}" for t, b in lab) / len(lab), 3)
                none = [b for t, b in lab if t == "none"]
                m["picked_when_human_said_none"] = round(len(none) / len(lab), 3)
        out[kind] = m
    return out


def load_labels(root: Path) -> dict:
    p = root / "labels.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        out[r["id"]] = r["label"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True)
    ap.add_argument("--backend", choices=["claude", "openai", "qwen-live", "clip", "siglip"])
    ap.add_argument("--name")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--url", default="http://localhost:8080/v1")
    ap.add_argument("--kinds", default=",".join(KINDS))
    ap.add_argument("--per-kind", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--no-json-mode", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--thinking", action="store_true", help="claude backend: leave Haiku's thinking on")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(a.set)
    items = {}
    for line in (root / "items.jsonl").read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        items[it["id"]] = it
    labels = load_labels(root)

    if a.score:
        table = {}
        for f in sorted(root.glob("results_*.jsonl")):
            rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            table[f.stem[len("results_"):]] = score(items, rows, labels)
        (root / "metrics.json").write_text(json.dumps(table, indent=1), encoding="utf-8")
        print(json.dumps(table, indent=1))
        return

    name = a.name or (a.backend if a.backend != "claude" else "haiku-lean")
    kinds = a.kinds.split(",")
    todo = [it for it in items.values() if it["kind"] in kinds]
    if a.backend in ("clip", "siglip"):
        todo = [it for it in todo if it["kind"] == "frame_search"]
    if a.per_kind:
        rnd = random.Random(a.seed)
        picked = []
        for k in kinds:
            pool = sorted((it for it in todo if it["kind"] == k), key=lambda it: it["id"])
            picked += rnd.sample(pool, min(a.per_kind, len(pool)))
        todo = picked
    out_path = root / f"results_{name}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(x)["id"] for x in out_path.read_text(encoding="utf-8").splitlines() if x.strip()}
    todo = [it for it in todo if it["id"] not in done]
    run = {"claude": lambda: claude_backend(a.model, a.thinking),
           "openai": lambda: openai_backend(a.url, a.name or "local", a.max_tokens, not a.no_json_mode),
           "qwen-live": lambda: qwen_live_backend(max(a.max_tokens, 1024)),
           "clip": lambda: embed_backend("clip"), "siglip": lambda: embed_backend("siglip")}[a.backend]()
    lock = threading.Lock()
    print(f"{name}: {len(todo)} items to run ({len(done)} already done)", flush=True)

    def one(it):
        try:
            raw, secs, extra = run(it, root)
            row = {"id": it["id"], "raw": raw, "parsed": parse_json(raw), "secs": round(secs, 2), **extra}
        except Exception as e:  # noqa: BLE001 - recorded as an invalid answer
            row = {"id": it["id"], "raw": "", "parsed": None, "secs": None, "error": str(e)[:300]}
        with lock, open(out_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    t0, n = time.time(), 0
    with ThreadPoolExecutor(a.workers) as pool:
        for row in pool.map(one, todo):
            n += 1
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  {time.time() - t0:.0f}s  last: {str(row.get('error') or row['raw'])[:80]!r}",
                      flush=True)
    rows = [json.loads(x) for x in out_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(json.dumps(score(items, rows, labels), indent=1))


if __name__ == "__main__":
    main()
