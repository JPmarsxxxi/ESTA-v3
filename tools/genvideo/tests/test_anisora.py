"""AniSora as the default video model (SPEC.md Part 6, M9.1-M9.2), without Kaggle."""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.genvideo import run as G  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")


def ffmpeg(*a):
    return subprocess.run(["ffmpeg", "-v", "error", *a], capture_output=True, text=True)


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_ffmpeg", ffmpeg)
    monkeypatch.setattr(G, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(G, "kaggle_username", lambda: "me")
    s = tmp_path / "plain-2026-10-04"
    s.mkdir()
    shots = [{"shot_number": 1, "start": 0, "end": 3.38, "visual": {"type": "AI_VIDEO", "desc": "wolves"}},
             {"shot_number": 2, "start": 3.38, "end": 5.28, "visual": {"type": "AI_VIDEO", "desc": "money",
                                                                       "generate": {"hd": True}}}]
    (s / "plan.json").write_text(json.dumps({"shots": shots}))
    return s


def push(session, capsys, model="anisora", chain=1):
    G.cmd_push(argparse.Namespace(session=str(session), model=model, accelerator="t4", preset="static", style="cinematic",
                                  shots="", chain=chain, seed_from_assets=False, dry_run=True, lipsync="off",
                                  ref_strength=1.0, frames=0, fps=0, width=0, height=0, steps=0, guidance=0.0))
    out = json.loads(capsys.readouterr().out)
    nb = json.loads(next((session / "assets" / "gen_kernel").glob("*.ipynb")).read_text())
    code = "".join("".join(c["source"]) for c in nb["cells"])
    slots = json.loads(ast.literal_eval(re.search(r"^SLOTS *= json.loads\((.*)\)$", code, re.M).group(1)))
    return out, code, slots


def test_models_are_anisora_and_wan5b():
    assert set(G.MODELS) == {"anisora", "wan5b"} and G.DEFAULT_MODEL == "anisora"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "genvideo" / "run.py"), "push", "--session", "x",
                        "--model", "ltx"], capture_output=True, text=True)
    assert r.returncode == 2 and "invalid choice" in r.stderr


def test_no_retired_model_remains():
    src = (ROOT / "tools" / "genvideo" / "run.py").read_text(encoding="utf-8")
    assert not re.search(r"LTX|StableVideoDiffusion|HunyuanVideo15", src)
    assert "LTX" not in (ROOT / "tools" / "genchar" / "run.py").read_text(encoding="utf-8")


def test_notebook_carries_the_bakeoff_recipe(session, capsys):
    out, code, slots = push(session, capsys)
    ast.parse(code)
    for needle in ("High/Index-Anisora-V3.2-High-Q4_0.gguf", "Low/Index-Anisora-V3.2-Low-Q4_K_S.gguf",
                   "expandable_segments:True", "maybe_free_model_hooks", "GGUFQuantizationConfig"):
        assert needle in code, needle
    # Prompts are encoded before the experts load; the keyframe pass runs before both.
    assert code.index("keyframe_pass()") < code.index("ENC = wan_embeds(") < code.index("pipe = load_wan(MODEL)")
    assert out["seeding"]["seeded"] == 2 and all(s["keyframe"] for s in slots)


def test_frames_cover_the_shot_in_4k_plus_1():
    assert [G.frames_for(d, 16, 81) for d in (0.4, 1.9, 3.38, 4.4)] == [17, 33, 57, 73]
    assert G.frames_for(9.0, 16, 81) == 81


def test_long_shots_chain_and_hd_rides_on_the_slot(session, capsys):
    plan = json.loads((session / "plan.json").read_text())
    plan["shots"].append({"shot_number": 3, "start": 5.28, "end": 13.28, "visual": {"type": "AI_VIDEO", "desc": "city"}})
    (session / "plan.json").write_text(json.dumps(plan))
    _, _, slots = push(session, capsys, chain=2)
    by = {s["key"]: s for s in slots}
    assert by["1"]["frames"] == 57 and by["1"]["segments"] == 1
    assert by["3"]["segments"] == 2 and by["3"]["frames"] <= 81
    assert by["2"]["hd"] and not by["1"]["hd"]


def test_wan5b_uses_24_fps_frame_counts(session, capsys):
    _, code, slots = push(session, capsys, model="wan5b")
    assert {s["key"]: s["frames"] for s in slots} == {"1": 85, "2": 49}
    assert "gguf_repo" not in code.split("MODEL = json.loads(")[1].split("\n")[0]


def test_genchar_animate_uses_the_shared_loader(tmp_path, monkeypatch, capsys):
    from tools.genchar import run as C
    monkeypatch.setattr(C, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(C, "_ffmpeg", ffmpeg)
    monkeypatch.setattr(C, "kaggle_username", lambda: "me")
    C.save_char("Kai", {"desc": "kai, a courier in a yellow jacket"})
    still = C.char_dir("Kai") / "render" / "neon__s2.png"
    still.parent.mkdir(parents=True)
    Image.new("RGB", (640, 640), (40, 90, 200)).save(still)
    C.cmd_animate(argparse.Namespace(name="Kai", mode="render", images="", limit=3, accelerator="t4", dry_run=True))
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] and out["clips"] == 1
    code = (C.char_dir("Kai") / "_kernel_anim" / "kernel.ipynb").read_text()
    code = "".join("".join(c["source"]) for c in json.loads(code)["cells"])
    ast.parse(code)
    assert "def load_wan" in code and "Index-Anisora-V3.2" in code and "LTX" not in code


from tools.genvideo.run import hub_missing as real_hub_missing  # noqa: E402  (imported before conftest stubs it)


def test_hub_check_names_missing_files_and_suggests_wan5b(session, capsys, monkeypatch):
    import urllib.error
    import urllib.request

    def fake(req, timeout=0):
        if "High" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return None
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    missing, warn = real_hub_missing(G.MODELS["anisora"])
    assert missing == ["High/Index-Anisora-V3.2-High-Q4_0.gguf"] and warn == ""
    assert real_hub_missing(G.MODELS["wan5b"]) == ([], "")

    monkeypatch.setattr(G, "hub_missing", real_hub_missing)
    with pytest.raises(ValueError, match="not found in youcef079/Index-Anisora-V3.2-GGUF.*--model wan5b"):
        push(session, capsys)


def test_unreachable_hub_only_warns(monkeypatch):
    import urllib.request

    def offline(req, timeout=0):
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    missing, warn = real_hub_missing(G.MODELS["anisora"])
    assert missing == [] and "could not reach the Hub" in warn
