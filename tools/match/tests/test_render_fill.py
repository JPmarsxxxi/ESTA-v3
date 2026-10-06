"""Render honours auto-pick's fill (speed, repeat) on a real ffmpeg-made clip."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.render import run as R  # noqa: E402


def session(tmp_path, row):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=25", "-y", str(clip)],
                   check=True)
    plan = {"shots": [{"shot_number": 1, "start": 0.0, "end": 4.0, "visual": {"type": "REAL_FOOTAGE", "desc": "x"}},
                      {"shot_number": 2, "start": 4.0, "end": 6.0, "visual": {"type": "REAL_FOOTAGE", "desc": "y"}}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    rows = [{"shot_number": 1, "ok": True, "file": str(clip), "asset_type": "video", "in_point": 0, **row},
            {"shot_number": 2, "ok": True, "file": str(clip), "asset_type": "video", "in_point": 0}]
    (tmp_path / "assets_progress.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path


def main_clips(project):
    return next(t for t in project["timeline"]["tracks"] if t["name"] == "Main")


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="needs ffmpeg")
def test_repeat_and_speed_cover_the_shot(tmp_path):
    out = R.build(session(tmp_path, {"speed": 0.6, "repeat": 3}))
    project = out["project"] if "project" in out else out
    track = main_clips(project)
    shot1 = [c for c in track["clips"] if c["id"].split("-r")[0] == "clip-shot-1"]
    assert [c["id"] for c in shot1] == ["clip-shot-1", "clip-shot-1-r2", "clip-shot-1-r3"]
    assert abs(sum(c["duration"] for c in shot1) - 4.0) < 1e-6
    assert all(abs(b["startTime"] - (a["startTime"] + a["duration"])) < 1e-6 for a, b in zip(shot1, shot1[1:]))
    for c in shot1:
        assert c["speed"] == 0.6
        assert abs((c["outPoint"] - c["inPoint"]) - c["duration"] * 0.6) < 0.01
    pairs = {(t["clipAId"], t["clipBId"]) for t in track.get("transitions", [])}
    assert not any(a.startswith("clip-shot-1") and b.startswith("clip-shot-1") for a, b in pairs)


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="needs ffmpeg")
def test_plain_clip_unchanged(tmp_path):
    out = R.build(session(tmp_path, {}))
    project = out["project"] if "project" in out else out
    shot2 = [c for c in main_clips(project)["clips"] if c["id"] == "clip-shot-2"]
    assert len(shot2) == 1 and "speed" not in shot2[0]
