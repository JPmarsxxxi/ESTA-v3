"""validate_plan.check on crafted plans: each hard rule, section scoping, frozen and locked shots."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import validate_plan as V  # noqa: E402

# 25 words of 0.3 s with 0.1 s gaps: boundaries at 0.35, 0.75, ..., 9.55; voice ends at 10.0.
WORDS = [{"word": f"w{i}", "start": 0.4 * i, "end": 0.4 * i + 0.3} for i in range(25)]
END = 10.0


def plan(cuts, target=2.0, **extra):
    edges = [0.0, *cuts, END]
    return [{"shot_number": i + 1, "start": a, "end": b, "ref_shot": f"i{i}", "ref_target_dur": target, **extra}
            for i, (a, b) in enumerate(zip(edges, edges[1:]))]


def problems(r):
    return [p for f in r["failures"] for p in f["problems"]]


def test_good_plan_passes():
    r = V.check(plan([1.95, 3.95, 5.95, 7.95]), WORDS, END)
    assert r["pass"] and r["frozen"] == [1, 2, 3, 4, 5]


def test_uncovered_tail():
    p = plan([1.95, 3.95, 5.95])
    p[-1]["end"] = 7.95
    r = V.check(p, WORDS, END)
    assert not r["pass"] and any("2.0 s uncovered" in x for x in problems(r))


def test_late_start():
    p = plan([1.95, 3.95, 5.95, 7.95])
    p[0]["start"] = 0.5
    assert any("starts at 0.50 s" in x for x in problems(V.check(p, WORDS, END)))


def test_gap_and_overlap():
    p = plan([1.95, 3.95, 5.95, 7.95])
    p[1]["end"] = 3.55  # gap 3.55-3.95
    p[3]["end"] = 8.35  # overlaps shot 5 (starts 7.95)
    probs = problems(V.check(p, WORDS, END))
    assert any("gap of 0.40 s" in x for x in probs) and any("overlaps shot 5" in x for x in probs)


def test_cut_inside_word():
    r = V.check(plan([1.95, 4.15, 5.95, 7.95]), WORDS, END)  # 4.15 is inside w10 (4.0-4.3)
    assert any("inside the word 'w10'" in x for x in problems(r))


def test_far_from_target_and_exemption():
    # Shot 1 is 4 s against a 2 s target while 1.95 was available: fails.
    r = V.check(plan([3.95, 5.95, 7.95]), WORDS, END)
    assert any("shot 1: is 3.95 s against a 2.00 s target" in x for x in problems(r))
    # Words 3 s long leave no closer boundary: the same miss is exempt.
    long = [{"word": f"w{i}", "start": 3.0 * i, "end": 3.0 * i + 2.9} for i in range(4)]
    edges = [0.0, 2.95, 5.95, 8.95, 12.0]
    p = [{"shot_number": i + 1, "start": a, "end": b, "ref_shot": "i", "ref_target_dur": 1.0} for i, (a, b) in enumerate(zip(edges, edges[1:]))]
    assert V.check(p, long, 12.0)["pass"]


def test_missing_ref_shot():
    p = plan([1.95, 3.95, 5.95, 7.95])
    del p[2]["ref_shot"]
    assert any("shot 3: has no ref_shot" in x for x in problems(V.check(p, WORDS, END)))


def test_sections_scoped_and_frozen():
    p = plan([1.95, 3.95, 5.95, 7.95])
    p[3]["end"] = 7.55  # gap after shot 4
    r = V.check(p, WORDS, END)
    assert [f["section"] for f in r["failures"]] == [[3, 5]]
    assert r["frozen"] == [1, 2]


def test_locked_reported_not_frozen():
    p = plan([1.95, 3.95, 5.95, 7.95])
    p[3]["end"] = 7.55
    p[3]["locked"] = True
    f = V.check(p, WORDS, END)["failures"][0]
    assert f["locked"] == [4]


def test_stretched_last_shot_fails():
    # Covering the tail by stretching the last shot to 4 s against a 2 s target, with 7.95 available, is caught.
    r = V.check(plan([1.95, 3.95, 5.95]), WORDS, END)
    assert any("shot 4: is 4.05 s against a 2.00 s target" in x for x in problems(r))


def test_last_shot_merge_allowance():
    # slots.py merges a short tail stub into the last slot: up to 1.75x its target passes.
    p = plan([1.95, 3.95, 6.75])
    p[2]["ref_target_dur"] = 2.8
    assert V.check(p, WORDS, END)["pass"]  # last shot 3.25 s = 1.63x its 2 s target


def test_stock_source_fails_naming_the_shot():
    p = plan([1.95, 3.95, 5.95, 7.95])
    p[2]["visual"] = {"search_sources": [{"source": "youtube", "queries": ["q"]}, {"source": "pexels_video", "queries": ["q"]}]}
    r = V.check(p, WORDS, END)
    assert not r["pass"] and problems(r) == ["shot 3: routes to stock (pexels_video)"]
