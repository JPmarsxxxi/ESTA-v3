"""genvideo seeds character shots from LoRA keyframe > ref.png > text (SPEC.md Part 4), without Kaggle."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genvideo import run as G  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")


def png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x640", "-frames:v", "1", str(path)], check=True)


def test_seed_order_and_look_style(tmp_path, monkeypatch):
    chars = tmp_path / "characters"
    monkeypatch.setattr(G, "CHARACTERS_DIR", chars)
    # genvideo calls ffmpeg through the esta conda env; this sandbox has ffmpeg but no conda.
    monkeypatch.setattr(G, "_ffmpeg", lambda *a: subprocess.run(["ffmpeg", "-v", "error", *a], capture_output=True, text=True))
    session = tmp_path / "my-video-2026-10-02"
    session.mkdir()
    shots = [{"shot_number": n, "start": 0, "end": 3, "visual": {"type": "AI_VIDEO", "desc": f"scene {n}",
              "generate": {"character": c, **({"talk": True} if n == 1 else {})}}}
             for n, c in ((1, "Homer Like"), (2, "Ref Only"), (3, "Text Only"), (4, "Ghost"))]
    (session / "plan.json").write_text(json.dumps({"shots": shots}))
    (session / "requirements.json").write_text(json.dumps({"look": "cartoon", "look_style": "flat bold-outline sitcom cartoon"}))
    png(chars / "homer-like" / "render" / "my-video-2026-10-02__s1.png")
    png(chars / "homer-like" / "ref.png")
    png(chars / "ref-only" / "ref.png")
    (chars / "text-only").mkdir(parents=True)
    (chars / "text-only" / "character.json").write_text(json.dumps({"desc": "tall man in a blue suit"}))

    model = G.MODELS["anisora"]
    slots = G.collect_slots(session, G.load_presets(), model, "static", "", None, 1)
    report = G.attach_character_seeds(session, slots, model)
    assert report == {1: "lora_keyframe", 2: "ref", 3: "text", 4: "text (no character.json)"}
    by = {s["shot_number"]: s for s in slots}
    assert by[1]["seed_b64"] and by[2]["seed_b64"] and not by[3]["seed_b64"]
    assert all(s["prompt"].endswith("flat bold-outline sitcom cartoon") for s in slots)
    assert by[3]["prompt"].startswith("tall man in a blue suit, scene 3")
    assert by[1]["talk"] and not by[2]["talk"] and by[1]["character"] == "Homer Like"
    from PIL import Image
    import base64
    import io
    w, h = Image.open(io.BytesIO(base64.b64decode(by[1]["seed_b64"]))).size
    assert (w, h) == (model["width"], model["height"])


def test_character_slots_never_take_a_stock_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(G, "_ffmpeg", lambda *a: subprocess.run(["ffmpeg", "-v", "error", *a], capture_output=True, text=True))
    session = tmp_path / "s"
    session.mkdir()
    stock = session / "assets" / "stock.png"
    png(stock)
    (session / "assets_progress.jsonl").write_text("".join(json.dumps({"shot_number": n, "ok": True, "file": str(stock)}) + "\n" for n in (1, 2)))
    slots = [{"shot_number": 1, "seed_b64": "", "character": "Text Only"}, {"shot_number": 2, "seed_b64": ""}]
    report = G.attach_seed_images(session, slots, G.MODELS["anisora"])
    assert report["skipped"] == [{"shot": 1, "why": "character shot: no stock seed"}]
    assert not slots[0]["seed_b64"] and slots[1]["seed_b64"]
