"""Hard checks on a mapped plan, scoped to the sections that fail (SPEC.md Part 3, M6.2, decision 6).

    python tools/match/validate_plan.py --session sessions/<id>     # -> plan_validation.json, exit 1 on failure

Checks: the shots cover the voiceover from 0 to its end, no gap or overlap over 0.1 s, every cut on a word
boundary, every shot within 35 % of its ref target (unless no boundary lies closer), every shot carrying a
ref_shot, no shot routed to a stock source (SPEC.md Part 7), the sourcing rules (SPEC.md Part 9), and the
idea rules (SPEC.md Part 10): no cut inside a name or number, every footage/image shot carrying its idea, and
no subject repeated across neighbouring shots. Failing shots are grouped into sections with one shot of context each side; each section says
what to change. Every other shot is frozen: the plan skill rewrites only the failing sections.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.assets.run import STOCK_SOURCES  # noqa: E402
from tools.match.common import read_json, utf8_stdout, write_json  # noqa: E402
from tools.match.slots import LAST_MERGE, boundaries, load_words, voice_end  # noqa: E402

TOL = 0.1          # gap / overlap / coverage, seconds
WORD_TOL = 0.05    # a cut this close to a word edge counts as on it
TARGET_TOL = 0.35  # share of ref_target_dur a shot may differ by
REACTION = ("meme", "reaction", "this is fine", "shrug", "facepalm")  # the plan skill's meme-override cues
UNITS = {"%", "percent", "per", "bps", "x", "k", "million", "billion", "trillion"}
STOP = {"the", "and", "with", "from", "into", "onto", "over", "that", "this", "his", "her", "their", "its", "at",
        "of", "in", "on", "a", "an", "to", "for", "shot", "close", "wide", "medium", "photo", "up"}
REPEAT_JACCARD = 0.5


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


def sourcing_problems(s: dict) -> list[tuple[str, str]]:
    """The plan skill's sourcing rules (query ladder, per-source queries, Giphy for reactions only), enforced
    because a plan that skipped them sent 206 of 307 footage shots to Giphy (SPEC.md Part 9)."""
    v = s.get("visual") or {}
    if v.get("type") == "MOTION_GRAPHICS":
        return []
    entries = v.get("search_sources") or []
    if not entries:
        return []  # assets falls back to the type's default sources
    out = []
    n = s["shot_number"]
    if len(entries[0].get("queries") or []) < 2:
        out.append((f"lead source {entries[0].get('source')} has no query ladder",
                    f"give shot {n}'s {entries[0].get('source')} 2-3 queries, most specific first"))
    queries = {q for e in entries for q in e.get("queries") or []}
    if len(entries) > 1 and len(queries) == 1:
        out.append(("every source has the same single query",
                    f"write queries for each of shot {n}'s sources in that source's own terms"))
    if any(e.get("source") == "giphy" for e in entries) and not any(m in (v.get("desc") or "").lower() for m in REACTION):
        out.append(("routes to giphy but is not a reaction or meme beat",
                    f"drop giphy from shot {n}, or mark its desc as a reaction/meme if that is what it is"))
    return out


def _bare(w: dict | None) -> str:
    return (w or {}).get("word", "").strip(" \"'")


def _numeric(s: str) -> bool:
    return bool(re.fullmatch(r"[$£€]?\.?\d[\d.,]*%?", s.rstrip(".,!?;:")))


def protected_cut(t: float, words: list[dict]) -> str:
    """Why a cut at t splits a name or a number ("" when it doesn't): two capitalised words, or a number
    followed by a number or unit, with no punctuation between them (SPEC.md Part 10, decision 8)."""
    before = next((w for w in reversed(words) if w["end"] <= t + WORD_TOL), None)
    after = next((w for w in words if w["start"] >= t - WORD_TOL), None)
    a, b = _bare(before), _bare(after)
    if not a or not b or a[-1] in ".,!?;:":
        return ""
    if a[0].isupper() and b[0].isupper() and a.rstrip(".,!?").isalpha() and "I" not in (a, b.rstrip(".,!?;:'")):
        return f"splits the name '{a} {b.rstrip('.,!?;:')}'"
    if (_numeric(a) or a[0].isupper()) and (_numeric(b) or b.lower().rstrip(".,!?;:") in UNITS) and (_numeric(a) or _numeric(b)):
        return f"splits the number '{a} {b.rstrip(',!?;:')}'"
    return ""


def _content(desc: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (desc or "").lower()) if len(w) > 2 and w not in STOP}


def idea_problems(shots: list[dict], i: int) -> list[tuple[str, str]]:
    """Ideas before cuts (SPEC.md Part 10): every footage/image shot names its idea and subject, a subject is
    not repeated by the next idea, and an idea spanning shots moves on instead of repeating itself."""
    s = shots[i]
    v = s.get("visual") or {}
    if not v or v.get("type") == "MOTION_GRAPHICS":
        return []
    n, idea = s["shot_number"], s.get("idea") or {}
    if not idea.get("id") or not idea.get("subject"):
        return [("has no idea {id, step, subject}", f"give shot {n} the idea its words belong to and that idea's subject")]
    if i == 0:
        return []
    p = shots[i - 1]
    pv, pidea = p.get("visual") or {}, p.get("idea") or {}
    if not pv or pv.get("type") == "MOTION_GRAPHICS" or not pidea.get("id"):
        return []
    if pidea["id"] != idea["id"]:
        if str(pidea.get("subject", "")).strip().lower() == str(idea["subject"]).strip().lower():
            return [(f"shows '{idea['subject']}' again right after shot {p['shot_number']} (a different idea)",
                     f"give shot {n} its own idea's subject, or move the cut so one idea holds both")]
        return []
    a, b = _content(pv.get("desc", "")), _content(v.get("desc", ""))
    if a and b and len(a & b) / len(a | b) >= REPEAT_JACCARD:
        return [(f"repeats shot {p['shot_number']} instead of moving its idea on",
                 f"show the next angle or step of the idea in shot {n} (a different framing, moment or detail)")]
    return []


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
            elif why := protected_cut(b, words):
                flag(i, f"cut at {b:.2f} s {why}", f"move shot {s['shot_number']}'s cut to the nearest boundary outside it")
        if not s.get("ref_shot"):
            flag(i, "has no ref_shot", "map it to the slot's ref_shot (or one of its alts)")
        stock = [e.get("source") for e in (s.get("visual") or {}).get("search_sources") or [] if e.get("source") in STOCK_SOURCES]
        if stock:
            flag(i, f"routes to stock ({', '.join(stock)})",
                 f"replace {', '.join(stock)} in shot {s['shot_number']} with the non-stock sources for its type")
        for problem, fix in sourcing_problems(s) + idea_problems(shots, i):
            flag(i, problem, fix)
        target = s.get("ref_target_dur")
        if target:
            dur = b - a
            want = a + float(target)
            near = min((c for c in cuts if c > a + WORD_TOL), key=lambda c: abs(c - want), default=b)
            # The last shot may also hold the stub slots.py merges into it at the voice end.
            tol = TARGET_TOL + (LAST_MERGE if i + 1 == len(shots) else 0)
            if abs(dur - target) > tol * target and abs(near - b) > 0.01:
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
