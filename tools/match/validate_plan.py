"""Hard checks on a mapped plan, scoped to the sections that fail (SPEC.md Part 3, M6.2, decision 6).

    python tools/match/validate_plan.py --session sessions/<id>     # -> plan_validation.json, exit 1 on failure

Checks: the shots cover the voiceover from 0 to its end, no gap or overlap over 0.1 s, every cut on a word
boundary, every shot within 35 % of its ref target (unless no boundary lies closer), every shot carrying a
ref_shot. Failing shots are grouped into sections with one shot of context each side; each section says
what to change. Every other shot is frozen: the plan skill rewrites only the failing sections.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import read_json, utf8_stdout, write_json  # noqa: E402
from tools.match.slots import boundaries, load_words, voice_end  # noqa: E402

TOL = 0.1          # gap / overlap / coverage, seconds
WORD_TOL = 0.05    # a cut this close to a word edge counts as on it
TARGET_TOL = 0.35  # share of ref_target_dur a shot may differ by


def _span(s: dict) -> tuple[float, float]:
    a = float(s.get("start", s.get("start_est", 0)) or 0)
    return a, float(s.get("end", s.get("end_est", a)) or a)


def inside_word(t: float, words: list[dict]) -> dict | None:
    """The word a cut falls inside, or None when it sits in a gap or within WORD_TOL of a word edge."""
    for w in words:
        if w["start"] + WORD_TOL < t < w["end"] - WORD_TOL:
            return w
    return None


def _word_before(t: float, words: list[dict]) -> str:
    prev = [w for w in words if w["end"] <= t + WORD_TOL]
    return prev[-1]["word"].strip(" ,.!?\"'") if prev else ""


def check(shots: list[dict], words: list[dict], end: float) -> dict:
    cuts = boundaries(words)
    problems: dict[int, list[str]] = {}
    fixes: dict[int, list[str]] = {}

    def flag(i, problem, fix=""):
        problems.setdefault(i, []).append(f"shot {shots[i]['shot_number']}: {problem}")
        if fix:
            fixes.setdefault(i, []).append(fix)

    if not shots:
        return {"pass": False, "failures": [{"section": [], "start": 0, "end": end, "problems": ["the plan has no shots"],
                                             "fix": "write the plan from slots.json", "locked": []}], "frozen": []}
    a0, _ = _span(shots[0])
    if a0 > TOL:
        flag(0, f"starts at {a0:.2f} s, not 0", "start the first shot at 0")
    _, z = _span(shots[-1])
    if abs(z - end) > TOL:
        what = f"the voice runs to {end:.2f} s: {end - z:.1f} s uncovered" if z < end else f"past the voice end {end:.2f} s"
        flag(len(shots) - 1, f"ends at {z:.2f} s, {what}",
             f"extend the last shots to {end:.2f} s, cutting on word boundaries at the ref targets")
    for i, s in enumerate(shots):
        a, b = _span(s)
        if i + 1 < len(shots):
            na, _ = _span(shots[i + 1])
            if na - b > TOL:
                flag(i, f"gap of {na - b:.2f} s before shot {shots[i + 1]['shot_number']} ({b:.2f}-{na:.2f} s)",
                     f"end shot {s['shot_number']} at {na:.2f} s")
            elif b - na > TOL:
                flag(i, f"overlaps shot {shots[i + 1]['shot_number']} by {b - na:.2f} s",
                     f"end shot {s['shot_number']} at {na:.2f} s")
            w = inside_word(b, words)
            if w:
                near = min(cuts, key=lambda c: abs(c - b)) if cuts else b
                flag(i, f"cut at {b:.2f} s falls inside the word '{w['word']}'",
                     f"cut shot {s['shot_number']} at {near:.2f} s, after '{_word_before(near, words)}'")
        if not s.get("ref_shot"):
            flag(i, "has no ref_shot", "map it to the slot's ref_shot (or one of its alts)")
        target = s.get("ref_target_dur")
        if target and i + 1 < len(shots):
            dur = b - a
            want = a + float(target)
            near = min((c for c in cuts if c > a + WORD_TOL), key=lambda c: abs(c - want), default=b)
            if abs(dur - target) > TARGET_TOL * target and abs(near - b) > 0.01:
                flag(i, f"is {dur:.2f} s against a {float(target):.2f} s target",
                     f"cut shot {s['shot_number']} at {near:.2f} s, after '{_word_before(near, words)}'")

    failing = sorted(problems)
    runs: list[list[int]] = []
    for i in failing:
        lo, hi = max(0, i - 1), min(len(shots) - 1, i + 1)
        if runs and lo <= runs[-1][1] + 1:
            runs[-1][1] = max(runs[-1][1], hi)
        else:
            runs.append([lo, hi])
    failures, in_section = [], set()
    for lo, hi in runs:
        idx = range(lo, hi + 1)
        in_section.update(idx)
        failures.append({
            "section": [shots[lo]["shot_number"], shots[hi]["shot_number"]],
            "start": round(_span(shots[lo])[0], 3), "end": round(_span(shots[hi])[1], 3),
            "problems": [p for i in idx for p in problems.get(i, [])],
            "fix": "; ".join(f for i in idx for f in fixes.get(i, [])),
            # Hand-edited shots are never rewritten by the plan skill or adjust: the user fixes them.
            "locked": [shots[i]["shot_number"] for i in idx if shots[i].get("locked") and i in problems],
        })
    return {"pass": not failures, "failures": failures,
            "frozen": [s["shot_number"] for i, s in enumerate(shots) if i not in in_section]}


def validate(session: Path) -> dict:
    words = load_words(read_json(session / "timestamps.json", {}) or {})
    if not words:
        raise RuntimeError("no timestamps.json words: the validator needs real word timing")
    shots = (read_json(session / "plan.json", {}) or {}).get("shots", [])
    end = voice_end(session, words)
    out = {"session": session.name, "voice_end": end, "shots": len(shots), **check(shots, words, end)}
    write_json(session / "plan_validation.json", out)
    return out


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Validate a mapped plan")
    ap.add_argument("--session", required=True)
    try:
        out = validate(Path(ap.parse_args().session))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(2)
    print(json.dumps({"ok": True, "pass": out["pass"], "failing_sections": len(out["failures"]),
                      "frozen": len(out["frozen"]), "shots": out["shots"]}))
    for f in out["failures"][:10]:
        more = f" | and {len(f['problems']) - 6} more" if len(f["problems"]) > 6 else ""
        print(f"shots {f['section'][0]}-{f['section'][1]} ({f['start']}-{f['end']} s): " + " | ".join(f["problems"][:6]) + more)
    sys.exit(0 if out["pass"] else 1)


if __name__ == "__main__":
    main()
