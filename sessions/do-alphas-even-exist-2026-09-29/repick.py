"""Re-pick every footage/image shot whose pick is not YouTube, after apply_sourcing.py (SPEC.md Part 9).

    python sessions/do-alphas-even-exist-2026-09-29/repick.py      # resumable: repick_state.json

Chunks of 20 run one at a time. The run stops itself when a chunk's judge calls failed or a shot was retyped to
a graphic: both mean the Claude usage limit (or claude itself) failed mid-run, and continuing would quietly
fill shots with whatever survived. Re-run to resume from the stopped chunk.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

S = Path(__file__).resolve().parent
ROOT = S.parents[1]
STATE = S / "repick_state.json"
CHUNK = 20


def picks() -> dict:
    out = {}
    for line in (S / "assets_progress.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("ok"):
                out[str(r["shot_number"])] = r
    return out


state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
if not state:
    plan = json.loads((S / "plan.json").read_text(encoding="utf-8"))
    have = picks()
    todo = [s["shot_number"] for s in plan["shots"] if s["visual"]["type"] != "MOTION_GRAPHICS"
            and (have.get(str(s["shot_number"])) or {}).get("source") != "youtube"]
    state = {"chunks": [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)], "done": []}
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(f"[repick] {len(todo)} shots in {len(state['chunks'])} chunks", flush=True)

for i, chunk in enumerate(state["chunks"]):
    if i in state["done"]:
        continue
    print(f"[repick] chunk {i + 1}/{len(state['chunks'])}: shots {chunk[0]}-{chunk[-1]}", flush=True)
    r = subprocess.run([sys.executable, "tools/match/autopick.py", "--session", str(S.relative_to(ROOT)),
                        "--shots", ",".join(map(str, chunk))], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [ln for ln in r.stdout.splitlines() if ln.startswith("{") or "judge" in ln or "retyp" in ln]
    print("\n".join(tail[-4:]), flush=True)
    result = next((json.loads(ln) for ln in reversed(r.stdout.splitlines()) if ln.startswith('{"ok"')), {})
    lane = result.get("lane", "")
    if r.returncode or not result.get("ok"):
        sys.exit(f"[repick] STOP: chunk {i + 1} failed (exit {r.returncode}): {r.stderr[-300:]}")
    if "failed calls" in lane or "unavailable" in r.stdout or re.search(r"\b[1-9][0-9]* become graphics", r.stdout):
        # Its candidates were gathered while the YouTube finder's Claude calls were failing too: regather on resume.
        for n in chunk:
            (S / "assets" / "candidates" / f"shot_{n}.json").unlink(missing_ok=True)
        sys.exit(f"[repick] STOP after chunk {i + 1}: '{lane}' - claude calls failing (usage limit?); re-run to resume")
    state["done"].append(i)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")

have = picks()
from collections import Counter  # noqa: E402
print("[repick] done. picks by source:", dict(Counter(r.get("source") for r in have.values())), flush=True)
