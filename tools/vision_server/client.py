"""Client for the live Qwen vision server on Kaggle (SPEC.md Part 10).

With `vision.backend: qwen` in config.yaml, every image call that llm.py and describe.ask would send to
`claude -p` comes here instead; text-only calls stay on Claude. A failure raises and the caller keeps its
"unchecked" path: there is no Claude fallback. Five connection failures in a row trip a breaker for the
rest of the process, so a dead server costs five timeouts, not one per candidate.
"""

import json
import re
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE = REPO_ROOT / ".esta" / "vision_server.json"
MODEL = "Qwen/Qwen3.5-9B"
TRIP_AFTER = 5

_LOCK = threading.Lock()
_FAILS = [0]
_TRIPPED = [""]
_SEM: list[threading.Semaphore | None] = [None]


class VisionUnavailable(RuntimeError):
    pass


def config() -> dict:
    try:
        import yaml
        cfg = (yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}).get("vision") or {}
    except (OSError, ImportError):
        cfg = {}
    return {"backend": cfg.get("backend", "claude"), "url": (cfg.get("url") or "").rstrip("/"),
            "concurrency": int(cfg.get("concurrency", 8)), "timeout": int(cfg.get("timeout", 120))}


def token() -> str:
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("token", "")
    except (OSError, ValueError):
        return ""


def wants(content: list[dict]) -> bool:
    """True when this turn holds an image and the vision backend is Qwen."""
    return any(b.get("type") == "image" for b in content) and config()["backend"] == "qwen"


def to_openai(content: list[dict]) -> list[dict]:
    out = []
    for b in content:
        if b.get("type") == "image":
            src = b["source"]
            out.append({"type": "image_url", "image_url": {"url": f"data:{src.get('media_type', 'image/jpeg')};base64,{src['data']}"}})
        elif b.get("type") == "text":
            out.append({"type": "text", "text": b["text"]})
    return out


def json_ok(text: str) -> bool:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return False
    try:
        json.loads(m.group())
        return True
    except ValueError:
        return False


def _request(path: str, body: dict | None, timeout: float) -> dict:
    cfg = config()
    if not cfg["url"]:
        raise VisionUnavailable("vision.url missing from config.yaml")
    req = urllib.request.Request(cfg["url"] + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json",
                                          "ngrok-skip-browser-warning": "1"},
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def health(timeout: float = 15) -> dict | None:
    try:
        return _request("/health", None, timeout)
    except (OSError, ValueError, VisionUnavailable):
        return None


def require_up() -> None:
    """Jobs call this first when the backend is Qwen: a dead server stops the job instead of leaving every
    shot unchecked."""
    if config()["backend"] != "qwen":
        return
    h = health()
    if not h or not h.get("ready"):
        raise SystemExit(f"vision backend is qwen but the server at {config()['url'] or '(no vision.url)'} is not "
                         f"ready ({h}). Start it: python tools/vision_server/run.py up")


def chat(content: list[dict], system: str, kind: str, timeout: float | None = None, max_tokens: int = 1024) -> str:
    """One turn on the Qwen server; returns the reply text. Raises on any failure."""
    from tools.usage import ledger
    cfg = config()
    if _TRIPPED[0]:
        raise VisionUnavailable(_TRIPPED[0])
    with _LOCK:
        if _SEM[0] is None:
            _SEM[0] = threading.Semaphore(cfg["concurrency"])
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": to_openai(content)}]}
    t0 = time.time()
    with _SEM[0]:
        try:
            r = _request("/v1/chat/completions", body, timeout or cfg["timeout"])
        except urllib.error.HTTPError as e:
            # The server answered, so it is alive: an HTTP error fails this call but never trips the breaker.
            err = f"http {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
            ledger.record(kind, MODEL, None, time.time() - t0, err, backend="qwen")
            raise RuntimeError(err) from None
        except (OSError, ValueError) as e:
            err = f"unreachable: {e}"[:200]
            with _LOCK:
                _FAILS[0] += 1
                if _FAILS[0] >= TRIP_AFTER and not _TRIPPED[0]:
                    _TRIPPED[0] = f"qwen server unreachable {TRIP_AFTER} times in a row: {e}"[:200]
                    print(f"    [vision] {_TRIPPED[0]}; remaining checks stay unchecked", flush=True)
            ledger.record(kind, MODEL, None, time.time() - t0, err, backend="qwen")
            raise VisionUnavailable(err) from None
    with _LOCK:
        _FAILS[0] = 0
    text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    u = r.get("usage") or {}
    ledger.record(kind, MODEL, {"usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}},
                  time.time() - t0, "" if text else "empty reply", backend="qwen", json_ok=json_ok(text))
    if not text:
        raise RuntimeError("empty reply")
    return text


def summary(rows: list[dict]) -> dict:
    """Qwen counts for the usage report: calls, failures, invalid JSON, median seconds."""
    q = [r for r in rows if r.get("backend") == "qwen"]
    ok = [r for r in q if r.get("ok")]
    return {"calls": len(q), "failed": len(q) - len(ok), "invalid_json": sum(1 for r in ok if r.get("json_ok") is False),
            "median_s": round(statistics.median([r["secs"] for r in ok]), 2) if ok else 0}
