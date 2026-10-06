"""A Google Images block queues the shot for the Chrome pass instead of counting as empty (SPEC.md Part 7, M10.4)."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.assets import chrome_queue as Q  # noqa: E402
from tools.assets import run as R  # noqa: E402
from tools.assets.search import NeedsChrome, google_blocked  # noqa: E402
from tools.match import autopick as P  # noqa: E402


def session(tmp_path):
    shot = {"shot_number": 3, "start": 0.0, "end": 2.0, "audio": "the logo",
            "visual": {"type": "REAL_IMAGE", "desc": "the company logo",
                       "search_sources": [{"source": "google_images", "queries": ["acme logo"]},
                                          {"source": "wikimedia", "queries": ["acme logo"]}]}}
    (tmp_path / "plan.json").write_text(json.dumps({"shots": [shot]}))
    return tmp_path


def candidates(tmp_path, monkeypatch):
    def blocked(q):
        raise NeedsChrome("google images served a captcha")

    monkeypatch.setattr(R, "_load_config", lambda: {})
    monkeypatch.setattr(R, "_build_source_fn_map", lambda config, **_: {"google_images": blocked, "wikimedia": lambda q: []})
    R.cmd_candidates(argparse.Namespace(session=str(tmp_path), n=3, per_source=2, queries=None, sources=None, max_queries=0))


def test_captcha_queues_the_shot_and_autopick_waits(tmp_path, monkeypatch):
    candidates(session(tmp_path), monkeypatch)
    q = json.loads((tmp_path / "assets" / "chrome_queue.json").read_text())
    assert q["shots"]["3"]["status"] == "pending" and q["shots"]["3"]["queries"] == ["acme logo"]
    assert P.chrome_pending(tmp_path) == {3}


def test_a_shot_through_the_pass_is_never_requeued(tmp_path, monkeypatch):
    candidates(session(tmp_path), monkeypatch)
    Q.set_status(tmp_path, 3, "skipped")
    candidates(tmp_path, monkeypatch)
    assert Q.load(tmp_path)["shots"]["3"]["status"] == "skipped" and P.chrome_pending(tmp_path) == set()


def test_add_saves_the_image_into_the_manifest(tmp_path, monkeypatch):
    session(tmp_path)
    Q.queue(tmp_path, 3, ["acme logo"])
    monkeypatch.setattr(R, "_download_file", lambda url, dest: dest.write_bytes(b"\xff" * 2048) or True)
    cand = Q.add(tmp_path, 3, "https://example.com/full/acme.png?x=1", "acme logo")
    m = json.loads((tmp_path / "assets" / "candidates" / "shot_3.json").read_text())
    assert m["candidates"] == [cand] and cand["file"].endswith(".png") and Path(cand["file"]).exists()
    assert Q.load(tmp_path)["shots"]["3"]["added"] == 1


def test_captcha_page_detected():
    assert google_blocked("https://www.google.com/sorry/index?continue=x", "")
    assert google_blocked("https://www.google.com/search?q=x", "<p>Our systems have detected unusual traffic</p>")
    assert not google_blocked("https://www.google.com/search?q=x", '<div data-ri="0">"https://a.com/b.jpg",900,900</div>')
