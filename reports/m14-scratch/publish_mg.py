"""Append every rendered full-frame MG slot of a session to its assets feed (last line wins in render's merge)
and write motion_graphics.json.   python publish_mg.py <session-id>"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("C:/Users/User/ESTA-v3")
S = ROOT / "sessions" / sys.argv[1]
plan = {s["shot_number"]: s for s in json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]}
slots = []
with open(S / "assets_progress.jsonl", "a", encoding="utf-8") as fh:
    for n, s in sorted(plan.items()):
        if s["visual"]["type"] != "MOTION_GRAPHICS":
            continue
        f = S / "assets" / "source_pool" / f"mg_{n}.mp4"
        rel = f"sessions/{S.name}/assets/source_pool/mg_{n}.mp4"
        if not f.exists():
            slots.append({"key": str(n), "flavor": "full_frame", "ok": False, "error": "not rendered"})
            continue
        fh.write(json.dumps({"shot_number": n, "ok": True, "source": "hyperframes", "asset_type": "video", "url": "", "file": rel,
                             "search_query": "", "in_point": 0.0, "out_point": round(s["end"] - s["start"], 3), "error": "",
                             "visual_verdict": "match", "visual_confidence": 100}) + "\n")
        slots.append({"key": str(n), "flavor": "full_frame", "ok": True, "file": rel})
ok = sum(x["ok"] for x in slots)
(S / "motion_graphics.json").write_text(json.dumps({"slots": slots, "generated": ok, "fallbacks": len(slots) - ok,
                                                    "generated_at": datetime.now(timezone.utc).isoformat()}, indent=1), encoding="utf-8")
print(f"{S.name}: published {ok}/{len(slots)} MG slots")
