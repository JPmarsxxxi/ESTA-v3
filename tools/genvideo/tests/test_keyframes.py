"""Keyframes: look refs reach video through an SDXL first frame per AI shot (SPEC.md Part 5, M8.2); without refs
every unseeded shot still gets a plain SDXL keyframe, since both video models are image-to-video only (Part 6)."""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genvideo import run as G  # noqa: E402
from tools.look import refs as R  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_ffmpeg", lambda *a: subprocess.run(["ffmpeg", "-v", "error", *a], capture_output=True, text=True))
    monkeypatch.setattr(G, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(R, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(G, "kaggle_username", lambda: "me")
    s = tmp_path / "neon-2026-10-03"
    s.mkdir()
    (s / "requirements.json").write_text(json.dumps({"look": "cartoon", "look_style": "comic halftone 3D"}))
    shots = [{"shot_number": 1, "start": 0, "end": 3, "visual": {"type": "AI_VIDEO", "desc": "kai", "generate": {"character": "Kai"}}},
             {"shot_number": 2, "start": 3, "end": 6, "visual": {"type": "AI_VIDEO", "desc": "neon street"}},
             {"shot_number": 3, "start": 6, "end": 9, "visual": {"type": "AI_VIDEO", "desc": "rooftops"}}]
    (s / "plan.json").write_text(json.dumps({"shots": shots}))
    ref = tmp_path / "characters" / "kai" / "ref.png"
    ref.parent.mkdir(parents=True)
    Image.new("RGB", (640, 640), (90, 20, 20)).save(ref)
    return s


def add_refs(session, tmp_path):
    files = []
    for i in range(2):
        f = tmp_path / f"street{i}.png"
        Image.new("RGB", (400, 300), (200, 60 * i, 120)).save(f)
        files.append(f)
    R.add(session, files)


def push(session, capsys, model="anisora", strength=1.0):
    G.cmd_push(argparse.Namespace(session=str(session), model=model, accelerator="t4", preset="static", style="cinematic",
                                  shots="", chain=1, seed_from_assets=False, dry_run=True, lipsync="off", ref_strength=strength,
                                  frames=0, fps=0, width=0, height=0, steps=0, guidance=0.0))
    return json.loads(capsys.readouterr().out)


def notebook(session):
    nb = json.loads(next((session / "assets" / "gen_kernel").glob("*.ipynb")).read_text())
    code = "".join("".join(c["source"]) for c in nb["cells"])
    slots = json.loads(ast.literal_eval(re.search(r"^SLOTS *= json.loads\((.*)\)$", code, re.M).group(1)))
    return code, slots


def test_unseeded_slots_get_styled_keyframes(session, tmp_path, capsys):
    add_refs(session, tmp_path)
    out = push(session, capsys)
    assert out["seeding"]["characters"] == {"1": "ref"}
    assert out["seeding"]["keyframes"] == {"refs": ["r01.jpg", "r02.jpg"], "shots": {"2": "styled_keyframe", "3": "styled_keyframe"}}
    assert out["seeding"]["seeded"] == 3
    code, slots = notebook(session)
    ast.parse(code)
    assert [s.get("keyframe", False) for s in slots] == [False, True, True]
    assert "def keyframe_pass" in code and 'load_ip_adapter("h94/IP-Adapter"' in code
    assert code.index("keyframe_pass()") < code.index("pipe = load_wan(MODEL)")


def test_no_refs_draws_plain_keyframes(session, tmp_path, capsys):
    out = push(session, capsys)
    code, slots = notebook(session)
    ast.parse(code)
    assert out["seeding"]["keyframes"] == {"refs": [], "shots": {"2": "plain_keyframe", "3": "plain_keyframe"}}
    assert out["seeding"]["seeded"] == 3
    assert [s.get("keyframe", False) for s in slots] == [False, True, True]
    assert "def keyframe_pass" in code and "load_ip_adapter" not in code
    add_refs(session, tmp_path)
    out = push(session, capsys, strength=0)
    assert set(out["seeding"]["keyframes"]["shots"].values()) == {"plain_keyframe"}
    assert "load_ip_adapter" not in notebook(session)[0]


def test_image_to_video_only_model_is_satisfied_by_keyframes(session, tmp_path, capsys):
    add_refs(session, tmp_path)
    assert push(session, capsys, model="wan5b")["seeding"]["seeded"] == 3


def test_model_without_image_to_video_skips_the_pass(session, tmp_path):
    add_refs(session, tmp_path)
    slots = [{"shot_number": 2, "seed_b64": ""}]
    out = G.attach_keyframes(session, slots, {"pipeline_i2v": ""}, "t2v-only", 1.0)
    assert out == {"skipped": "t2v-only has no image-to-video pipeline: no keyframes"} and "keyframe" not in slots[0]


def test_empty_look_draws_keyframes_with_base_sdxl(session, tmp_path):
    from tools.genchar.run import MODELS
    (session / "requirements.json").write_text(json.dumps({"look": "", "look_style": ""}))
    add_refs(session, tmp_path)
    model = dict(G.MODELS["anisora"])
    G.attach_keyframes(session, [{"shot_number": 2, "seed_b64": ""}], model, "anisora", 1.0)
    assert model["keyframe"]["repo"] == MODELS["sdxl"]["repo"]


def test_stock_frame_rides_as_backup_for_keyframe_slots(session, tmp_path, capsys):
    add_refs(session, tmp_path)
    stock = session / "assets" / "stock.png"
    stock.parent.mkdir(parents=True)
    Image.new("RGB", (640, 360), (10, 120, 10)).save(stock)
    (session / "assets_progress.jsonl").write_text("".join(json.dumps({"shot_number": n, "ok": True, "file": str(stock)}) + "\n"
                                                           for n in (1, 2, 3)))
    G.cmd_push(argparse.Namespace(session=str(session), model="anisora", accelerator="t4", preset="static", style="cinematic",
                                  shots="", chain=1, seed_from_assets=True, dry_run=True, lipsync="off", ref_strength=1.0,
                                  frames=0, fps=0, width=0, height=0, steps=0, guidance=0.0))
    out = json.loads(capsys.readouterr().out)
    assert out["seeding"]["backups"] == [2, 3] and out["seeding"]["seeded"] == 3
    code, slots = notebook(session)
    by = {s["key"]: s for s in slots}
    assert by["2"]["keyframe"] and by["2"]["backup_b64"] and not by["2"]["seed_b64"]
    assert "backup_b64" not in by["1"] and by["1"]["seed_b64"]   # the character keeps its own seed
    assert code.index('slot["key"] in KEYFRAMES') < code.index('slot.get("backup_b64")')
