"""SPEC.md Part 12 F1-F3: adjust refetches only what a round changed, keeps the writer inside the sourcing
rules, and never proposes a split the validator would fail."""

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import adjust as A  # noqa: E402
from tools.match.common import DEFAULT_MATCH  # noqa: E402

WORDS = [{"word": f"w{i}", "start": 0.4 * i, "end": 0.4 * i + 0.3} for i in range(25)]  # 0-9.9 s


def session(tmp_path, cuts, targets, stale=()):
    edges = [0.0, *cuts, 10.0]
    shots = [{"shot_number": i + 1, "start": a, "end": b, "audio": "", "ref_shot": f"i{i}", "ref_target_dur": t,
              "idea": {"id": i + 1, "step": 1, "subject": f"subject {i}"},
              "visual": {"type": "REAL_FOOTAGE", "desc": f"desc {i}",
                         "search_sources": [{"source": "youtube", "queries": [f"q{i} a", f"q{i} b"]}],
                         **({"queries_stale": True} if i + 1 in stale else {})}}
             for i, ((a, b), t) in enumerate(zip(zip(edges, edges[1:]), targets))]
    (tmp_path / "plan.json").write_text(json.dumps({"shots": shots}))
    (tmp_path / "timestamps.json").write_text(json.dumps({"segments": [{"words": WORDS}]}))
    (tmp_path / "audio_metadata.json").write_text(json.dumps({"duration_seconds": 10.0}))
    return tmp_path


def fake_tools(monkeypatch, picked):
    monkeypatch.setattr("tools.match.autopick.run", lambda session, shots, log=None: picked.append(list(shots)) or {"picked": len(shots)})
    monkeypatch.setattr(A, "run_esta", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""))


def test_refresh_after_restore_rerenders_only(tmp_path, monkeypatch):
    s = session(tmp_path, [2.35, 4.35, 6.35, 8.35], [2.0] * 5, stale={1, 3, 5})
    picked = []
    fake_tools(monkeypatch, picked)
    notes = A.refresh_final(s)
    assert picked == [] and notes == ["re-rendered"]


def _final_round(tmp_path, monkeypatch, wording):
    s = session(tmp_path, [2.35, 4.35, 6.35, 8.35], [2.0] * 5, stale={1, 3})
    failing = {"stage": "final", "overall": 50.0, "pass": False,
               "sections": {k: {"pass": k != "c", "score": 50} for k in "abcde"}}
    better = {**failing, "overall": 60.0}
    scores = iter([failing, better])
    monkeypatch.setattr(A, "match_config", lambda: DEFAULT_MATCH | {"max_rounds": 1})
    monkeypatch.setattr(A.scorer, "score", lambda *a, **k: next(scores))
    monkeypatch.setattr(A.scorer, "report_path", lambda session, stage: session / f"match_{stage}.json")
    monkeypatch.setattr(A.scorer, "_asset_rows", lambda session: {str(n): {} for n in range(1, 6)})
    monkeypatch.setattr(A.scorer, "load_inspo", lambda session: {"shots": []})
    monkeypatch.setattr(A, "fix_theme", lambda session, rep, tasks: tasks.update({2: {"task": "retheme", "why": "x"}}) or ["rethemed shot 2"])
    monkeypatch.setattr("tools.match.common.Embedder", lambda: None)
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout=json.dumps({"result": json.dumps({"shots": [wording]}), "total_cost_usd": 0.001}), stderr=""))
    (s / "match_final.json").write_text(json.dumps(better))
    picked = []
    fake_tools(monkeypatch, picked)
    return s, A.run(s, "final"), picked


def test_kept_round_refetches_only_its_shots(tmp_path, monkeypatch):
    s, rep, picked = _final_round(tmp_path, monkeypatch, {
        "n": 2, "desc": "a new desc", "search_sources": [{"source": "youtube", "queries": ["new a", "new b"]}]})
    assert picked == [[2]]  # shots 1 and 3 still carry an old stale mark and are left alone
    assert rep["adjust"]["rounds"][0]["kept"]


def test_writer_giphy_off_a_reaction_is_dropped_not_reverted(tmp_path, monkeypatch):
    s, rep, _ = _final_round(tmp_path, monkeypatch, {
        "n": 2, "desc": "a man walking", "search_sources": [
            {"source": "giphy", "queries": ["man walking", "walk"]},
            {"source": "youtube", "queries": ["man walking street", "walking b roll"]},
            {"source": "pexels_video", "queries": ["man walking"]}]})
    shot = A.shot_by_n(A.load_plan(s), 2)
    assert [e["source"] for e in shot["visual"]["search_sources"]] == ["youtube"]
    assert rep["adjust"]["rounds"][0]["kept"]


def test_allowed_sources_keeps_giphy_on_a_reaction():
    shot = {"visual": {"desc": "Reaction: a shrug"}}
    assert [e["source"] for e in A.allowed_sources(shot, [{"source": "giphy"}, {"source": "pixabay_video"}])] == ["giphy"]


def e_report(mean_ours, med_ours, mean_inspo, med_inspo):
    return {"sections": {"e": {"mean": {"ours": mean_ours, "inspo": mean_inspo},
                               "median": {"ours": med_ours, "inspo": med_inspo}}}}


def test_split_that_would_fail_the_target_check_is_skipped(tmp_path):
    # Shot 2 is 6 s against a 3 s target: any split leaves halves near 3 s against a 1.5 s half-target.
    s = session(tmp_path, [1.95, 7.95], [2.0, 3.0, 2.0])
    changes = A.fix_duration(s, e_report(3.3, 2.0, 2.0, 2.0), {})
    assert not any(c.startswith("split") for c in changes)
    assert len(A.load_plan(s)["shots"]) == 3


def test_split_inside_the_target_check_goes_ahead(tmp_path):
    s = session(tmp_path, [1.95, 7.95], [2.0, 6.0, 2.0])
    changes = A.fix_duration(s, e_report(3.3, 2.0, 2.0, 2.0), {})
    assert any(c.startswith("split shot 2") for c in changes)
