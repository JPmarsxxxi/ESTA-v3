"""Scoring formulas and the grade port, on synthetic data (no GPU, no Kaggle)."""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import score as S  # noqa: E402
from tools.match.common import COLOUR_FEATURES, colour_features, kind_group, plan_kind  # noqa: E402
from tools.match.grade import apply_grade, curve_table, make_grade  # noqa: E402

TAGS = {"text_on_screen": True, "overlay": False, "panels": 1, "clips_in_shot": 1}


def inspo(durs, kinds, overlay=None):
    shots = []
    for i, (d, k) in enumerate(zip(durs, kinds)):
        tags = {**TAGS, "kind": k, "overlay": bool(overlay and overlay[i])}
        shots.append({"dur": d, "tags": tags, "colour": {f: 10.0 + i for f in COLOUR_FEATURES}})
    return {"shots": shots, "tagged": True}


def ours(durs, kinds, overlay=None):
    return [{"n": i + 1, "dur": d, "kind": k, "overlay": bool(overlay and overlay[i]), "text": True,
             "panels": 1, "clips": 1, "locked": False} for i, (d, k) in enumerate(zip(durs, kinds))]


def test_identical_distributions_score_100():
    durs, kinds = [2.0, 3.0, 4.0, 2.5], ["footage", "graphic", "footage", "meme"]
    ov = [True, False, False, True]
    a, _ = S.section_a(ours(durs, kinds, ov), inspo(durs, kinds, ov), 4, "plan")
    d, _ = S.section_d(ours(durs, kinds, ov), inspo(durs, kinds, ov), "plan", 4, {"panels", "clips_in_shot"})
    e, _ = S.section_e(ours(durs, kinds), inspo(durs, kinds))
    assert a["score"] == 100 and d["score"] == 100 and e["score"] == 100


def test_duration_shift_hand_computed():
    # ours median 4 vs inspo 2: median sub 100*(1-|4-2|/2) = 0; no overlap, KS 1 -> shape 0
    e, _ = S.section_e(ours([4, 4, 4], ["footage"] * 3), inspo([2, 2, 2], ["footage"] * 3))
    assert e["score"] == 0
    # median 2.5 vs 2: median sub 75; KS 1 -> shape 0; section (75 + 0) / 2 = 37.5
    e, _ = S.section_e(ours([2.5, 2.5], ["footage"] * 2), inspo([2, 2], ["footage"] * 2))
    assert abs(e["score"] - 37.5) <= 1


def test_duration_shape_ks_hand_computed():
    # Same median (3), different spread. ECDFs of [1,3,5] and [2,3,4] differ by at most 1/3,
    # so KS = 1/3 -> shape 66.7; median sub 100; section 83.3.
    e, _ = S.section_e(ours([1, 3, 5], ["footage"] * 3), inspo([2, 3, 4], ["footage"] * 3))
    assert abs(e["shape"]["ks"] - 1 / 3) <= 0.01
    assert abs(e["score"] - 83.3) <= 1


def test_text_rate_ignores_subtitles():
    # Inspo: half its time shows text other than subtitles. Ours: no captions, so text is False
    # even though subtitles are burned in; text sub-score 100*(1-0.5/0.5) = 0.
    ins = inspo([2, 2], ["footage", "footage"])
    ins["shots"][0]["tags"]["text_extra"] = True
    ins["shots"][1]["tags"]["text_extra"] = False
    mine = ours([2, 2], ["footage", "footage"])
    for s in mine:
        s["text"] = False
    d, _ = S.section_d(mine, ins, "plan", 3, {"panels", "clips_in_shot"})
    assert d["rates"]["text"]["inspo"] == 0.5 and d["rates"]["text"]["score"] == 0


def test_asset_mix_total_variation():
    # ours: 100% footage; inspo: 50/50 footage/graphic by duration -> TVD 0.5 -> 50
    a, _ = S.section_a(ours([2, 2], ["footage", "footage"]), inspo([2, 2], ["footage", "graphic"]), 4, "plan")
    assert abs(a["score"] - 50) <= 2


def test_complexity_overlay_rate():
    # overlay share ours 0, inspo 0.5 -> overlay sub 0; text equal -> 100; variety equal -> 100; mean 66.7
    d, _ = S.section_d(ours([2, 2], ["footage", "graphic"]), inspo([2, 2], ["footage", "graphic"], [True, False]),
                       "plan", 4, {"panels", "clips_in_shot"})
    assert abs(d["score"] - 66.7) <= 2


def test_colour_identical_is_100_and_shift_drops():
    ins = inspo([2, 2, 2], ["footage"] * 3)
    mine = ours([2, 2, 2], ["footage"] * 3)
    for s, t in zip(mine, ins["shots"]):
        s["features"] = {"colour": dict(t["colour"])}
    b, _ = S.section_b(mine, ins)
    assert b["score"] == 100
    for s in mine:
        s["features"]["colour"] = {f: v + 20 for f, v in s["features"]["colour"].items()}
    b2, _ = S.section_b(mine, ins)
    # every feature shifted 20 with floored IQR -> distance 20/max(iqr,floor) each
    expected = 100 * math.exp(-sum(20 / max(S._iqr([10, 11, 12]), S.COLOUR_FLOOR[f]) for f in COLOUR_FEATURES) / 6)
    assert abs(b2["score"] - expected) <= 2


def test_kind_groups_and_plan_kinds():
    assert kind_group("talking_head", 4) == "footage"
    assert kind_group("meme", 3) == "footage" and kind_group("meme", 4) == "meme"
    shot = {"visual": {"type": "REAL_FOOTAGE", "search_sources": [{"source": "giphy", "queries": []}]}}
    assert plan_kind(shot, 4) == "meme" and plan_kind(shot, 3) == "footage"
    assert plan_kind({"visual": {"type": "MOTION_GRAPHICS"}}, 4) == "graphic"


def test_grade_identity_and_direction():
    img = (np.random.default_rng(0).random((32, 32, 3)) * 255).astype("uint8")
    # Catmull-Rom with clamped end points bends slightly near 0 and 1, in the editor too.
    assert np.abs(apply_grade(img, make_grade(0, 1, 0, 0, 0)).astype(int) - img).mean() < 2
    darker = colour_features([apply_grade(img, make_grade(-0.2, 1, 0, 0, 0))])
    assert darker["L_mean"] < colour_features([img])["L_mean"] - 5
    flat = colour_features([apply_grade(img, make_grade(0, 1, -0.5, 0, 0))])
    assert flat["chroma"] < colour_features([img])["chroma"]


def test_curve_table_matches_endpoints():
    t = curve_table([[0, 0], [0.5, 0.7], [1, 1]])
    assert abs(t[0]) < 1e-6 and abs(t[255] - 1) < 1e-6 and t[128] > 0.65
