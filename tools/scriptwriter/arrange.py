"""Validate a found-audio arrangement against its pool.

Phase 4 of notes/smart-pipeline-and-found-audio.md. The arranger MODE of the
scriptwriter is Claude-native (clip selection + sequencing happens in
conversation), so there is no generator here — this is the checker that keeps
the authored arrangement.json honest and gives audio:assemble (Phase 5) a clean,
pre-validated input. It confirms every arrangement clip references a real,
downloaded pool clip and has a sane in/out window.

    python tools/scriptwriter/arrange.py validate --session sessions/<id>
"""

import argparse
import json
import sys
from pathlib import Path


def validate_arrangement(session_dir: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    arr_path = session_dir / "arrangement.json"
    pool_path = session_dir / "audio_pool.json"
    if not arr_path.exists():
        return False, ["arrangement.json missing — run the scriptwriter arranger first"]
    if not pool_path.exists():
        return False, ["audio_pool.json missing — run audio found-fetch first"]

    try:
        arr = json.loads(arr_path.read_text(encoding="utf-8"))
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"unreadable JSON: {e}"]

    pool_by_id = {f"{c.get('source')}:{c.get('id')}": c for c in pool.get("clips", [])}
    clips = arr.get("clips", [])
    if not clips:
        errors.append("arrangement has no clips")

    seen_order: set = set()
    for i, c in enumerate(clips):
        tag = c.get("pool_id") or f"<clip #{i}>"
        pid = c.get("pool_id")
        if pid not in pool_by_id:
            errors.append(f"{tag}: pool_id not found in audio_pool.json")
        else:
            f = c.get("file") or pool_by_id[pid].get("file", "")
            if not f or not Path(f).exists():
                errors.append(f"{tag}: source media not downloaded ({f or 'no file'})")
        ip, op = c.get("in_point", 0), c.get("out_point", 0)
        if op <= ip:
            errors.append(f"{tag}: out_point ({op}) must be > in_point ({ip})")
        o = c.get("order")
        if o is not None:
            if o in seen_order:
                errors.append(f"{tag}: duplicate order {o}")
            seen_order.add(o)

    return len(errors) == 0, errors


def main() -> None:
    ap = argparse.ArgumentParser(description="ESTA found-audio arrangement validator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="Validate arrangement.json against audio_pool.json")
    v.add_argument("--session", required=True, help="Path to session dir")
    args = ap.parse_args()

    ok, errors = validate_arrangement(Path(args.session))
    print("VALID" if ok else "INVALID")
    for e in errors:
        print(f"  - {e}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
