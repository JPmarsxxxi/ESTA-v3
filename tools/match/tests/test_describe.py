"""The describe lane with a stubbed `claude` (no network, no model)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest  # noqa: E402

from tools.match import describe as D  # noqa: E402
from tools.match.common import DEFAULT_MATCH  # noqa: E402

ANSWER = {"description": "amber terminal text on black", "kind": "graphic", "content": "ui_chart",
          "sourcing_hint": "terminal backtest readout", "likely_sources": ["hyperframes", "nonsense"],
          "text_extra": True, "overlay_extra": False}


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(D, "match_config", lambda: DEFAULT_MATCH)


def _frames(tmp_path, n):
    from PIL import Image
    out = []
    for i in range(n):
        p = tmp_path / f"k{i}.jpg"
        Image.new("RGB", (640, 360), (i * 20 % 255, 10, 10)).save(p)
        out.append({"id": f"s{i}", "image": p, "words": "the sharpe was 1.9" if i % 2 else ""})
    return out


def _stub(calls, fail_first=0):
    def call(argv, message):
        calls.append((argv, json.loads(message)))
        if len(calls) <= fail_first:
            return "not json at all"
        ids = [c["text"].split()[1].rstrip(":") for c in json.loads(message)["message"]["content"]
               if c["type"] == "text" and c["text"].startswith("Shot ")]
        result = json.dumps({i: ANSWER for i in ids})
        return "\n".join([json.dumps({"type": "system"}),
                          json.dumps({"type": "result", "result": result, "total_cost_usd": 0.01})])
    return call


def test_batches_parse_and_lean_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "CACHE", tmp_path / "describe.json")
    calls = []
    monkeypatch.setattr(D, "_call", _stub(calls))
    res = D.describe_shots(_frames(tmp_path, 23), log=lambda m: None)
    assert len(calls) == 3  # 10 + 10 + 3
    assert len(res["answers"]) == 23 and not res["errors"]
    a = res["answers"]["s0"]
    assert a["kind"] == "graphic" and a["content"] == "ui_chart" and a["likely_sources"] == ["hyperframes"]
    argv = calls[0][0]
    for flag in ("--strict-mcp-config", "--setting-sources", "--tools", "--max-turns"):
        assert flag in argv
    # Batches run in parallel, so calls arrive in any order.
    sizes = sorted(sum(c["type"] == "image" for c in m["message"]["content"]) for _, m in calls)
    assert sizes == [3, 10, 10]
    spoken = [c["text"] for _, m in calls for c in m["message"]["content"] if c["type"] == "text" and "spoken" in c["text"]]
    assert spoken and "sharpe" in spoken[0]


def test_cache_hit_makes_no_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "CACHE", tmp_path / "describe.json")
    calls = []
    monkeypatch.setattr(D, "_call", _stub(calls))
    items = _frames(tmp_path, 4)
    D.describe_shots(items, log=lambda m: None)
    n = len(calls)
    res = D.describe_shots(items, log=lambda m: None)
    assert len(calls) == n and len(res["answers"]) == 4 and res["cost_usd"] == 0


def test_malformed_batch_retried_once(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "CACHE", tmp_path / "describe.json")
    calls = []
    monkeypatch.setattr(D, "_call", _stub(calls, fail_first=1))
    res = D.describe_shots(_frames(tmp_path, 3), log=lambda m: None)
    assert len(calls) == 2 and len(res["answers"]) == 3 and not res["errors"]


def test_failing_batch_reports_error(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "CACHE", tmp_path / "describe.json")
    calls = []
    monkeypatch.setattr(D, "_call", _stub(calls, fail_first=99))
    res = D.describe_shots(_frames(tmp_path, 3), log=lambda m: None)
    assert len(calls) == 2 and res["answers"] == {} and res["errors"]


def test_normalise_repairs_bad_fields():
    a = D.normalise({"kind": "photo", "content": "??", "likely_sources": ["pexels_image"]})
    assert a["kind"] == "still" and a["content"] == "background" and a["text_extra"] is False
