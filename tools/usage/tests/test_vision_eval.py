"""tools/vision_eval/replay.py scoring on synthetic items."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.vision_eval.replay import score  # noqa: E402


def _v(i, haiku):
    return {"id": f"v{i}", "kind": "validate", "baseline": {"parsed": {"matches": haiku}}}


def test_validate_rates_against_haiku_and_labels():
    items = {f"v{i}": _v(i, h) for i, h in enumerate([True, True, False, False])}
    results = [{"id": "v0", "parsed": {"matches": True}, "secs": 1.0},
               {"id": "v1", "parsed": {"matches": False}, "secs": 2.0},
               {"id": "v2", "parsed": {"matches": True}, "secs": 3.0},
               {"id": "v3", "parsed": None, "secs": 4.0}]
    labels = {"v0": "match", "v1": "match", "v2": "mismatch"}
    m = score(items, results, labels)["validate"]
    assert m["n"] == 4 and m["json_valid"] == 0.75
    assert m["agree_haiku"] == round(1 / 3, 3)
    assert m["says_match_where_haiku_mismatch"] == 1.0
    assert m["false_match_rate"] == 1.0 and m["false_reject_rate"] == 0.5


def test_frame_search_and_judge():
    items = {"f": {"id": "f", "kind": "frame_search", "baseline": {"parsed": {"best_index": 2}}},
             "g": {"id": "g", "kind": "frame_search", "baseline": {"parsed": {"best_index": 0}}},
             "j": {"id": "j", "kind": "judge", "baseline": {"parsed": {"best": 1, "reject": [2]}}}}
    results = [{"id": "f", "parsed": {"best_index": 2}, "secs": 1}, {"id": "g", "parsed": {"best_index": "1"}, "secs": 1},
               {"id": "j", "parsed": {"93": {"best": 1, "reject": [2, 3]}}, "secs": 1}]
    s = score(items, results, {"j": "none"})
    assert s["frame_search"]["same_frame_as_haiku"] == 0.5 and s["frame_search"]["within_one_frame"] == 1.0
    assert s["judge"]["same_best_as_haiku"] == 1.0 and s["judge"]["reject_overlap"] == 0.5
    assert s["judge"]["picked_when_human_said_none"] == 1.0
