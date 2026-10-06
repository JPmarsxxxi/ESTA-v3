"""Render mutes footage per clip unless the shot keeps its own sound (SPEC.md Part 7, decision 7)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.render import run as R  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                  reason="needs ffmpeg")


def build(tmp_path, keep_audio):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=64x64:rate=25", "-y", str(clip)],
                   check=True)
    shots = [{"shot_number": 1, "start": 0.0, "end": 2.0, "visual": {"type": "REAL_FOOTAGE", "desc": "x"}},
             {"shot_number": 2, "start": 2.0, "end": 4.0,
              "visual": {"type": "REAL_FOOTAGE", "desc": "y", **({"keep_audio": True} if keep_audio else {})}}]
    (tmp_path / "plan.json").write_text(json.dumps({"shots": shots}))
    rows = [{"shot_number": n, "ok": True, "file": str(clip), "asset_type": "video", "in_point": 0} for n in (1, 2)]
    (tmp_path / "assets_progress.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = R.build(tmp_path)
    project = out["project"] if "project" in out else out
    return next(t for t in project["timeline"]["tracks"] if t["name"] == "Main")


@needs_ffmpeg
def test_keep_audio_clip_plays_and_the_rest_are_muted(tmp_path):
    main = build(tmp_path, keep_audio=True)
    vol = {c["id"]: c["volume"] for c in main["clips"]}
    assert vol == {"clip-shot-1": 0, "clip-shot-2": 1} and main["muted"] is False


@needs_ffmpeg
def test_without_keep_audio_every_clip_and_the_lane_are_muted(tmp_path):
    main = build(tmp_path, keep_audio=False)
    assert {c["volume"] for c in main["clips"]} == {0} and main["muted"] is True
