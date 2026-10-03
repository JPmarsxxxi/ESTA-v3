"""adjust.py with a mapped plan: split/merge keep refs and targets; a round that breaks the validator is reverted."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import adjust as A  # noqa: E402
from tools.match.common import DEFAULT_MATCH  # noqa: E402

WORDS = [{"word": f"w{i}", "start": 0.4 * i, "end": 0.4 * i + 0.3} for i in range(25)]  # 0-9.9 s


def session(tmp_path, cuts, targets):
    edges = [0.0, *cuts, 10.0]
    shots = [{"shot_number": i + 1, "start": a, "end": b, "audio": "", "ref_shot": f"i{i}", "ref_target_dur": t,
              "visual": {"type": "REAL_FOOTAGE", "desc": ""}}
             for i, ((a, b), t) in enumerate(zip(zip(edges, edges[1:]), targets))]
    (tmp_path / "plan.json").write_text(json.dumps({"shots": shots}))
    (tmp_path / "timestamps.json").write_text(json.dumps({"segments": [{"words": WORDS}]}))
    (tmp_path / "audio_metadata.json").write_text(json.dumps({"duration_seconds": 10.0}))
    return tmp_path


def e_report(mean_ours, med_ours, mean_inspo, med_inspo):
    return {"sections": {"e": {"mean": {"ours": mean_ours, "inspo": mean_inspo},
                               "median": {"ours": med_ours, "inspo": med_inspo}}}}


def test_split_halves_the_target(tmp_path):
    s = session(tmp_path, [1.95, 7.95], [2.0, 6.0, 2.0])
    changes = A.fix_duration(s, e_report(3.3, 2.0, 2.0, 2.0), {})
    assert any(c.startswith("split shot 2") for c in changes)
    shots = A.load_plan(s)["shots"]
    assert [x["ref_shot"] for x in shots] == ["i0", "i1", "i1", "i2"]
    assert [x["ref_target_dur"] for x in shots] == [2.0, 3.0, 3.0, 2.0]


def test_merge_sums_the_targets(tmp_path):
    s = session(tmp_path, [0.75, 1.55, 5.95], [0.8, 0.8, 4.0, 4.0])
    changes = A.fix_duration(s, e_report(2.5, 0.8, 4.0, 4.0), {})
    assert any(c.startswith("merged") for c in changes)
    shots = A.load_plan(s)["shots"]
    assert shots[0]["ref_shot"] == "i0" and shots[0]["ref_target_dur"] == 1.6


def test_round_breaking_the_validator_is_reverted(tmp_path, monkeypatch):
    s = session(tmp_path, [1.95, 3.95, 5.95, 7.95], [2.0] * 5)
    before = (s / "plan.json").read_text()
    failing = {"stage": "plan", "overall": 50, "pass": False, "sections": {k: {"pass": k != "e", "score": 50} for k in "abcde"}}

    def breaks(session, rep, tasks):
        plan = A.load_plan(session)
        plan["shots"][1]["end"] = 3.35  # opens a 0.6 s gap: a new validator problem
        A.save_plan(session, plan)
        return ["moved a cut"]

    monkeypatch.setattr(A, "match_config", lambda: DEFAULT_MATCH)
    monkeypatch.setattr(A.scorer, "score", lambda *a, **k: failing)
    monkeypatch.setattr(A.scorer, "report_path", lambda session, stage: session / f"match_{stage}.json")
    monkeypatch.setattr(A, "fix_duration", breaks)
    monkeypatch.setattr(A, "write_wording", lambda *a, **k: ([], 0.0))
    monkeypatch.setattr("tools.match.common.Embedder", lambda: None)
    (s / "match_plan.json").write_text(json.dumps(failing))
    rep = A.run(s, "plan")
    r = rep["adjust"]["rounds"][0]
    assert not r["kept"] and "plan validator" in r["why"]
    assert (s / "plan.json").read_text() == before


def test_new_kind_of_problem_counts_as_regression():
    before = ["shot 3: gap of 0.40 s before shot 4 (1-2 s)"]
    assert A.validator_regressed(before, ["shot 5: cut at 3.10 s falls inside the word 'x'"])
    assert not A.validator_regressed(before, ["shot 4: gap of 0.20 s before shot 5 (1-2 s)"])
    assert A.validator_regressed([], ["shot 1: has no ref_shot"])
