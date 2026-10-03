"""Unit tests for M5.1 bake-off tooling — pure Python, synthetic data, no GPU.

The scoring math (cut-matching F1, macro-F1) also lives inline inside
kaggle.py's NOTEBOOK_CODE string, since a Kaggle kernel can't import this
package. These tests exercise a local copy of that same algorithm so the logic
is verified somewhere runnable — see kaggle.py's module docstring.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match.bakeoff.common import slug_for  # noqa: E402
from tools.match.bakeoff.extract import _frange  # noqa: E402
from tools.match.bakeoff.report import _table  # noqa: E402


def f1_cuts(pred, gt, tol=0.1):
    """Mirrors kaggle.py's NOTEBOOK_CODE::f1_cuts — see that file's docstring."""
    gt_used = [False] * len(gt)
    tp = 0
    for p in sorted(pred):
        best_j, best_d = -1, tol + 1e-9
        for j, g in enumerate(sorted(gt)):
            if gt_used[j]:
                continue
            d = abs(p - g)
            if d <= tol and d < best_d:
                best_d, best_j = d, j
        if best_j >= 0:
            gt_used[best_j] = True
            tp += 1
    fp, fn = len(pred) - tp, len(gt) - tp
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


def macro_f1_kind(preds, gts, classes):
    """Mirrors kaggle.py's NOTEBOOK_CODE::macro_f1_kind."""
    per_class = {}
    for c in classes:
        support = sum(1 for g in gts if g == c)
        if support == 0:
            continue
        tp = sum(1 for p, g in zip(preds, gts) if p == c and g == c)
        fp = sum(1 for p, g in zip(preds, gts) if p == c and g != c)
        fn = sum(1 for p, g in zip(preds, gts) if p != c and g == c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[c] = {"f1": f1, "support": support}
    macro = sum(v["f1"] for v in per_class.values()) / len(per_class) if per_class else 0.0
    return macro, per_class


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


def test_macro_f1_kind_perfect_predictions():
    gts = ["footage", "meme", "still", "footage"]
    macro, per_class = macro_f1_kind(gts, gts, ["footage", "meme", "still", "screen"])
    assert macro == 1.0
    assert "screen" not in per_class  # zero support in gt -> excluded, not zero-scored


def test_macro_f1_kind_zero_gt_support_class_excluded_even_if_predicted():
    # "meme" never appears in ground truth, even though the model predicts it once —
    # exclusion is keyed on gt support, not on whether a class was guessed.
    gts = ["footage", "footage"]
    preds = ["footage", "meme"]
    macro, per_class = macro_f1_kind(preds, gts, ["footage", "meme", "still"])
    assert set(per_class) == {"footage"}
    # tp=1, fp=0, fn=1 (the "meme" miss costs footage's own recall) -> P=1 R=.5 F1=2/3
    assert abs(per_class["footage"]["f1"] - 2 / 3) < 1e-9


def test_macro_f1_kind_all_wrong_scores_zero():
    gts = ["footage", "footage"]
    preds = ["meme", "meme"]
    macro, _ = macro_f1_kind(preds, gts, ["footage", "meme"])
    assert macro == 0.0


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
