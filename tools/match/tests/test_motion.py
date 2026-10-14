"""motion.py on synthetic ffmpeg clips made from one still frame (a moving source would read as a move itself)."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match.motion import classify, fade_kind, measure  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")

CLIPS = {
    "push_in": ["-vf", "zoompan=z='1+0.003*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=640x360:fps=25", "-frames:v", "75"],
    "push_out": ["-vf", "zoompan=z='1.4-0.003*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=640x360:fps=25", "-frames:v", "75"],
    "pan_right": ["-framerate", "25", "-vf", "crop=960:540:x='t*150':y=270,scale=640:360", "-t", "3"],
    "tilt_up": ["-framerate", "25", "-vf", "crop=960:540:x=480:y='270-t*60',scale=640:360", "-t", "3"],
    "static": ["-framerate", "25", "-vf", "crop=960:540:x=480:y=270,scale=640:360", "-t", "3"],
    "fades": ["-framerate", "25", "-vf", "crop=960:540:x=480:y=270,scale=640:360,fade=in:0:10,fade=out:55:10", "-t", "3"],
}


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("motion")
    still = d / "still.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=size=1920x1080", "-frames:v", "1", str(still)], check=True)
    out = {}
    for name, args in CLIPS.items():
        out[name] = d / f"{name}.mp4"
        pre = args[:2] if args[0] == "-framerate" else []
        rest = args[2:] if pre else args
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", *pre, "-i", str(still), *rest, "-pix_fmt", "yuv420p",
                        str(out[name])], check=True)
    return out


@pytest.mark.parametrize("move", ["push_in", "push_out", "pan_right", "tilt_up", "static"])
def test_moves(clips, move):
    assert measure(clips[move], 0.0, 3.0, 25.0)["move"] == move


def test_fades(clips):
    m = measure(clips["fades"], 0.0, 3.0, 25.0)
    assert (m["fade_in"], m["fade_out"]) == ("black", "black")
    assert measure(clips["static"], 0.0, 3.0, 25.0)["fade_in"] == "none"


def test_punch_in_and_shake_from_steps():
    assert classify([(1.0, 0, 0), (1.18, 0, 0), (1.0, 0, 0)], dt=0.2)["move"] == "punch_in"
    jitter = [(1.0, 0.04, 0.0), (1.0, -0.04, 0.0)] * 4
    assert classify(jitter, dt=0.3)["move"] == "shake"
    assert classify([None, None], dt=0.3) == {"move": "static", "amount": 0.0}


def test_fade_kind_white_and_flat():
    assert fade_kind([250, 200, 150]) == "white"
    assert fade_kind([40, 41, 40]) == "none"


def test_punch_in_inside_a_long_shot():
    # Samples 0.5 s apart: one step holds an 18 % jump, the rest barely move.
    steps = [(1.0, 0, 0), (1.01, 0, 0), (1.18, 0, 0), (1.0, 0, 0), (1.01, 0, 0)]
    assert classify(steps, dt=0.5)["move"] == "punch_in"
    # A smooth push of the same total zoom is a push, not a punch.
    assert classify([(1.045, 0, 0)] * 5, dt=0.5)["move"] == "push_in"


def test_punch_clip(tmp_path):
    still = tmp_path / "still.png"
    clip = tmp_path / "punch.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=size=1920x1080", "-frames:v", "1", str(still)], check=True)
    # 6 s shot: still until 3 s, then a 20 % zoom in 4 frames, then still.
    z = "if(lt(on,75),1,if(lt(on,79),1+0.05*(on-74),1.2))"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(still), "-vf",
                    f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=640x360:fps=25", "-frames:v", "150",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    assert measure(clip, 0.0, 6.0, 25.0)["move"] == "punch_in"


def _drawn(path: Path, moving: bool) -> Path:
    """A cartoon-like clip: a flat background with a drawn circle that moves (or doesn't), camera locked off."""
    import cv2
    import numpy as np
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 360))
    bg = np.full((360, 640, 3), (60, 140, 200), np.uint8)
    cv2.rectangle(bg, (0, 260), (640, 360), (40, 90, 40), -1)
    for i in range(75):
        f = bg.copy()
        x = 120 + (5 * i if moving else 0)
        cv2.circle(f, (x, 180), 60, (20, 200, 240), -1)
        cv2.circle(f, (x, 180), 60, (0, 0, 0), 4)
        w.write(f)
    w.release()
    return path


def test_subject_motion_moving_circle_is_high(tmp_path):
    m = measure(_drawn(tmp_path / "moving.mp4", True), 0.0, 3.0, 25.0)
    assert m["subject_motion"] == "high" and m["move"] == "static"


def test_subject_motion_pan_over_a_still_is_none(clips):
    m = measure(clips["pan_right"], 0.0, 3.0, 25.0)
    assert m["move"] == "pan_right" and m["subject_motion"] == "none"


def test_subject_motion_locked_off_still_is_none(tmp_path):
    assert measure(_drawn(tmp_path / "still.mp4", False), 0.0, 3.0, 25.0)["subject_motion"] == "none"


def test_still_with_high_subject_motion_is_reclassified():
    from tools.match.motion import reclassify
    shots = [{"tags": {"kind": "still", "material": "cel_animation"}, "motion": {"subject_motion": "high"}},
             {"tags": {"kind": "still"}, "motion": {"subject_motion": "low"}},
             {"tags": {"kind": "graphic"}, "motion": {"subject_motion": "high"}}]
    assert reclassify(shots) == 1
    assert shots[0]["tags"] == {"kind": "footage", "kind_described": "still", "material": "cel_animation"}
    assert shots[1]["tags"]["kind"] == "still" and shots[2]["tags"]["kind"] == "graphic"
