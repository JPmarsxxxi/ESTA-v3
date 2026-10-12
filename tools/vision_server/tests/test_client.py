"""Qwen vision client (SPEC.md Part 10) against a stub HTTP server. No network, no claude."""

import base64
import io
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest  # noqa: E402

from tools.assets import llm  # noqa: E402
from tools.match import describe as D  # noqa: E402
from tools.match.common import DEFAULT_MATCH  # noqa: E402
from tools.usage import ledger  # noqa: E402
from tools.vision_server import client as C  # noqa: E402

REPLY = {"text": '{"matches": true, "confidence": 90, "reason": "ok"}', "status": 200, "seen": [], "delay": 0}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self._send(200, {"ready": True, "model": C.MODEL})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REPLY["seen"].append({"auth": self.headers.get("Authorization"), "body": body})
        time.sleep(REPLY["delay"])
        if REPLY["status"] != 200:
            return self._send(REPLY["status"], {"error": "boom"})
        self._send(200, {"choices": [{"message": {"content": REPLY["text"]}}],
                         "usage": {"prompt_tokens": 900, "completion_tokens": 40}})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    REPLY.update(text='{"matches": true, "confidence": 90, "reason": "ok"}', status=200, seen=[], delay=0)
    monkeypatch.setenv("ESTA_SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(C, "_FAILS", [0])
    monkeypatch.setattr(C, "_TRIPPED", [""])
    monkeypatch.setattr(C, "_SEM", [None])
    monkeypatch.setattr(C, "token", lambda: "tok")
    monkeypatch.setattr(ledger, "_TRIPPED", threading.Event())
    monkeypatch.setattr(ledger, "_REASON", [""])
    monkeypatch.setattr(D, "match_config", lambda: DEFAULT_MATCH)

    def no_claude(*a, **k):
        raise AssertionError("claude spawned")
    monkeypatch.setattr(llm, "_spawn", no_claude)
    monkeypatch.setattr(D, "_call", no_claude)


def use(monkeypatch, url, backend="qwen", timeout=5):
    monkeypatch.setattr(C, "config", lambda: {"backend": backend, "url": url, "concurrency": 4, "timeout": timeout})


def rows(tmp_path):
    return [json.loads(x) for x in (tmp_path / "usage.jsonl").read_text().splitlines()]


def frame() -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (40, 10, 10)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_blocks_convert_to_openai():
    out = C.to_openai([{"type": "text", "text": "frame 0:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}])
    assert out == [{"type": "text", "text": "frame 0:"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]


def test_validate_goes_to_qwen_and_is_logged(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    res = llm.validate_frames([frame()], "q", "desc", "")
    assert res["matches"] is True
    sent = REPLY["seen"][0]
    assert sent["auth"] == "Bearer tok" and sent["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert any(b["type"] == "image_url" for b in sent["body"]["messages"][1]["content"])
    r = rows(tmp_path)[0]
    assert r["backend"] == "qwen" and r["ok"] and r["json_ok"] and r["input"] == 900 and r["kind"] == "validate"


def test_frame_search_goes_to_qwen(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    REPLY["text"] = '{"best_index": 2, "confidence": 70, "reasoning": "x"}'
    p = tmp_path / "f.jpg"
    p.write_bytes(base64.b64decode(frame()))
    assert llm.find_best_frame_at_timestamps([str(p)] * 3, [0, 1, 2], "q", "desc")["best_index"] == 2


def test_invalid_json_is_unchecked(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    REPLY["text"] = "I think it matches"
    assert llm.validate_frames([frame()], "q", "desc", "") is None
    assert rows(tmp_path)[0]["json_ok"] is False


def test_timeout_is_unchecked(monkeypatch, server):
    use(monkeypatch, server, timeout=0.3)
    REPLY["delay"] = 1
    assert llm.validate_frames([frame()], "q", "desc", "") is None


def test_http_error_fails_without_tripping(monkeypatch, server):
    use(monkeypatch, server)
    REPLY["status"] = 500
    for _ in range(6):
        assert llm.validate_frames([frame()], "q", "desc", "") is None
    assert not C._TRIPPED[0]


def test_five_connection_failures_trip_the_breaker(monkeypatch, tmp_path):
    use(monkeypatch, "http://127.0.0.1:9")
    for _ in range(5):
        assert llm.validate_frames([frame()], "q", "desc", "") is None
    assert C._TRIPPED[0]
    n = len(rows(tmp_path))
    assert llm.validate_frames([frame()], "q", "desc", "") is None
    assert len(rows(tmp_path)) == n  # no request once tripped


def test_judge_goes_to_qwen_text_stays_on_claude(monkeypatch, server):
    use(monkeypatch, server)
    REPLY["text"] = '{"12": {"best": 1, "reject": [], "why": "x"}}'
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": frame()}}
    res = D.ask([{"type": "text", "text": "Shot 12"}, img], "sys", "haiku", kind="judge")
    assert res["answer"]["12"]["best"] == 1
    with pytest.raises(AssertionError, match="claude spawned"):
        D.ask([{"type": "text", "text": "rewrite these"}], "sys", "haiku", kind="rewrite")


def test_claude_backend_is_untouched(monkeypatch, server):
    use(monkeypatch, server, backend="claude")
    with pytest.raises(AssertionError, match="claude spawned"):
        llm._call_with_images("p", [frame()], kind="validate")
    assert REPLY["seen"] == []


def test_require_up(monkeypatch, server):
    use(monkeypatch, server)
    C.require_up()
    use(monkeypatch, "http://127.0.0.1:9")
    with pytest.raises(SystemExit):
        C.require_up()


def test_summary_counts():
    rs = [{"backend": "qwen", "ok": True, "json_ok": True, "secs": 4}, {"backend": "qwen", "ok": True, "json_ok": False, "secs": 6},
          {"backend": "qwen", "ok": False, "secs": 1}, {"backend": "claude", "ok": True, "secs": 9}]
    assert C.summary(rs) == {"calls": 3, "failed": 1, "invalid_json": 1, "median_s": 5.0}
