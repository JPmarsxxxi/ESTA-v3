"""Unit tests for M5.1 bake-off tooling — pure Python, synthetic data, no GPU.

Scoring lives in scoring.py, used by `kaggle.py apply`; the Kaggle kernel only
records raw predictions, so everything scored here is what the report shows."""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match.bakeoff import kaggle, scoring  # noqa: E402
from tools.match.bakeoff.common import slug_for  # noqa: E402
from tools.match.bakeoff.extract import _frange  # noqa: E402
from tools.match.bakeoff.report import _table  # noqa: E402
from tools.match.bakeoff.scoring import f1_cuts  # noqa: E402


def test_f1_cuts_perfect_match():
    gt = [1.0, 2.5, 4.0]
    assert f1_cuts(gt, gt) == 1.0


def test_f1_cuts_within_tolerance_still_matches():
    gt = [1.0, 2.5, 4.0]
    pred = [1.05, 2.45, 4.02]
    assert f1_cuts(pred, gt) == 1.0


def test_f1_cuts_outside_tolerance_misses():
    gt = [1.0]
    pred = [1.5]
    assert f1_cuts(pred, gt) == 0.0


def test_f1_cuts_empty_gt_and_pred_scores_zero_not_crash():
    assert f1_cuts([], []) == 0.0


def test_f1_cuts_extra_false_positive_lowers_precision():
    gt = [1.0, 2.0]
    pred = [1.0, 2.0, 3.0]
    f1 = f1_cuts(pred, gt)
    assert 0.0 < f1 < 1.0


def test_f1_cuts_never_double_matches_one_gt_to_two_preds():
    # Two predictions both land within tolerance of the same single gt cut —
    # only one may count as a true positive.
    gt = [1.0]
    pred = [1.02, 1.04]
    assert f1_cuts(pred, gt) == 2 / 3  # tp=1, fp=1, fn=0 -> P=.5 R=1 F1=2/3


def test_kind_folds_seven_labels_into_five():
    assert [scoring.kind5(k) for k in ("screen", "ai", "footage", "still", "graphic", "talking_head", "meme")] == \
        ["footage", "footage", "footage", "still", "graphic", "talking_head", "meme"]


def test_always_guessing_the_majority_is_not_rewarded():
    # 9 of 10 shots are single-panel: guessing 1 every time is 90% accurate but
    # only 50% balanced accuracy, below the bar.
    pairs = [(1, 1)] * 9 + [(1, 2)]
    sc = scoring.score_field(pairs)
    assert sc["accuracy"] == 0.9 and sc["baseline"] == 0.9
    assert sc["balanced_accuracy"] == 0.5
    assert sc["testable"]


def test_a_field_with_one_value_in_the_key_is_untestable():
    sc = scoring.score_field([(1, 1)] * 10)
    assert sc["accuracy"] == 1.0
    assert not sc["testable"]
    assert kaggle._tag_score("panels", sc) == 0.0


def test_unparsed_answers_count_as_wrong():
    gt = {"v": {"shots": [{"shot_id": "1", "kind": "still", "text_on_screen": True, "panels": 1, "overlay": False, "clips_in_shot": 1},
                          {"shot_id": "2", "kind": "footage", "text_on_screen": False, "panels": 2, "overlay": True, "clips_in_shot": 1}]}}
    preds = {"v/1": {"kind": "still", "text_on_screen": True, "panels": 1, "overlay": False, "clips_in_shot": 1}}
    out = scoring.score_tags(preds, gt)
    assert out["unparsed"] == 1
    assert out["fields"]["kind"]["accuracy"] == 0.5
    assert out["fields"]["text_on_screen"]["balanced_accuracy"] == 0.5


def test_auc_separates_and_ties_count_half():
    assert scoring.auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert scoring.auc([0.5], [0.5]) == 0.5
    assert scoring.auc([0.1], [0.9]) == 0.0


def test_score_end_to_end_on_synthetic_run():
    gt = {"v": {"cuts": [0.0, 1.0, 2.0, 3.0], "duration": 3.0,
                "shots": [{"shot_id": str(i), "kind": k, "text_on_screen": t, "panels": 1, "overlay": False, "clips_in_shot": 1}
                          for i, (k, t) in enumerate([("footage", True), ("still", False), ("meme", True)], start=1)]}}
    preds = {"cuts": {"good": {"v": [1.0, 2.02]}, "bad": {"v": [0.5]}},
             "tags": {"m": {f"v/{s['shot_id']}": dict(s) for s in gt["v"]["shots"]}},
             "theme": {"e": {"pos": [0.9, 0.8], "neg": [0.2]}},
             "timing": {"tags:m": {"sec_per_min": 3.0, "gpu_min": 0.1}}}
    out = kaggle._score(preds, gt)
    assert out["cuts"]["good"]["score"] == 1.0 and out["cuts"]["bad"]["score"] == 0.0
    assert out["tags"]["m"]["fields"]["kind"]["balanced_accuracy"] == 1.0
    assert not out["tags"]["m"]["fields"]["panels"]["testable"]
    assert out["tags"]["m"]["sec_per_min"] == 3.0
    assert out["theme"]["e"]["score"] == 1.0


def test_a_partial_run_keeps_earlier_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(kaggle, "MERGED", tmp_path / "all.json")
    kaggle._merge({"tags": {"qwen": {"v/1": {}}}, "theme": {}, "errors": {"theme:siglip2": "boom"}})
    merged = kaggle._merge({"theme": {"siglip2": {"pos": [1], "neg": [0]}}, "errors": {}})
    assert "qwen" in merged["tags"] and "siglip2" in merged["theme"]
    assert "theme:siglip2" not in merged["errors"]


def test_notebook_code_parses_with_placeholders_filled():
    code = kaggle.NOTEBOOK_CODE
    for k in ("__GT__", "__HF_TOKEN__", "__IN_VIDEOS_SLUG__", "__IN_VIDEOS_PROBE__", "__IN_FRAMES_SLUG__", "__IN_FRAMES_PROBE__"):
        code = code.replace(k, repr("x"))
    ast.parse(code.replace("__JOBS__", repr(["tags"])).replace("__MODELS__", repr([])))


def test_notebook_prompt_formats_with_motion():
    code = kaggle.NOTEBOOK_CODE
    prompt_src = code[code.index("PROMPT = ("):code.index("def motion_word")]
    ns = {}
    exec(prompt_src, ns)
    text = ns["PROMPT"].format(motion="low")
    assert "motion across the shot: low" in text
    assert '{"kind": one of ["footage","still","graphic","talking_head","meme"]' in text


def test_slug_for_strips_spaces_and_case():
    assert slug_for("Man U leeds Loss.mov") == "man-u-leeds-loss"
    assert slug_for("SESKO_AI_READY.mp4") == "sesko-ai-ready"


def test_frange_covers_range_without_overshoot():
    ts = list(_frange(0.0, 3.0, 1.0))
    assert ts == [0.0, 1.0, 2.0]


def test_frange_empty_when_start_ge_stop():
    assert list(_frange(5.0, 3.0, 1.0)) == []


def test_report_table_formats_header_and_rows():
    md = _table(["a", "b"], [["1", "2"], ["3", "4"]])
    lines = md.splitlines()
    assert lines[0] == "| a | b |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| 1 | 2 |"


def test_manual_notebook_builds_and_every_cell_parses():
    import json as _json

    from tools.match.bakeoff import manual_notebook
    nb = _json.loads(manual_notebook.build().read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in nb["cells"]]
    for c in cells:
        ast.parse(c)
    assert not any(p in "".join(cells) for p in ("__GT__", "__JOBS__", "__MODELS__", "__HF_TOKEN__", "__IN_"))
