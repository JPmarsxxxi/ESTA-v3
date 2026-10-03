"""genchar's session hooks (SPEC.md Part 4): pick writes ref.png; render --session keys one keyframe per shot."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genchar import run as C  # noqa: E402


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHARACTERS_DIR", tmp_path / "characters")
    d = tmp_path / "characters" / "homer-like"
    (d / "explore").mkdir(parents=True)
    (d / "character.json").write_text(json.dumps({"name": "Homer Like", "desc": "bald man, white shirt", "model": "sdxl"}))
    return d


def test_pick_writes_ref_png(tmp_path, monkeypatch):
    d = setup(tmp_path, monkeypatch)
    (d / "explore" / "results.json").write_text(json.dumps({"results": {"v01": {"file": "v01.png", "seed": 7}}}))
    (d / "explore" / "v01.png").write_bytes(b"png-bytes")
    C.cmd_pick(argparse.Namespace(name="Homer Like", variation="v01"))
    assert (d / "ref.png").read_bytes() == b"png-bytes"


def test_render_session_keys_and_prompts(tmp_path, monkeypatch, capsys):
    d = setup(tmp_path, monkeypatch)
    (d / "lora").mkdir()
    (d / "lora" / "homer-like.safetensors").write_bytes(b"x")
    session = tmp_path / "my-video-2026-10-02"
    session.mkdir()
    shots = [{"shot_number": 1, "visual": {"desc": "on the couch, wide shot.", "generate": {"character": "Homer Like"}}},
             {"shot_number": 2, "visual": {"desc": "a city skyline"}},
             {"shot_number": 3, "visual": {"desc": "shouting at the TV", "generate": {"character": "homer like"}}}]
    (session / "plan.json").write_text(json.dumps({"shots": shots}))
    (session / "requirements.json").write_text(json.dumps({"look_style": "flat bold-outline sitcom cartoon"}))
    C.cmd_render(argparse.Namespace(name="Homer Like", prompts="", session=str(session), lora_scale=0.9, seed=777,
                                    accelerator="t4", dry_run=True, style_refs="", ref_strength=1.0))
    out = json.loads(capsys.readouterr().out)
    assert out["keys"] == ["my-video-2026-10-02__s1", "my-video-2026-10-02__s3"]
    assert "bald man, white shirt, on the couch, wide shot, flat bold-outline sitcom cartoon" in out["sample"]
    assert out["trigger"] in out["sample"]


def test_look_style_baked_into_design_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(C, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(C, "push_job", lambda name, jobs, model, mode, acc, dry: {"ok": True, "kernel": "k", "prompt": jobs[0]["prompt"],
                                                                                  "model": model["repo"]})
    C.cmd_explore(argparse.Namespace(name="Nova", desc="teen girl, short pink hair", count=2, seed=1, model="sdxl",
                                     look="cartoon", look_style="comic halftone 3D", accelerator="t4", dry_run=False,
                                     session="", style_refs="", ref_strength=1.0))
    out = json.loads(capsys.readouterr().out)
    assert "teen girl, short pink hair, comic halftone 3D" in out["prompt"]
    assert C.load_char("Nova")["desc"] == "teen girl, short pink hair, comic halftone 3D"
    session = tmp_path / "v"
    session.mkdir()
    (session / "plan.json").write_text(json.dumps({"shots": [{"shot_number": 1, "visual": {"desc": "on a roof", "generate": {"character": "Nova"}}}]}))
    (session / "requirements.json").write_text(json.dumps({"look_style": "comic halftone 3D"}))
    assert C.session_scenes("Nova", session) == [("v__s1", "on a roof")]
