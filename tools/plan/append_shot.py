"""Stream plan shots to plan_progress.jsonl and assemble plan.json from it (SPEC.md Part 8).

    python tools/plan/append_shot.py append --session sessions/<id> [--replace]  < shots
    python tools/plan/append_shot.py build  --session sessions/<id>              < header

`append` reads one shot object, a JSON array of shots, or JSONL from stdin and appends
one line per shot. It replaces the plan skill's "rewrite the whole file after every
shot", whose output grew with the square of the shot count. A shot number already in
the file is refused unless --replace, which rewrites that line in place.

`build` reads plan.json's top-level fields (everything but `shots`) from stdin and
writes plan.json with the shots from plan_progress.jsonl in shot order, so the plan is
not typed out a second time.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_shots(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        shots = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        shots = [json.loads(line) for line in text.splitlines() if line.strip()]
    for s in shots:
        if not isinstance(s, dict) or not isinstance(s.get("shot_number"), int) or not isinstance(s.get("visual"), dict):
            raise ValueError(f"not a shot (needs int shot_number and a visual object): {json.dumps(s)[:120]}")
    return shots


def read_progress(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(session: Path, shots: list[dict], replace: bool) -> str:
    path = session / "plan_progress.jsonl"
    have = read_progress(path)
    numbers = {s["shot_number"] for s in have}
    dup = [s["shot_number"] for s in shots if s["shot_number"] in numbers]
    if dup and not replace:
        raise ValueError(f"shot(s) {dup} already in {path.name}; pass --replace to rewrite them")
    if dup:
        new = {s["shot_number"]: s for s in shots}
        rows = [new.pop(s["shot_number"], s) for s in have] + list(new.values())
        path.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in rows), encoding="utf-8")
    else:
        with open(path, "a", encoding="utf-8") as fh:
            for s in shots:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    return f"{len(shots)} shot(s) -> {path.name} ({len(numbers | {s['shot_number'] for s in shots})} total)"


def build(session: Path, header: dict) -> str:
    shots = sorted(read_progress(session / "plan_progress.jsonl"), key=lambda s: s["shot_number"])
    if not shots:
        raise ValueError("plan_progress.jsonl has no shots")
    plan = {k: v for k, v in header.items() if k != "shots"}
    plan.setdefault("session_id", session.name)
    meta = plan.setdefault("video_metadata", {})
    meta["shot_count"] = len(shots)
    plan["shots"] = shots
    plan.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    (session / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"plan.json: {len(shots)} shots"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["append", "build"])
    ap.add_argument("--session", required=True)
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    session = Path(a.session)
    text = sys.stdin.read()
    try:
        if a.mode == "append":
            print(append(session, parse_shots(text), a.replace))
        else:
            print(build(session, json.loads(text) if text.strip() else {}))
    except (ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
