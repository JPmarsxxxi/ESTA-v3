"""Build a vision eval set from the run's own Haiku calls (SPEC.md Part 8, decision 3).

    python tools/vision_eval/extract.py --out D:/esta-perf/vision_eval/<name> \
        [--transcripts <claude project dir>] [--captures sessions/<id>/vision_eval]

Claude Code transcripts keep the exact images each `claude -p` call sent and the reply,
so the asset checks of a past run replay with no re-download:

- validate: 1-4 frames of a candidate, Haiku's match/mismatch (tools/assets/llm.py).
- frame_search: 5 frames of a YouTube video, Haiku's best index (the binary search).
- judge: the auto-pick judge (tools/match/autopick.py), split into one item per shot:
  the inspo frame, up to 3 candidates, Haiku's best/reject.

`--captures` adds the records written by ESTA_VISION_CAPTURE=1. Writes items.jsonl plus
one folder of JPEGs per item. Haiku's answer is stored as the baseline, not as truth.
"""

import argparse
import base64
import collections
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.usage.report import project_dir  # noqa: E402

JUDGE_TAIL = "Each shot above shows the INSPO frame"


def parse_json(text: str):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(m.group()) if m else None
    except ValueError:
        return None


def load(path: Path) -> tuple[list, str, str]:
    """(user content blocks incl. attachment images, reply text, model) of a one-shot transcript."""
    content, reply, model = [], "", ""
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        t = o.get("type")
        if t == "user" and not content:
            c = o["message"]["content"]
            content = [{"type": "text", "text": c}] if isinstance(c, str) else list(c)
        elif t == "attachment" and (o.get("attachment") or {}).get("type") == "file":
            f = (o["attachment"].get("content") or {}).get("file") or {}
            if f.get("base64"):
                content.append({"type": "image", "data": f["base64"]})
        elif t == "assistant":
            msg = o["message"]
            if msg.get("model") == "<synthetic>":
                return [], "", ""
            model = msg.get("model", model)
            reply += "".join(c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text")
    for c in content:
        if c.get("type") == "image" and "source" in c:
            c["data"] = c["source"].get("data", "")
    return content, reply, model


def save(out: Path, iid: str, images: list[str]) -> list[str]:
    d = out / "items" / iid
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for i, b in enumerate(images):
        p = d / f"{i}.jpg"
        p.write_bytes(base64.b64decode(b))
        files.append(str(p.relative_to(out)).replace("\\", "/"))
    return files


def items_from_transcript(path: Path, out: Path) -> list[dict]:
    content, reply, model = load(path)
    if not content or not reply:
        return []
    texts = [c["text"] for c in content if c.get("type") == "text"]
    images = [c["data"] for c in content if c.get("type") == "image" and c.get("data")]
    head = texts[0] if texts else ""
    src = {"source": path.name, "model": model, "raw": reply}
    if head.startswith("These frames are from a clip") and images:
        prompt = head.split(" @")[0].strip()
        iid = "v-" + hashlib.sha1(path.name.encode()).hexdigest()[:12]
        return [{"id": iid, "kind": "validate", "prompt": prompt, "images": save(out, iid, images), "labels": None,
                 "baseline": {**src, "parsed": parse_json(reply)}}]
    if head.startswith("Round ") and "visual search" in head and images:
        prompt = head.split(" @")[0].strip()
        iid = "f-" + hashlib.sha1(path.name.encode()).hexdigest()[:12]
        return [{"id": iid, "kind": "frame_search", "prompt": prompt, "images": save(out, iid, images),
                 "labels": [f"frame {i}:" for i in range(len(images))], "baseline": {**src, "parsed": parse_json(reply)}}]
    if texts and texts[-1].startswith(JUDGE_TAIL):
        answer = parse_json(reply) or {}
        tail = texts[-1]
        shots, cur = [], None
        for c in content:
            if c.get("type") == "text":
                m = re.match(r"Shot (\d+)\. Spoken line", c["text"])
                if m:
                    cur = {"n": m.group(1), "blocks": []}
                    shots.append(cur)
                if cur is not None and c["text"] is not tail:
                    cur["blocks"].append({"type": "text", "text": c["text"]})
            elif c.get("type") == "image" and cur is not None:
                cur["blocks"].append({"type": "image", "data": c["data"]})
        items = []
        for sh in shots:
            verdict = answer.get(sh["n"])
            if not isinstance(verdict, dict):
                continue
            imgs = [b["data"] for b in sh["blocks"] if b["type"] == "image"]
            iid = "j-" + hashlib.sha1(f"{path.name}|{sh['n']}".encode()).hexdigest()[:12]
            files = save(out, iid, imgs)
            # Text pieces in order, with {image:k} markers where each image went.
            seq, k = [], 0
            for b in sh["blocks"]:
                if b["type"] == "text":
                    seq.append(b["text"])
                else:
                    seq.append({"image": k})
                    k += 1
            items.append({"id": iid, "kind": "judge", "prompt": tail, "sequence": seq, "images": files,
                          "shot": int(sh["n"]), "n_candidates": sum(1 for b in sh["blocks"] if b["type"] == "text"
                                                                     and " candidate " in b["text"]),
                          "baseline": {**src, "raw": json.dumps(verdict), "parsed": verdict}})
        return items
    return []


def items_from_captures(cap: Path, out: Path) -> list[dict]:
    items = []
    for line in (cap / "records.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("error") or not r.get("parsed"):
            continue
        iid = "c-" + r["id"]
        d = out / "items" / iid
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for i, f in enumerate(r["frame_files"]):
            shutil.copy(cap / f, d / f"{i}.jpg")
            files.append(f"items/{iid}/{i}.jpg")
        items.append({"id": iid, "kind": r["kind"], "prompt": r["prompt"], "images": files,
                      "labels": [f"frame {i}:" for i in range(len(files))] if r["kind"] == "frame_search" else None,
                      "url": r.get("url"), "baseline": {"source": "capture", "model": r.get("model"),
                                                        "raw": r.get("raw_result"), "parsed": r["parsed"]}})
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--transcripts", nargs="?", const="")
    ap.add_argument("--captures", action="append", default=[])
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items, skipped = [], collections.Counter()
    if a.transcripts is not None:
        d = Path(a.transcripts) if a.transcripts else project_dir()
        for p in sorted(d.glob("*.jsonl")):
            if p.stat().st_size > 20_000_000:
                continue
            got = items_from_transcript(p, out)
            items += got
            if not got:
                skipped["not a replayable vision call"] += 1
    for c in a.captures:
        items += items_from_captures(Path(c), out)
    with open(out / "items.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(json.dumps({"items": len(items), "by_kind": collections.Counter(i["kind"] for i in items),
                      "skipped": skipped, "out": str(out)}, indent=1))


if __name__ == "__main__":
    main()
