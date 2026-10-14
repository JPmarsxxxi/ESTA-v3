"""Fit a stitched voiceover toward a target length: scale every line's pace and shrink pauses, then re-stitch.

    python D:/esta-perf/m14t/fit.py <session-id> <current_seconds> [target=60]
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("C:/Users/User/ESTA-v3")
sid, cur = sys.argv[1], float(sys.argv[2])
target = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
vs = ROOT / "sessions" / sid / "voice_script.json"
job = json.loads(vs.read_text(encoding="utf-8"))
lines = job["lines"] if isinstance(job, dict) else job
pause_total = sum(int(l.get("pause_after_ms") or 0) for l in lines) / 1000
# pauses shrink to 60% first; the rest of the gap is taken by tempo, capped at 1.15 so the clone still sounds human
speech = cur - pause_total
want_speech = target - pause_total * 0.6
f = min(1.15, max(1.0, speech / max(1.0, want_speech)))
for l in lines:
    l["pace"] = round((l.get("pace") or 1.0) * f, 3)
    if l.get("pause_after_ms"):
        l["pause_after_ms"] = int(l["pause_after_ms"] * 0.6)
vs.write_text(json.dumps(job, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"tempo x{f:.3f}, pauses x0.6 (were {pause_total:.1f}s)")
r = subprocess.run(["conda", "run", "--no-capture-output", "-n", "esta", "python", "tools/audio/run.py", "stitch",
                    "--session", f"sessions/{sid}"], cwd=ROOT, capture_output=True, text=True)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-400:])
