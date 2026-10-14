"""SPEC.md Part 12 goals A, C (profiling half) and D (profiling half): layers, captions and the look block."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import layers as L  # noqa: E402
from tools.style_analysis import look as K  # noqa: E402

cv2 = pytest.importorskip("cv2")
FIXTURES = Path(__file__).parent / "fixtures" / "m14_profiles"


def shot(i, dur, kind="graphic", material="illustration"):
    return {"id": f"s{i}", "dur": dur, "tags": {"kind": kind, "material": material}}


def test_presenter_cut_out_over_art():
    shots = [shot(i, 2.0) for i in range(10)]
    faces = {f"s{i}": (0.6, 0.55, 0.2, 0.25) for i in range(6)} | {"s6": (0.1, 0.1, 0.05, 0.05)}
    p = L.presenter(shots, faces)
    assert p["share"] == 0.6 and p["cutout"] and p["bbox"] == {"x": 0.6, "y": 0.55, "w": 0.2, "h": 0.25}


def test_full_frame_talking_head_is_not_cut_out():
    shots = [shot(i, 2.0, "footage", "live_action") for i in range(5)]
    p = L.presenter(shots, {f"s{i}": (0.35, 0.2, 0.3, 0.4) for i in range(3)})
    assert p and p["cutout"] is False


def test_talking_head_with_varying_face_size_is_a_presenter():
    shots = [shot(i, 2.0, "footage", "live_action") for i in range(10)]
    faces = {f"s{i}": (0.4, 0.3, 0.2, 0.2) for i in range(3)} | {f"s{i}": (0.33, 0.2, 0.35, 0.35) for i in range(3, 6)}
    p = L.presenter(shots, faces)
    assert p and p["cutout"] is False and p["shots"] == 6


def test_no_presenter_under_forty_percent():
    shots = [shot(i, 2.0) for i in range(10)]
    assert L.presenter(shots, {f"s{i}": (0.6, 0.55, 0.2, 0.25) for i in range(3)}) is None


def _caption_obs(t, text, spoken, display=""):
    lines = [{"text": text, "box": (300, 1500, 780, 1580), "colour": (60, 220, 90)}]
    if display:
        lines.append({"text": display, "box": (100, 200, 900, 320), "colour": (255, 255, 255)})
    return {"t": t, "w": 1080, "h": 1920, "spoken": spoken, "lines": lines}


WORDS = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in
         enumerate("the edge did not fade it flipped same size opposite sign holy molly".split())]


def test_caption_layer_reads_the_band_and_ignores_display_type():
    obs = [_caption_obs(w["start"] + 0.2, f"{w['word']} {WORDS[min(i + 1, len(WORDS) - 1)]['word']}", w["word"],
                        display="OZEMPIC FOR THE BRAIN") for i, w in enumerate(WORDS)]
    c = L.caption_layer(obs, WORDS)
    assert c["present"] and c["colour"] == "#3cdc5a" and c["animation"] == "static_line"
    assert c["band"] == {"y0": round(1500 / 1920, 3), "y1": round(1580 / 1920, 3)}
    assert c["words_per_chunk"] == 2 and c["case"] == "lower"


def test_display_type_alone_is_not_a_caption():
    obs = [{"t": w["start"], "w": 1080, "h": 1920, "spoken": w["word"],
            "lines": [{"text": "BUFF MOTION", "box": (0, 0, 10, 10), "colour": (255, 255, 255)}]} for w in WORDS]
    assert L.caption_layer(obs, WORDS)["present"] is False
    assert L.caption_layer(obs, [])["present"] is False  # the showreel: no speech, no caption layer


def test_karaoke_highlight_is_detected():
    obs = []
    for i, w in enumerate(WORDS):
        o = _caption_obs(w["start"] + 0.2, f"{w['word']} {WORDS[min(i + 1, len(WORDS) - 1)]['word']}", w["word"])
        o["lines"][0]["colour"], o["lines"][0]["word_colour"] = (255, 255, 255), (250, 220, 40)
        obs.append(o)
    c = L.caption_layer(obs, WORDS)
    assert c["animation"] == "karaoke" and c["highlight"] == "#fadc28" and c["colour"] == "#ffffff"


@pytest.mark.skipif(not __import__("importlib").util.find_spec("rapidocr_onnxruntime"), reason="needs rapidocr")
def test_observe_reads_burned_in_captions(tmp_path):
    video = tmp_path / "v.mp4"
    w = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 360))
    for i in range(int(25 * 6.5)):
        t = i / 25
        word = next((x["word"] for x in WORDS if x["start"] <= t < x["start"] + 0.5), "")
        f = np.full((360, 640, 3), (90, 60, 40), np.uint8)
        cv2.putText(f, "PSYCHEDELIC", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
        if word:
            cv2.putText(f, word.upper(), (250, 300), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (80, 230, 60), 3)
        w.write(f)
    w.release()
    obs, crops = L.observe(video, WORDS, log=lambda m: None)
    c = L.caption_layer(obs, WORDS)
    assert c["present"] and c["case"] == "upper" and c["animation"] == "word_pop"
    assert 0.7 < c["band"]["y0"] < c["band"]["y1"] < 0.9 and crops


def test_font_class_falls_back_to_sans(monkeypatch):
    from tools.match.common import DEFAULT_MATCH
    monkeypatch.setattr("tools.match.common.match_config", lambda: DEFAULT_MATCH)
    assert L.font_class([]) == "sans"
    crop = np.zeros((20, 60, 3), np.uint8)
    assert L.font_class([crop], ask=lambda *a, **k: {"answer": {"font_class": "serif"}}) == "serif"
    assert L.font_class([crop], ask=lambda *a, **k: {"answer": {"font_class": "comic"}}) == "sans"


def test_stable_corner_logo():
    rng = np.random.default_rng(1)
    frames = []
    for i in range(8):
        f = np.full((360, 640, 3), [int(x) for x in rng.integers(0, 255, 3)], np.uint8)
        for _ in range(6):
            cv2.circle(f, (int(rng.integers(0, 640)), int(rng.integers(0, 360))), int(rng.integers(30, 120)),
                       [int(x) for x in rng.integers(0, 255, 3)], -1)
        cv2.rectangle(f, (560, 20), (620, 60), (255, 255, 255), -1)
        cv2.putText(f, "TV", (566, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)
        frames.append(f)
    out = L.stable_regions(frames)
    assert "logo_bug" in out and out["logo_bug"]["x"] > 0.8 and "frame" not in out


def _fixture_profiles():
    profs = [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("*.json"))]
    # The committed profiles predate material: the test supplies the tags (SPEC.md Part 12 build environment).
    plan = {"clock_rick_and_morty": ("cel_animation", []), "fade_psychedelic_reel": ("illustration", ["grain", "blur"]),
            "fiveways_collage_reel": ("photo_collage", ["halftone"]), "label_showreel": ("render_3d", ["glow"])}
    for p in profs:
        material, finish = plan[p["source"]["name"]]
        for i, s in enumerate(p["shots"]):
            s["tags"] = {**s.get("tags", {}), "material": material if i % 4 else "flat_vector", "finish": finish}
    return profs


def test_look_block_from_the_fixture_profiles():
    profs = _fixture_profiles()
    look = K.build_look(profs)
    assert abs(sum(look["materials"].values()) - 1) < 0.01
    assert set(look["materials"]) == {"cel_animation", "illustration", "photo_collage", "render_3d", "flat_vector"}
    total = sum(s["dur"] for p in profs for s in p["shots"])
    for f in ("grain", "halftone", "glow"):
        share = sum(s["dur"] for p in profs for s in p["shots"] if f in s["tags"]["finish"]) / total
        assert (f in look["finish"]) == (share >= 0.25)
    assert len(look["palette"]) == 5 and all(c.startswith("#") for c in look["palette"])
    assert look["captions"] is None  # no profile was read for captions


def test_look_captions_follow_the_inspo():
    one, two = _fixture_profiles()[:2]
    one["captions"] = {"present": True, "band": {"y0": 0.7, "y1": 0.76}, "colour": "#3cdc5a", "samples": 30}
    two["captions"] = {"present": False, "reason": "no speech"}
    assert K.build_look([one])["captions"]["colour"] == "#3cdc5a"
    assert K.build_look([two])["captions"] == {"present": False, "reason": "no speech"}
