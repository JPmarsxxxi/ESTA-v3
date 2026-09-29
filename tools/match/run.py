"""The `match` pipeline step: profile the inspo, score, adjust until pass.

    python tools/match/run.py --session sessions/<id> --stage plan|final

System python. Tagging and auto-pick judging go to Kaggle (tools/match/vlm_kaggle.py).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match import adjust, inspo, score  # noqa: E402
from tools.match.common import utf8_stdout  # noqa: E402


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--session", required=True)
    ap.add_argument("--stage", required=True, choices=["plan", "final"])
    a = ap.parse_args()
    session = Path(a.session)
    log = lambda m: print(m, flush=True)  # noqa: E731
    try:
        prof = inspo.profile(session, log=log)
        if not prof["profiles"]:
            raise RuntimeError("no inspo could be profiled: " + json.dumps(prof["failed"])[:300])
        rep = adjust.run(session, a.stage)
        log(score.summary(rep))
        for r in rep["adjust"]["rounds"]:
            log(f"  round {r['round']}: {'kept' if r['kept'] else 'reverted'} {len(r['changes'])} changes {r.get('why', '')}")
        print(json.dumps({"ok": True, "overall": rep["overall"], "pass": rep["pass"],
                          "rounds": len(rep["adjust"]["rounds"]), "cost_usd": rep["adjust"]["cost_usd"]}))
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
