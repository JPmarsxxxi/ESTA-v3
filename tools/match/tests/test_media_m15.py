"""SPEC.md Part 12 F5, F6, F13: the watermark check, the H.264 window cut, and the match run lock."""

import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import run as match_run  # noqa: E402
from tools.media import codec, watermark  # noqa: E402

cv2 = pytest.importorskip("cv2")


def frame(seed: int, text: str = "", at=(0.62, 0.95)):
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (360, 640, 3), dtype=np.uint8), (0, 0), 6)
    cv2.circle(img, (200 + 40 * seed, 180), 60, (230, 120, 40), -1)
    if text:
        cv2.putText(img, text, (int(at[0] * 640), int(at[1] * 360)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


needs_ocr = pytest.mark.skipif(watermark._engine() is None, reason="rapidocr not installed")


@needs_ocr
def test_url_in_corner_is_rejected():
    out = watermark.check_frames([frame(i, "www.wildfilmsindia.com") for i in range(3)])
    assert out["reject"] and "url" in out["reason"]


@needs_ocr
def test_clean_frame_is_kept():
    out = watermark.check_frames([frame(i) for i in range(3)])
    assert not out["reject"] and not out["logo"]


@needs_ocr
def test_planned_caption_in_the_band_is_kept():
    out = watermark.check_frames([frame(i, "SEE YOU.COM", at=(0.62, 0.95)) for i in range(3)], caption="see you.com")
    assert not out["reject"]


def test_offending_text_kinds():
    assert watermark.offending("Photo by Jane Doe") == "credit"
    assert watermark.offending("© 2021 Surf Mag") == "credit"
    assert watermark.offending("@surfclips") == "handle"
    assert watermark.offending("wildfilmsindia.com") == "url"
    assert watermark.offending("THE CLOCK WAS WRONG") == ""


def test_static_corner_logo_is_flagged():
    frames = []
    for i in range(3):
        f = frame(i * 3)
        f[:40, :70] = 0
        cv2.putText(f, "TV", (8, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
        frames.append(f)
    assert watermark.logo_corner(frames)
    assert not watermark.logo_corner([frame(i * 3) for i in range(3)])


def _clip(path: Path, vcodec: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=6",
                    *vcodec, str(path)], check=True)


def test_vp9_pick_gets_an_h264_window(tmp_path):
    src = tmp_path / "clip.webm"
    _clip(src, ["-c:v", "libvpx-vp9", "-b:v", "200k"])
    cut, a, b = codec.h264_window(src, 2.0, 3.5, 7)
    assert cut.name == "clip_h264_7.mp4" and codec.video_codec(cut) == "h264"
    assert (a, b) == (0.5, 2.0)  # the cut starts half a second before the old in point
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(cut)],
                               capture_output=True, text=True).stdout)
    assert abs(dur - 2.5) < 0.15


def test_h264_pick_is_untouched(tmp_path):
    src = tmp_path / "clip.mp4"
    _clip(src, ["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    assert codec.h264_window(src, 1.0, 2.0, 3) == (src, 1.0, 2.0)


def test_second_match_run_waits(tmp_path):
    lock = tmp_path / "match.lock"
    holder = subprocess.Popen([sys.executable, "-c", (
        "import sys, time; sys.path.insert(0, %r)\n"
        "from tools.match.run import run_lock\n"
        "with run_lock(__import__('pathlib').Path(%r), log=lambda m: None):\n"
        "    print('held', flush=True); time.sleep(1.5)\n") % (str(Path(__file__).resolve().parents[3]), str(lock))],
        stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    waited, t0 = [], time.monotonic()
    with match_run.run_lock(lock, log=waited.append, poll=0.1):
        took = time.monotonic() - t0
    holder.wait(5)
    assert waited and took > 0.8


def test_lock_is_free_when_nobody_holds_it(tmp_path):
    done = threading.Event()
    with match_run.run_lock(tmp_path / "m.lock", log=lambda m: None, poll=0.05):
        done.set()
    assert done.is_set()
