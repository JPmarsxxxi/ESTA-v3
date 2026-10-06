"""apply's clip check (SPEC.md Part 6, M9.4): dark or collapsed clips fall back to their keyframe as a still."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.genvideo import run as G  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")
W, H, FPS = 416, 240, 16


def scene(seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 140, np.uint8)
    for _ in range(12):
        x, y = int(rng.integers(0, W - 60)), int(rng.integers(0, H - 60))
        cv2.rectangle(img, (x, y), (x + 60, y + 40), tuple(int(c) for c in rng.integers(30, 255, 3)), -1)
    return img


def write(path, frames):
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for f in frames:
        out.write(f)
    out.release()
    return path


def zoom(img, z):
    m = cv2.getRotationMatrix2D((W / 2, H / 2), 0, z)
    return cv2.warpAffine(img, m, (W, H), borderMode=cv2.BORDER_REFLECT)


def test_fade_to_black_fails_dark(tmp_path):
    base = scene()
    clip = write(tmp_path / "fade.mp4", [(base * (1 - i / 47)).astype(np.uint8) for i in range(48)])
    assert G.check_clip(clip, 3.0) == "dark"


def test_cut_to_unrelated_content_fails_collapse(tmp_path):
    # The real melts anti-correlated with frame 0 (-0.13, -0.31); the tonal inverse reproduces that.
    a = scene(1)
    clip = write(tmp_path / "melt.mp4", [a] * 20 + [255 - a] * 28)
    assert G.check_clip(clip, 3.0) == "collapse"


def test_steady_zoom_passes(tmp_path):
    base = scene(3)
    clip = write(tmp_path / "zoom.mp4", [zoom(base, 1 + 0.25 * i / 47) for i in range(48)])
    assert G.check_clip(clip, 3.0) == ""


BAKE = ROOT / "tools" / "genvideo" / "bakeoff" / "work"
LTX = ROOT / "sessions" / "m6-first-minute-test" / "assets" / "source_pool"


@pytest.mark.skipif(not (BAKE / "inputs.json").exists() or not (LTX / "gen_7.mp4").exists(),
                    reason="bake-off clips are local only (gitignored)")
def test_calibrated_on_the_bakeoff_clips():
    for inputs, outs in ((BAKE / "inputs.json", ("out_anisora", "out_wan5b")),
                         (BAKE / "real" / "inputs.json", ("real/out_anisora", "real/out_wan5b"))):
        for s in json.loads(inputs.read_text(encoding="utf-8")):
            for o in outs:
                clip = BAKE / o / f"bo_{s['key']}.mp4"
                assert G.check_clip(clip, float(s["seconds"])) == "", clip
    seconds = {s["key"]: float(s["seconds"]) for s in json.loads((BAKE / "inputs.json").read_text(encoding="utf-8"))}
    assert G.check_clip(LTX / "gen_7.mp4", seconds["7"]) == "dark"
    assert G.check_clip(LTX / "gen_8.mp4", seconds["8"]) == "collapse"


def test_failed_slot_publishes_its_keyframe_and_flags_it(tmp_path, capsys):
    s = tmp_path / "check-2026-10-04"
    s.mkdir()
    (s / "plan.json").write_text(json.dumps({"shots": [
        {"shot_number": 1, "start": 0, "end": 3, "camera": {"move": "push_in", "amount": 0.5},
         "visual": {"type": "AI_VIDEO", "desc": "a"}},
        {"shot_number": 2, "start": 3, "end": 6, "visual": {"type": "AI_VIDEO", "desc": "b"}}]}))
    out = s / "assets" / "gen_out"
    out.mkdir(parents=True)
    base = scene(5)
    write(out / "gen_1.mp4", [(base * (1 - i / 47)).astype(np.uint8) for i in range(48)])
    write(out / "gen_2.mp4", [zoom(base, 1 + 0.2 * i / 47) for i in range(48)])
    cv2.imwrite(str(out / "kf_1.png"), base)
    results = {k: {"file": f"gen_{k}.mp4", "frames": 48, "fps": FPS, "preset": "push_in", "shot_number": int(k)}
               for k in ("1", "2")}
    (out / "gen_results.json").write_text(json.dumps({"results": results, "errors": {}}))
    G._state_path(s).write_text(json.dumps({"kernel": "me/a", "kernels": [{"half": "a", "kernel": "me/a", "slots": ["1", "2"]}]}))
    G.cmd_apply(argparse.Namespace(session=str(s), kernel="", output_dir="", skip_download=True))
    json.loads(capsys.readouterr().out)
    rows = {r["shot_number"]: r for r in map(json.loads, (s / "assets_progress.jsonl").read_text().splitlines())}
    assert rows[1]["gen_check"] == "dark" and rows[1]["asset_type"] == "image" and rows[1]["file"].endswith("genkf_1.png")
    assert rows[2]["asset_type"] == "video" and "gen_check" not in rows[2]

    from tools.match import review
    assert "gen_check" in Path(review.__file__).read_text(encoding="utf-8")
