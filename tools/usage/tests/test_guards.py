"""Lean `claude -p` guards (SPEC.md Part 8): fail closed, limit breaker, ledger. No network, no claude."""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest  # noqa: E402

from tools.assets import llm  # noqa: E402
from tools.match import describe as D  # noqa: E402
from tools.match.common import DEFAULT_MATCH  # noqa: E402
from tools.usage import ledger  # noqa: E402

LIMIT = "You've hit your session limit · resets 1:50am (Europe/London)"


def _result(text: str, is_error: bool = False) -> str:
    return json.dumps({"type": "result", "result": text, "is_error": is_error, "total_cost_usd": 0.003,
                       "usage": {"input_tokens": 2100, "output_tokens": 250}}) + "\n"


def _frame() -> str:
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), (40, 10, 10)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ESTA_SESSION_DIR", str(tmp_path))
    monkeypatch.delenv("ESTA_VISION_CAPTURE", raising=False)
    monkeypatch.setattr(ledger, "_TRIPPED", __import__("threading").Event())
    monkeypatch.setattr(ledger, "_REASON", [""])
    monkeypatch.setattr(llm, "_claude_bin", lambda: "claude")
    monkeypatch.setattr(D, "match_config", lambda: DEFAULT_MATCH)


def _rows(tmp_path):
    p = tmp_path / "usage.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_validate_returns_verdict_and_records_usage(monkeypatch, tmp_path):
    seen = []

    def spawn(argv, message, timeout):
        seen.append((argv, json.loads(message)))
        return _result('{"what_i_see": "x", "matches": false, "confidence": 90, "reason": "y"}')

    monkeypatch.setattr(llm, "_spawn", spawn)
    res = llm.validate_frames([_frame()] * 4, "q", "desc", "")
    assert res["matches"] is False
    argv, msg = seen[0]
    assert "--tools" in argv and "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    images = [c for c in msg["message"]["content"] if c["type"] == "image"]
    assert len(images) == 4
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(base64.b64decode(images[0]["source"]["data"]), np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) == llm.MAX_SIDE
    row = _rows(tmp_path)[0]
    assert row["kind"] == "validate" and row["input"] == 2100 and row["ok"]


@pytest.mark.parametrize("reply", ["not json at all", ""])
def test_failed_check_is_not_a_match(monkeypatch, reply):
    monkeypatch.setattr(llm, "_spawn", lambda *a: _result(reply, is_error=not reply))
    assert llm.validate_frames([_frame()], "q", "desc", "") is None


def test_timeout_is_not_a_match(monkeypatch):
    import subprocess

    def spawn(*a):
        raise subprocess.TimeoutExpired("claude", 60)

    monkeypatch.setattr(llm, "_spawn", spawn)
    assert llm.validate_frames([_frame()], "q", "desc", "") is None


def test_no_frames_is_not_a_match():
    assert llm.validate_frames([], "q", "desc", "") is None


def test_limit_trips_breaker_and_stops_spawning(monkeypatch, tmp_path):
    calls = []

    def spawn(*a):
        calls.append(1)
        return _result(LIMIT, is_error=True)

    monkeypatch.setattr(llm, "_spawn", spawn)
    assert llm.validate_frames([_frame()], "q", "desc", "") is None
    assert llm.validate_frames([_frame()], "q", "desc", "") is None
    assert llm.pick_best_videos([{"duration": 30}, {"duration": 10}], "q", n=1) == [1]
    assert len(calls) == 1
    assert ledger.unavailable().startswith("You've hit")
    # describe.ask (judge, rewrite, describe lanes) sees the same breaker.
    monkeypatch.setattr(D, "_call", lambda *a: pytest.fail("spawned claude after the limit"))
    assert "unavailable" in D.ask([{"type": "text", "text": "hi"}], "sys", "haiku")["error"]


def test_json_answer_mentioning_a_limit_does_not_trip(monkeypatch):
    monkeypatch.setattr(llm, "_spawn", lambda *a: _result(
        '{"what_i_see": "a banner reading usage limit reached", "matches": true, "confidence": 80, "reason": "r"}'))
    assert llm.validate_frames([_frame()], "q", "desc", "")["matches"] is True
    assert not ledger.unavailable()


def test_describe_ask_limit_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "_call", lambda *a: _result(LIMIT, is_error=True))
    res = D.ask([{"type": "text", "text": "hi"}], "sys", "haiku", kind="judge")
    assert "error" in res and ledger.unavailable()
    assert _rows(tmp_path)[0]["kind"] == "judge" and not _rows(tmp_path)[0]["ok"]


def test_capture_writes_frames_and_record(monkeypatch, tmp_path):
    monkeypatch.setenv("ESTA_VISION_CAPTURE", "1")
    monkeypatch.setattr(llm, "_spawn", lambda *a: _result('{"matches": true, "confidence": 70}'))
    llm.validate_frames([_frame()] * 2, "q", "desc", "", meta={"url": "https://x/y.mp4"})
    rec = json.loads((tmp_path / "vision_eval" / "records.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["kind"] == "validate" and rec["url"] == "https://x/y.mp4" and rec["parsed"]["matches"] is True
    assert all((tmp_path / "vision_eval" / f).exists() for f in rec["frame_files"])
    assert rec["prompt"] == llm.validate_prompt("q", "desc")
