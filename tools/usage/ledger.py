"""Append-only usage ledger for headless `claude -p` calls (SPEC.md Part 8).

One JSON line per call in `<session>/usage.jsonl`, or `cache/usage.jsonl` when no
session is known. `ESTA_SESSION_DIR` names the session for tools that don't pass it.
"""

import json
import os
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
# Replies that mean every later call will fail too. Once seen, callers stop spawning
# `claude` for the rest of the process: on 2026-10-06 1,507 calls ran into the limit.
FATAL = ("hit your session limit", "usage limit", "hit your limit", "/login", "invalid api key",
         "not logged in", "credit balance")
_TRIPPED = threading.Event()
_REASON = [""]


def fatal_reply(text: str) -> bool:
    """True (and trips the breaker) for a limit/auth notice. A JSON answer that merely
    mentions a limit (text seen on screen) is not one."""
    low = (text or "").lower()
    if "{" not in low and len(low) < 400 and any(m in low for m in FATAL):
        _REASON[0] = text.strip()[:200]
        _TRIPPED.set()
        return True
    return False


def unavailable() -> str:
    """The limit/auth reply that tripped the breaker, or "" while claude is usable."""
    return _REASON[0] if _TRIPPED.is_set() else ""


def ledger_path(session_dir: str | Path | None = None) -> Path:
    d = session_dir or os.environ.get("ESTA_SESSION_DIR")
    if d:
        p = Path(d)
        return (p if p.is_absolute() else REPO_ROOT / p) / "usage.jsonl"
    return REPO_ROOT / "cache" / "usage.jsonl"


def record(kind: str, model: str, result: dict | None, secs: float, error: str = "",
           session_dir: str | Path | None = None) -> None:
    """`result` is the stream-json `result` event (its `usage` and `total_cost_usd`), or None on failure."""
    u = (result or {}).get("usage") or {}
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": kind,
        "model": model,
        "input": u.get("input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cost_usd": float((result or {}).get("total_cost_usd") or 0),
        "secs": round(secs, 2),
        "ok": not error,
        **({"error": error[:200]} if error else {}),
    }
    path = ledger_path(session_dir)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
    except OSError:
        pass
