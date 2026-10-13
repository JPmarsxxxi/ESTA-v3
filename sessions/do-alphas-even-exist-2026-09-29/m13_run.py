"""The M13 Qwen run, unattended (SPEC.md Part 10): autopick every footage/image shot of the replanned plan in
chunks with vision.backend qwen, then render final and match final.

    python sessions/do-alphas-even-exist-2026-09-29/m13_run.py      # resumable: m13_state.json

Before each chunk the Qwen server must answer /health; when it doesn't (Kaggle stopped it, idle or 12 h cap)
the driver pushes it again. A chunk whose checks failed because the server died mid-chunk loses its candidate
cache and runs again. Text calls (query rewrites) still use Claude; a Claude limit only costs rewrites.
Progress lines go to stdout and to reports/m13-overnight-log.md.
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

S = Path(__file__).resolve().parent
ROOT = S.parents[1]
sys.path.insert(0, str(ROOT))
from tools.vision_server import client  # noqa: E402

STATE = S / "m13_state.json"
LOG = ROOT / "reports" / "m13-overnight-log.md"
CHUNK = 20


def log(msg: str) -> None:
    line = f"- {time.strftime('%H:%M')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def server_up() -> bool:
    h = client.health(20)
    if h and h.get("ready"):
        return True
    log(f"Qwen server not ready ({(h or {}).get('stage', 'unreachable')}); pushing it again")
    r = subprocess.run([sys.executable, "tools/vision_server/run.py", "up", "--wait", "80"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    log("server: " + (r.stdout.strip().splitlines() or ["?"])[-1])
    return r.returncode == 0


def main() -> None:
    if client.config()["backend"] != "qwen":
        sys.exit("set vision.backend: qwen in config.yaml first")
    plan = json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
    if not state:
        todo = [s["shot_number"] for s in plan if s["visual"]["type"] != "MOTION_GRAPHICS"]
        state = {"chunks": [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)], "done": [], "retries": {}}
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
        log(f"autopick: {len(todo)} shots in {len(state['chunks'])} chunks")
    for i, chunk in enumerate(state["chunks"]):
        if i in state["done"]:
            continue
        while True:
            if not server_up():
                log("STOP: the Qwen server would not come up")
                sys.exit(1)
            t0 = time.time()
            r = subprocess.run([sys.executable, "tools/match/autopick.py", "--session", str(S.relative_to(ROOT)),
                                "--shots", ",".join(map(str, chunk))], cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            result = next((json.loads(ln) for ln in reversed(r.stdout.splitlines()) if ln.startswith('{"ok"')), {})
            dead = "unreachable" in r.stdout + r.stderr or "not ready" in r.stdout + r.stderr or "failed calls" in result.get("lane", "")
            if r.returncode == 0 and result.get("ok") and not dead:
                break
            tries = state["retries"].get(str(i), 0) + 1
            state["retries"][str(i)] = tries
            STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
            log(f"chunk {i + 1} failed (exit {r.returncode}, lane '{result.get('lane', '')}'): "
                f"{(r.stderr or r.stdout)[-200:].strip()!r}; retry {tries}")
            for n in chunk:
                (S / "assets" / "candidates" / f"shot_{n}.json").unlink(missing_ok=True)
            if tries >= 3:
                log(f"STOP: chunk {i + 1} failed 3 times")
                sys.exit(1)
        graphics = re.search(r"(\d+) shots become word-card graphics", r.stdout)
        log(f"chunk {i + 1}/{len(state['chunks'])} (shots {chunk[0]}-{chunk[-1]}): picked {result.get('picked')}, "
            f"lane '{result.get('lane')}', {round((time.time() - t0) / 60, 1)} min"
            + (f", {graphics.group(1)} became graphics" if graphics else ""))
        state["done"].append(i)
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")

    rows = {}
    for line in (S / "assets_progress.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            x = json.loads(line)
            rows[str(x["shot_number"])] = x
    log("autopick done. picks by source: " + json.dumps(dict(Counter(x.get("source") for x in rows.values() if x.get("ok")))))
    sess = str(S.relative_to(ROOT))
    for name, argv in (("render", ["conda", "run", "--no-capture-output", "-n", "esta", "python", "tools/render/run.py",
                                   "build", "--session", sess]),
                       ("match final", [sys.executable, "tools/match/score.py", "--session", sess, "--stage", "final"])):
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log(f"{name}: exit {r.returncode} {r.stdout.strip().splitlines()[-1][:300] if r.stdout.strip() else r.stderr[-300:]}")


if __name__ == "__main__":
    main()
