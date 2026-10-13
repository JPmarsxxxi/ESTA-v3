"""Start the M13 Qwen run clean (SPEC.md Part 10): the asset feed and candidate cache are keyed by shot number,
so after the renumbered replan they would hand new shots the old shots' Claude-checked picks.

The pre-M13 files are in backup_m12_claude/ (and assets/candidates_m12/). Graphic shots that reuse an old
crimson card (visuals.txt `=N` on an old graphic) get that card's render under their new number.
"""
import json
import shutil
import subprocess
from pathlib import Path

S = Path(__file__).resolve().parent
ROOT = S.parents[1]
plan = json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]
old_mg = {s["key"]: s for s in json.loads((S / "backup_m12_claude" / "motion_graphics.json").read_text(encoding="utf-8"))["slots"]
          if s.get("ok") and s.get("flavor") != "overlay" and "-" not in s["key"]}
old_plan = {s["shot_number"]: s for s in json.loads((S / "backup_m12_claude" / "plan.json").read_text(encoding="utf-8"))["shots"]}

cand = S / "assets" / "candidates"
if cand.exists() and not (S / "assets" / "candidates_m12").exists():
    shutil.move(str(cand), str(S / "assets" / "candidates_m12"))
cand.mkdir(parents=True, exist_ok=True)


def duration(f: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


rows, slots, missing = [], [], []
for s in plan:
    if s["visual"]["type"] != "MOTION_GRAPHICS":
        continue
    match = next((k for k, o in old_plan.items() if str(k) in old_mg and o["visual"]["desc"] == s["visual"]["desc"]), None)
    if match is None:
        missing.append(s["shot_number"])
        continue
    f = old_mg[str(match)]["file"]
    dur = min(duration(ROOT / f), s["end"] - s["start"])
    rows.append({"shot_number": s["shot_number"], "ok": True, "source": "hyperframes", "asset_type": "video", "url": "",
                 "file": f, "search_query": "", "in_point": 0.0, "out_point": round(dur, 3), "error": "",
                 "visual_verdict": "match", "visual_confidence": 100, "m13_from_shot": match})
    slots.append({"key": str(s["shot_number"]), "flavor": "full", "ok": True, "file": f})
(S / "assets_progress.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
(S / "assets.json").write_text(json.dumps({"session_id": S.name, "shots_total": len(plan), "shots_fetched": len(rows),
                                           "shots_failed": 0, "shots": {str(r["shot_number"]): r for r in rows}}, indent=1),
                               encoding="utf-8")
(S / "motion_graphics.json").write_text(json.dumps({"slots": slots, "generated": len(slots), "fallbacks": [],
                                                    "note": "M13: renders reused from the pre-M13 shots"}, indent=1),
                                        encoding="utf-8")
(S / "autopick.json").write_text("{}", encoding="utf-8")
print(f"{len(rows)} graphic shots mapped to existing renders; without a render: {missing}")
