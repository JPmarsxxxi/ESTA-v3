"""Talking shots (SPEC.md Part 4, M7.2): voiceover slices ship with the job; apply prefers the synced clip."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genvideo import run as G  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_ffmpeg", lambda *a: subprocess.run(["ffmpeg", "-v", "error", *a], capture_output=True, text=True))
    monkeypatch.setattr(G, "CHARACTERS_DIR", tmp_path / "characters")
    s = tmp_path / "talk-video"
    s.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=10", str(s / "audio.wav")], check=True)
    shots = [{"shot_number": 1, "start": 1.0, "end": 4.0, "audio": "you never saw it coming", "visual": {"type": "AI_VIDEO", "desc": "a", "generate": {"talk": True}}},
             {"shot_number": 2, "start": 4.0, "end": 4.3, "audio": "hey", "visual": {"type": "AI_VIDEO", "desc": "b", "generate": {"talk": True}}},
             {"shot_number": 3, "start": 4.3, "end": 7.0, "visual": {"type": "AI_VIDEO", "desc": "c"}},
             {"shot_number": 4, "start": 7.0, "end": 9.0, "audio": " ", "visual": {"type": "AI_VIDEO", "desc": "d", "generate": {"talk": True}}}]
    (s / "plan.json").write_text(json.dumps({"shots": shots}))
    return s


def push(session, lipsync, monkeypatch, capsys):
    monkeypatch.setattr(G, "kaggle_username", lambda: "me")
    G.cmd_push(argparse.Namespace(session=str(session), model="anisora", accelerator="t4", preset="static", style="cinematic",
                                  shots="", chain=1, seed_from_assets=False, dry_run=True, lipsync=lipsync, ref_strength=1.0, split=1,
                                  frames=0, fps=0, width=0, height=0, steps=0, guidance=0.0))
    return json.loads(capsys.readouterr().out)


def notebook(session):
    import ast
    import re
    nb = json.loads(next((session / "assets" / "gen_kernel").glob("*.ipynb")).read_text())
    code = "".join("".join(c["source"]) for c in nb["cells"])
    val = lambda name: json.loads(ast.literal_eval(re.search(rf"^{name} *= json.loads\((.*)\)$", code, re.M).group(1)))  # noqa: E731
    return code, val("SLOTS"), val("MODEL")


def test_talking_slices_ship_with_the_job(session, monkeypatch, capsys):
    out = push(session, "latentsync", monkeypatch, capsys)
    assert out["talking"] == {"1": "3.00 s", "2": "line under 0.5 s: no lip-sync", "4": "no spoken line: no lip-sync"}
    code, slots, model = notebook(session)
    by = {s["key"]: s for s in slots}
    assert by["1"]["audio_b64"] and by["1"]["audio_seconds"] == 3.0 and not by["2"]["audio_b64"] and not by["3"]["audio_b64"] and not by["4"]["audio_b64"]
    assert model["lipsync"] == "latentsync" and "LatentSync-1.5" in code


def test_lipsync_off_ships_no_audio(session, monkeypatch, capsys):
    out = push(session, "off", monkeypatch, capsys)
    assert out["talking"] == {}
    _, slots, model = notebook(session)
    assert model["lipsync"] == "off" and not any(s["audio_b64"] for s in slots)


def test_apply_prefers_synced_clip_and_records_failures(session, tmp_path):
    out = tmp_path / "kout"
    out.mkdir()
    for name in ("gen_1.mp4", "gen_1_talk.mp4", "gen_3.mp4"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=24", str(out / name)], check=True)
    results = {"1": {"file": "gen_1.mp4", "frames": 48, "fps": 24, "shot_number": 1, "synced_file": "gen_1_talk.mp4",
                     "synced_seconds": 3.0, "lipsync": "ok"},
               "3": {"file": "gen_3.mp4", "frames": 48, "fps": 24, "shot_number": 3, "lipsync": "no face found"}}
    marker = G.apply_results(session, results, {}, out)
    rows = {r["shot_number"]: r for r in map(json.loads, (session / "assets_progress.jsonl").read_text().splitlines())}
    assert rows[1]["file"].endswith("gen_1_talk.mp4") and rows[1]["lipsync"] == "ok" and rows[1]["out_point"] == 3.0
    assert rows[3]["file"].endswith("gen_3.mp4") and rows[3]["lipsync"] == "no face found"
    assert {s["key"]: s.get("lipsync") for s in marker["slots"]} == {"1": "ok", "3": "no face found"}
