"""Word-card motion graphics for shots that stock can't fill (SPEC.md Part 7, decision 5).

    python tools/motiongraphics/wordcard.py --session sessions/<id> --shots 12,40

A shot past the stock budget becomes a full-frame card of its own spoken line, in the
session kit's `line()` shape (`<div class='line'>` of `.w` spans landed by `words()`).
Each config is built by build.py, rendered by HyperFrames, checked with ffprobe and
published to assets_progress.jsonl and motion_graphics.json like any MG slot. Without
a kit the shots are listed in stock_overflow.json for the motion-graphics skill.
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.motiongraphics.build import HOLD_TAIL, build_slot, canvas  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGIBLE = 0.8       # the last word lands this long before the cut
BREAK_OVER = 6      # a line longer than this many words wraps once (the kit's .line never wraps)


def card(words: str, dur: float) -> tuple[str, str]:
    parts = re.findall(r"[\w'’%$.,-]+", words)
    parts = [p.strip(".,") or p for p in parts] or ["…"]
    last = max(0.0, dur - LEGIBLE)
    k = len(parts)
    times = [round(last * i / (k - 1), 2) for i in range(k)] if k > 1 and last > 0.2 else [0.05] * k
    mid = (k + 1) // 2 if k > BREAK_OVER else None
    spans = []
    for i, p in enumerate(parts):
        spans.append(("<br>" if i == mid else "") + f"<span class='w' id='w{i}'>{html.escape(p)}</span>")
    body = f"<div class='line'>{' '.join(spans)}</div>"
    tl = f"words(tl, {json.dumps([f'#w{i}' for i in range(k)])}, {json.dumps(times)});"
    return body, tl


def write_configs(session: Path, shots: list[dict]) -> list[dict]:
    out = []
    slots = session / "assets" / "mg" / "_kit" / "slots"
    slots.mkdir(parents=True, exist_ok=True)
    for s in shots:
        dur = round(float(s["end"]) - float(s["start"]), 3)
        body, tl = card(s.get("audio", ""), dur)
        cfg = {"key": str(s["shot_number"]), "flavor": "full_frame", "duration": dur, "body": body, "timeline": tl,
               "origin": "stock_cap"}
        (slots / f"{s['shot_number']}.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        out.append(cfg)
    return out


def _probe(f: Path) -> tuple[float, int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration", "-of", "json",
                        str(f)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    st = (j.get("streams") or [{}])[0]
    return float(j.get("format", {}).get("duration", 0) or 0), st.get("width") or 0, st.get("height") or 0


def render(session: Path, cfg: dict) -> tuple[Path | None, str]:
    """Render one built full-frame slot and check it; (file, "") or (None, error)."""
    npx = shutil.which("npx")
    if not npx:
        return None, "npx not found"
    out = session / "assets" / "source_pool" / f"mg_{cfg['key']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([npx, "hyperframes", "render", str(session / "assets" / "mg" / f"slot_{cfg['key']}"),
                            "-o", str(out)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=600)
    except subprocess.TimeoutExpired:
        return None, "render timed out"
    if r.returncode:
        return None, (r.stderr or r.stdout)[-300:]
    dur, w, h = _probe(out)
    errs = []
    if abs(dur - (cfg["duration"] + HOLD_TAIL)) > 0.15:
        errs.append(f"duration {dur:.2f} vs {cfg['duration'] + HOLD_TAIL:.2f}")
    if (w, h) != canvas(session):
        errs.append(f"size {w}x{h}")
    return (None, "; ".join(errs)) if errs else (out, "")


def publish(session: Path, cfg: dict, file: Path) -> None:
    rel = file.resolve().relative_to(REPO_ROOT).as_posix()
    with open(session / "assets_progress.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"shot_number": int(cfg["key"]), "ok": True, "source": "hyperframes", "asset_type": "video",
                             "url": "", "file": rel, "search_query": "", "in_point": 0.0, "out_point": cfg["duration"],
                             "error": "", "visual_verdict": "match", "visual_confidence": 100}) + "\n")
    mg_path = session / "motion_graphics.json"
    mg = json.loads(mg_path.read_text(encoding="utf-8")) if mg_path.exists() else {"slots": []}
    slots = [s for s in mg.get("slots", []) if str(s.get("key")) != cfg["key"]]
    slots.append({"key": cfg["key"], "flavor": "full_frame", "ok": True, "file": rel, "origin": "stock_cap"})
    ok = sum(1 for s in slots if s.get("ok"))
    mg.update({"slots": slots, "generated": ok, "fallbacks": len(slots) - ok,
               "generated_at": datetime.now(timezone.utc).isoformat()})
    mg_path.write_text(json.dumps(mg, indent=1), encoding="utf-8")


def overflow(session: Path, shots: list[dict], reason: str) -> None:
    path = session / "stock_overflow.json"
    have = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"shots": []}
    keep = [x for x in have.get("shots", []) if x["shot_number"] not in {s["shot_number"] for s in shots}]
    keep += [{"shot_number": s["shot_number"], "audio": s.get("audio", ""), "reason": reason} for s in shots]
    path.write_text(json.dumps({"shots": sorted(keep, key=lambda x: x["shot_number"])}, indent=1), encoding="utf-8")


def make(session: Path, shots: list[dict], log=print) -> dict:
    """Word cards for `shots`: {"published": [n], "failed": {n: error}, "queued": [n] (no kit yet)}."""
    kit = session / "assets" / "mg" / "_kit"
    if not (kit / "surface.css").exists():
        overflow(session, shots, "no session kit yet")
        log(f"[wordcard] no kit: {len(shots)} shots listed in stock_overflow.json")
        return {"published": [], "failed": {}, "queued": [s["shot_number"] for s in shots]}
    css = (kit / "surface.css").read_text(encoding="utf-8")
    js = (kit / "helpers.js").read_text(encoding="utf-8") if (kit / "helpers.js").exists() else ""
    published, failed = [], {}
    # Sequential: a HyperFrames render holds a headless Chrome, and memory is tight.
    for cfg in write_configs(session, shots):
        build_slot(session, cfg, css, js)
        file, err = render(session, cfg)
        if file:
            publish(session, cfg, file)
            published.append(int(cfg["key"]))
        else:
            failed[int(cfg["key"])] = err
            log(f"[wordcard] shot {cfg['key']}: {err}")
    if failed:
        overflow(session, [s for s in shots if s["shot_number"] in failed], "word card failed")
    return {"published": published, "failed": failed, "queued": []}


def main() -> None:
    ap = argparse.ArgumentParser(description="Word-card graphics for shots stock can't fill")
    ap.add_argument("--session", required=True)
    ap.add_argument("--shots", required=True, help="comma-separated shot numbers")
    a = ap.parse_args()
    session = Path(a.session)
    want = {int(x) for x in a.shots.split(",") if x.strip()}
    plan = json.loads((session / "plan.json").read_text(encoding="utf-8"))
    print(json.dumps(make(session, [s for s in plan["shots"] if s["shot_number"] in want])))


if __name__ == "__main__":
    main()
