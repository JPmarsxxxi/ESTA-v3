"""Render turns a mapped shot's camera move and fades into keyframes (SPEC.md Part 3, decision 13)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.render import run as R  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")


def build(tmp_path, shots, rows):
    clip, still = tmp_path / "clip.mp4", tmp_path / "still.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=10:size=64x64:rate=25", "-y", str(clip)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64", "-frames:v", "1", "-y", str(still)], check=True)
    (tmp_path / "plan.json").write_text(json.dumps({"shots": shots}))
    files = {"video": clip, "image": still}
    (tmp_path / "assets_progress.jsonl").write_text("\n".join(
        json.dumps({"shot_number": n, "ok": True, "file": str(files[t]), "asset_type": t, "in_point": 0, **extra})
        for n, t, extra in rows) + "\n")
    out = R.build(tmp_path)
    project = out.get("project", out)
    return {c["id"]: c for t in project["timeline"]["tracks"] for c in t.get("clips", []) if c["id"].startswith("clip-shot")}, project


def shot(n, a, b, **extra):
    return {"shot_number": n, "start": a, "end": b, "visual": {"type": "REAL_FOOTAGE", "desc": "x"}, **extra}


def props(clip):
    return {k["property"] for k in clip["keyframes"]}


@pytest.mark.parametrize("move,channels", [
    ("push_in", {"scale.x", "scale.y"}),
    ("punch_in", {"scale.x", "scale.y"}),
    ("pan_right", {"scale.x", "scale.y", "position.x"}),
    ("tilt_up", {"scale.x", "scale.y", "position.y"}),
    ("shake", {"scale.x", "scale.y", "position.x", "position.y", "rotation"}),
])
def test_moves_to_channels(tmp_path, move, channels):
    clips, _ = build(tmp_path, [shot(1, 0, 3, camera={"move": move, "amount": 0.5})], [(1, "video", {})])
    assert props(clips["clip-shot-1"]) == channels


def test_pan_direction_and_cover(tmp_path):
    clips, _ = build(tmp_path, [shot(1, 0, 3, camera={"move": "pan_right", "amount": 1.0})], [(1, "video", {})])
    xs = [k for k in clips["clip-shot-1"]["keyframes"] if k["property"] == "position.x"]
    scale = next(k["value"] for k in clips["clip-shot-1"]["keyframes"] if k["property"] == "scale.x")
    assert xs[0]["value"] > 0 > xs[-1]["value"]  # picture moves left as the camera pans right
    assert scale >= 1 + 2 * abs(xs[0]["value"]) - 1e-6  # never shows an edge


def test_static_camera_replaces_ken_burns_and_stills_keep_it_otherwise(tmp_path):
    shots = [shot(1, 0, 3, camera={"move": "static", "amount": 0}), {**shot(2, 3, 6), "visual": {"type": "REAL_IMAGE", "desc": "y"}}]
    clips, _ = build(tmp_path, shots, [(1, "image", {}), (2, "image", {})])
    assert clips["clip-shot-1"]["keyframes"] == []
    assert props(clips["clip-shot-2"]) == {"scale.x", "scale.y"}  # R1 Ken Burns


def test_fades_on_shot_edges_only(tmp_path):
    shots = [shot(1, 0, 4, transition_in="fade_black", transition_out="fade_black"), shot(2, 4, 6, transition_in="cut")]
    clips, project = build(tmp_path, shots, [(1, "video", {"repeat": 2}), (2, "video", {})])
    first, second = clips["clip-shot-1"], clips["clip-shot-1-r2"]
    assert [k["value"] for k in first["keyframes"] if k["property"] == "opacity"] == [0.0, 1.0]
    assert [k["value"] for k in second["keyframes"] if k["property"] == "opacity"] == [1.0, 0.0]
    main = next(t for t in project["timeline"]["tracks"] if t["name"] == "Main")
    assert main.get("transitions", []) == []  # a mapped plan carries its own transitions


def test_very_high_energy_hard_cuts(tmp_path):
    (tmp_path / "style_analysis.json").write_text(json.dumps({"energy_level": "very-high"}))
    _, project = build(tmp_path, [shot(1, 0, 2), shot(2, 2, 4)], [(1, "video", {}), (2, "video", {})])
    main = next(t for t in project["timeline"]["tracks"] if t["name"] == "Main")
    assert main.get("transitions", []) == []
