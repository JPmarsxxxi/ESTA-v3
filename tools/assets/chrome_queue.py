"""Google Images shots waiting on the Claude in Chrome pass (SPEC.md Part 7, decision 6).

Headless Google Images gets a CAPTCHA, so a gather that hits one queues the shot
in sessions/<id>/assets/chrome_queue.json instead of counting it as empty:

    {"shots": {"12": {"status": "pending", "queries": ["..."], "desc": "...", "audio": "...",
                      "reason": "...", "queued_at": "...", "added": 0}}}

The assets/match skills then work the queue in conversation:

    python tools/assets/chrome_queue.py list --session sessions/<id>
    python tools/assets/chrome_queue.py add  --session sessions/<id> --n 12 --url <full-res image url> [--query q]
    python tools/assets/chrome_queue.py done --session sessions/<id> --n 12
    python tools/assets/chrome_queue.py skip --session sessions/<id> --n 12

`add` saves the image into assets/source_pool and appends it to the shot's
candidates manifest; `done` closes the shot (autopick is then re-run for it);
`skip` lets it fall through to the rewrite loop on its other sources. A shot
already done or skipped is never re-queued by a later CAPTCHA.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


def _path(session: Path) -> Path:
    return session / "assets" / "chrome_queue.json"


@contextmanager
def _locked(session: Path):
    # Gathers run as parallel processes, one per shot: an exclusive lock file keeps their writes whole.
    lock = _path(session).with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 30
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() > deadline:
                lock.unlink(missing_ok=True)  # a crashed writer's lock
                continue
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def load(session: Path) -> dict:
    try:
        return json.loads(_path(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"shots": {}}


def _save(session: Path, q: dict) -> None:
    tmp = _path(session).with_suffix(".tmp")
    tmp.write_text(json.dumps(q, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _path(session))


def queue(session: Path, n, queries: list[str], desc: str = "", audio: str = "", reason: str = "") -> bool:
    """Queue shot n for the Chrome pass; False when it was already done or skipped."""
    with _locked(session):
        q = load(session)
        shots = q.setdefault("shots", {})
        have = shots.get(str(n)) or {}
        if have.get("status") in ("done", "skipped"):
            return False
        shots[str(n)] = {**have, "status": "pending",
                         "queries": list(dict.fromkeys((have.get("queries") or []) + [x for x in queries if x])),
                         "desc": desc, "audio": audio, "reason": reason,
                         "queued_at": have.get("queued_at") or datetime.now().isoformat(), "added": have.get("added", 0)}
        _save(session, q)
        return True


def set_status(session: Path, n, status: str) -> dict:
    with _locked(session):
        q = load(session)
        shot = q.setdefault("shots", {}).get(str(n))
        if shot is None:
            raise ValueError(f"shot {n} is not in the Chrome queue")
        shot["status"] = status
        shot[f"{status}_at"] = datetime.now().isoformat()
        _save(session, q)
        return shot


def add(session: Path, n: int, url: str, query: str = "") -> dict:
    """Save a full-resolution image found in Chrome and append it to shot n's candidates manifest."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.assets.run import _download_file
    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
    ext = ext if ext in {"jpg", "jpeg", "png", "webp"} else "jpg"
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    dest = session / "assets" / "source_pool" / f"google_images_{key}.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest.exists() and dest.stat().st_size > 1024) and not _download_file(url, dest):
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"download failed: {url}")
    w = h = 0
    try:
        from PIL import Image
        with Image.open(dest) as im:
            w, h = im.size
    except Exception:
        pass
    cand = {"candidate_id": f"google_images:{key}", "source": "google_images", "asset_type": "image",
            "query": query, "url": url, "file": str(dest).replace("\\", "/"), "title": f"{query[:40]} (Chrome)",
            "thumb": url, "width": w, "height": h, "source_duration": 0.0, "in_point": 0.0, "out_point": 0.0,
            "via": "chrome"}
    mpath = session / "assets" / "candidates" / f"shot_{n}.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    m = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {"shot_number": n, "candidates": []}
    m["candidates"] = [c for c in m.get("candidates", []) if c.get("candidate_id") != cand["candidate_id"]] + [cand]
    if query:
        m["queries"] = list(dict.fromkeys((m.get("queries") or []) + [query]))
    mpath.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    with _locked(session):
        q = load(session)
        shot = q.setdefault("shots", {}).setdefault(str(n), {"status": "pending"})
        shot["added"] = shot.get("added", 0) + 1
        _save(session, q)
    return cand


def main() -> None:
    ap = argparse.ArgumentParser(description="The Google Images Chrome queue")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "add", "done", "skip"):
        p = sub.add_parser(name)
        p.add_argument("--session", required=True)
        if name != "list":
            p.add_argument("--n", type=int, required=True)
        if name == "add":
            p.add_argument("--url", required=True)
            p.add_argument("--query", default="")
    a = ap.parse_args()
    session = Path(a.session)
    try:
        if a.cmd == "list":
            out = {k: v for k, v in load(session).get("shots", {}).items() if v.get("status") == "pending"}
        elif a.cmd == "add":
            out = add(session, a.n, a.url, a.query)
        else:
            out = set_status(session, a.n, "done" if a.cmd == "done" else "skipped")
        print(json.dumps({"ok": True, "result": out}, ensure_ascii=False, indent=1))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
