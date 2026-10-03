"""genchar with look refs (SPEC.md Part 5, M8.2): the IP-Adapter rides only with refs, per purpose."""

import argparse
import ast
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genchar import run as C  # noqa: E402
from tools.look import refs as R  # noqa: E402


def session_with_refs(tmp_path):
    s = tmp_path / "v"
    s.mkdir()
    files = []
    for i, colour in enumerate([(200, 0, 0), (0, 200, 0), (0, 0, 200)]):
        f = tmp_path / f"in{i}.png"
        Image.new("RGB", (300, 300), colour).save(f)
        files.append(f)
    R.add(s, files)
    R.set_role(s, "r01.jpg", "character")
    return s


def notebook(name, tmp_path, kernel="_kernel"):
    nb = json.loads(next((tmp_path / "characters" / C.slugify(name) / kernel).glob("*.ipynb")).read_text())
    return "".join("".join(c["source"]) for c in nb["cells"])


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(R, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(C, "kaggle_username", lambda: "me")


def explore(name, session="", style_refs="", strength=1.0):
    C.cmd_explore(argparse.Namespace(name=name, desc="teen boy, curly hair", count=2, seed=1, model="sdxl", look="cartoon",
                                     look_style="", accelerator="t4", dry_run=True, session=session,
                                     style_refs=style_refs, ref_strength=strength))


def test_no_refs_no_adapter(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    explore("Kai")
    assert json.loads(capsys.readouterr().out)["refs"] == []
    code = notebook("Kai", tmp_path)
    ast.parse(code)
    assert "IP-Adapter" not in code and "load_ip_adapter" not in code and "**IPA_KW" in code


def test_explore_uses_character_refs_with_scaled_adapter(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    s = session_with_refs(tmp_path)
    explore("Kai", session=str(s), strength=0.5)
    assert json.loads(capsys.readouterr().out)["refs"] == ["r01.jpg"]
    code = notebook("Kai", tmp_path)
    ast.parse(code)
    assert 'load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models", weight_name="ip-adapter_sdxl.bin")' in code
    assert '"ref_scale": {"style": 0.5, "layout": 0.3}' in code


def test_strength_zero_turns_refs_off(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    explore("Kai", session=str(session_with_refs(tmp_path)), strength=0)
    assert json.loads(capsys.readouterr().out)["refs"] == [] and "load_ip_adapter" not in notebook("Kai", tmp_path)


def test_own_style_refs_are_kept_and_win(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    own = tmp_path / "own"
    own.mkdir()
    Image.new("RGB", (64, 64)).save(own / "face.png")
    (own / "readme.txt").write_text("x")
    explore("Kai", session=str(session_with_refs(tmp_path)), style_refs=str(own))
    assert json.loads(capsys.readouterr().out)["refs"] == ["face.png"]
    assert [p.name for p in (tmp_path / "characters" / "kai" / "style_refs").iterdir()] == ["face.png"]


def test_render_uses_scene_refs_from_the_remembered_session(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    s = session_with_refs(tmp_path)
    d = tmp_path / "characters" / "kai"
    (d / "lora").mkdir(parents=True)
    (d / "lora" / "kai.safetensors").write_bytes(b"x")
    (d / "character.json").write_text(json.dumps({"name": "Kai", "desc": "teen boy", "model": "sdxl", "session": str(s)}))
    C.cmd_render(argparse.Namespace(name="Kai", prompts="on a roof", session="", lora_scale=0.9, seed=7, accelerator="t4",
                                    dry_run=True, style_refs="", ref_strength=1.0))
    assert json.loads(capsys.readouterr().out)["refs"] == ["r01.jpg", "r02.jpg", "r03.jpg"]


def test_ipa_block_is_valid_python_in_place():
    code = C.char_notebook([{"key": "a", "prompt": "p", "seed": 1}], {"style_refs": ["eA=="], "ref_scale": R.scales(1.0)})
    ast.parse(code)
    assert code.index("load_lora_weights") < code.index("load_ip_adapter") < code.index("results, errors = {}, {}")
