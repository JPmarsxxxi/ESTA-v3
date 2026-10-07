"""Where the Claude usage went (SPEC.md Part 8).

    python tools/usage/report.py --session sessions/<id>        # the session's usage.jsonl, by call kind
    python tools/usage/report.py --transcripts [<project dir>]  # every Claude Code transcript of a project

`--transcripts` defaults to this repo's folder under ~/.claude/projects. It sums each
transcript's token usage, separates interactive sessions from one-shot `claude -p`
calls (classified by their prompt), and counts calls that came back as a usage-limit
notice. `--json <file>` also writes the per-transcript rows.
"""

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# API list prices per million tokens (input, cache write, cache read, output), only to rank items.
PRICES = {"opus": (5, 6.25, 0.5, 25), "sonnet": (3, 3.75, 0.3, 15), "haiku": (1, 1.25, 0.1, 5)}
KINDS = (("verify the frames", "validate"), ("round ", "frame_search"), ("select the", "pick_videos"),
         ("find the exact moment", "find_moment"), ("pick the candidate", "judge"),
         ("search queries", "rewrite"), ("shot", "judge/describe"))


def price(model: str, cin: float, cw: float, cr: float, out: float) -> float:
    p = next((v for k, v in PRICES.items() if k in (model or "")), None)
    return 0.0 if p is None else (cin * p[0] + cw * p[1] + cr * p[2] + out * p[3]) / 1e6


def project_dir() -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(REPO_ROOT))
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    return base / slug


def scan(path: Path) -> dict:
    first, models, seen = "", collections.Counter(), set()
    u = collections.Counter()
    limited = t0 = t1 = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            ts = o.get("timestamp")
            if ts:
                t0, t1 = t0 or ts, ts
            msg = o.get("message") or {}
            if o.get("type") == "user" and not first:
                c = msg.get("content")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
                first = (c or "").strip()[:200] if isinstance(c, str) else ""
            if o.get("type") != "assistant" or msg.get("id") in seen:
                continue
            seen.add(msg.get("id"))
            if msg.get("model") == "<synthetic>":
                text = " ".join(c.get("text", "") for c in msg.get("content", []) if isinstance(c, dict))
                if "limit" in text.lower():
                    limited = text[:80]
                continue
            models[msg.get("model")] += 1
            us = msg.get("usage") or {}
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
                u[k] += us.get(k) or 0
    turns = sum(models.values())
    model = models.most_common(1)[0][0] if models else ""
    return {"file": path.name, "first": first, "model": model, "turns": turns, "limited": limited, "t0": t0, "t1": t1,
            "in": u["input_tokens"], "cw": u["cache_creation_input_tokens"], "cr": u["cache_read_input_tokens"],
            "out": u["output_tokens"],
            "usd": price(model, u["input_tokens"], u["cache_creation_input_tokens"], u["cache_read_input_tokens"],
                         u["output_tokens"])}


def kind(row: dict) -> str:
    if row["turns"] > 3:
        return "interactive session"
    p = row["first"].lower()
    return "claude -p: " + next((name for key, name in KINDS if key in p), "other")


def report_transcripts(d: Path, out_json: str | None) -> None:
    rows = [scan(p) for p in sorted(d.glob("*.jsonl"))]
    if out_json:
        Path(out_json).write_text(json.dumps(rows, indent=0), encoding="utf-8")
    agg = collections.defaultdict(collections.Counter)
    for r in rows:
        k = (kind(r), r["model"] or "-")
        a = agg[k]
        a["files"] += 1
        a["limited"] += 1 if r["limited"] else 0
        for f in ("turns", "in", "cw", "cr", "out", "usd"):
            a[f] += r[f]
    total = sum(a["usd"] for a in agg.values()) or 1
    print(f"{d}  ({len(rows)} transcripts)\n")
    print(f"{'kind':34} {'model':28} {'calls':>6} {'turns':>6} {'in':>7} {'cache_w':>8} {'cache_r':>8} {'out':>6} "
          f"{'limit':>6} {'~share':>7}   (tokens in millions)")
    for (k, m), a in sorted(agg.items(), key=lambda kv: -kv[1]["usd"]):
        print(f"{k:34} {m:28} {a['files']:6} {a['turns']:6} {a['in'] / 1e6:7.2f} {a['cw'] / 1e6:8.2f} "
              f"{a['cr'] / 1e6:8.2f} {a['out'] / 1e6:6.2f} {a['limited']:6} {100 * a['usd'] / total:6.1f}%")
    for r in sorted((r for r in rows if r["turns"] > 3), key=lambda r: -r["usd"])[:5]:
        print(f"\n{r['file'][:8]}  {r['t0'][:16]} -> {r['t1'][:16]}  {r['turns']} turns, "
              f"avg context {(r['in'] + r['cw'] + r['cr']) / max(1, r['turns']) / 1000:.0f}k tokens/turn: {r['first'][:70]!r}")


def report_session(session: Path) -> None:
    path = session / "usage.jsonl"
    if not path.exists():
        sys.exit(f"no {path}")
    agg = collections.defaultdict(collections.Counter)
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        a = agg[r["kind"]]
        a["calls"] += 1
        a["failed"] += 0 if r.get("ok") else 1
        for f in ("input", "cache_write", "cache_read", "output", "cost_usd", "secs"):
            a[f] += r.get(f, 0)
    print(f"{'kind':14} {'calls':>6} {'failed':>6} {'in':>9} {'out':>8} {'cost $':>8} {'avg s':>6}")
    for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["cost_usd"]):
        print(f"{k:14} {a['calls']:6} {a['failed']:6} {a['input'] + a['cache_write'] + a['cache_read']:9} "
              f"{a['output']:8} {a['cost_usd']:8.3f} {a['secs'] / a['calls']:6.1f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session")
    ap.add_argument("--transcripts", nargs="?", const="")
    ap.add_argument("--json", dest="out_json")
    a = ap.parse_args()
    for s in (sys.stdout,):
        s.reconfigure(encoding="utf-8", errors="replace")
    if a.session:
        report_session(Path(a.session))
    elif a.transcripts is not None:
        report_transcripts(Path(a.transcripts) if a.transcripts else project_dir(), a.out_json)
    else:
        ap.error("pass --session or --transcripts")


if __name__ == "__main__":
    main()
