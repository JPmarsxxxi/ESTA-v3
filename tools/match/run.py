"""The `match` pipeline step: profile the inspo, score, adjust until pass.

    python tools/match/run.py --session sessions/<id> --stage profile|plan|final

`profile` builds the inspo profiles only (runs before plan: the mapped plan cuts against them).

System python. Inspo shots are described and auto-pick candidates judged by Haiku (tools/match/describe.py);
nothing in the match path uses Kaggle.
"""

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match import adjust, inspo, score  # noqa: E402
from tools.match.common import REPO_ROOT, utf8_stdout  # noqa: E402

LOCK = REPO_ROOT / "cache" / "match.lock"


@contextlib.contextmanager
def run_lock(path: Path = LOCK, log=print, poll: float = 5.0):
    """One match run at a time: two at once ran the machine out of memory (SPEC.md Part 12, F13). An OS file
    lock, so a crashed run never leaves it held; a second run waits for it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    waited = False
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not waited:
                    log(f"another match run holds {path.name}; waiting for it to finish")
                    waited = True
                time.sleep(poll)
        yield
    finally:
        with contextlib.suppress(OSError):
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", required=True)
    ap.add_argument("--stage", required=True, choices=["profile", "plan", "final"])
    a = ap.parse_args()
    session = Path(a.session)
    log = lambda m: print(m, flush=True)  # noqa: E731
    try:
        with run_lock(log=log):
            stage(session, a.stage, log)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


def stage(session: Path, which: str, log) -> None:
    prof = inspo.profile(session, log=log)
    if not prof["profiles"]:
        raise RuntimeError("no inspo could be profiled: " + json.dumps(prof["failed"])[:300])
    if which == "profile":
        print(json.dumps({"ok": True, "profiles": prof["profiles"], "failed": prof["failed"]}))
        return
    rep = adjust.run(session, which)
    log(score.summary(rep))
    for r in rep["adjust"]["rounds"]:
        log(f"  round {r['round']}: {'kept' if r['kept'] else 'reverted'} {len(r['changes'])} changes {r.get('why', '')}")
    print(json.dumps({"ok": True, "overall": rep["overall"], "pass": rep["pass"],
                      "rounds": len(rep["adjust"]["rounds"]), "cost_usd": rep["adjust"]["cost_usd"]}))


if __name__ == "__main__":
    main()
