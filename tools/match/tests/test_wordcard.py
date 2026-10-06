"""Word-card graphics for shots past the stock budget, without HyperFrames."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.motiongraphics import wordcard as W  # noqa: E402


def test_card_lands_every_word_by_the_legibility_floor():
    body, tl = W.card("So, alphas, nah,", 2.8)
    assert body.count("class='w'") == 3 and "alphas" in body and "," not in body
    assert tl == 'words(tl, ["#w0", "#w1", "#w2"], [0.0, 1.0, 2.0]);'


def test_long_line_wraps_once():
    body, _ = W.card("one two three four five six seven eight", 4.0)
    assert body.count("<br>") == 1 and body.index("<br>") < body.index("five")


def test_short_shot_shows_at_once():
    _, tl = W.card("too fast", 0.9)
    assert tl.endswith("[0.05, 0.05]);")


def test_no_kit_lists_the_shots_for_the_skill(tmp_path):
    shots = [{"shot_number": 7, "start": 1.0, "end": 3.0, "audio": "x"}]
    out = W.make(tmp_path, shots, log=lambda m: None)
    assert out["queued"] == [7]
    assert json.loads((tmp_path / "stock_overflow.json").read_text())["shots"][0]["reason"] == "no session kit yet"


def test_kit_builds_renders_and_publishes(tmp_path, monkeypatch):
    kit = tmp_path / "assets" / "mg" / "_kit"
    kit.mkdir(parents=True)
    (kit / "surface.css").write_text(".line{}")
    monkeypatch.setattr(W, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(W, "render", lambda session, cfg: (tmp_path / f"mg_{cfg['key']}.mp4", ""))
    shots = [{"shot_number": 7, "start": 1.0, "end": 3.0, "audio": "go now"}]
    out = W.make(tmp_path, shots, log=lambda m: None)
    assert out["published"] == [7]
    assert (tmp_path / "assets" / "mg" / "slot_7" / "index.html").exists()
    row = json.loads((tmp_path / "assets_progress.jsonl").read_text())
    assert row["shot_number"] == 7 and row["source"] == "hyperframes" and row["file"] == "mg_7.mp4"
    mg = json.loads((tmp_path / "motion_graphics.json").read_text())
    assert mg["slots"][0]["origin"] == "stock_cap" and mg["generated"] == 1
