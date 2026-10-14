"""SPEC.md Part 12 F11: build.py flags motion-graphics text that crosses the caption band."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.motiongraphics import build as B  # noqa: E402


def test_band_crossings_pure():
    boxes = [{"text": "IN BAND", "y0": 1250, "y1": 1330}, {"text": "TOP", "y0": 200, "y1": 290},
             {"text": "IN BAND", "y0": 1255, "y1": 1335}]
    assert B.band_crossings(boxes, (0.6, 0.68), 1920) == [{"text": "IN BAND", "y0": 1250, "y1": 1330}]


def test_band_from_slots_json(tmp_path):
    (tmp_path / "slots.json").write_text(json.dumps({"caption_band": {"present": True, "y0": 0.1, "y1": 0.2}}))
    assert B.caption_band(tmp_path) == (0.1, 0.2)
    (tmp_path / "slots.json").write_text(json.dumps({"caption_band": {"present": False}}))
    assert B.caption_band(tmp_path) is None


def test_default_band_is_where_our_captions_sit(tmp_path):
    y0, y1 = B.caption_band(tmp_path)
    assert 0.55 < y0 < 0.72 < y1 < 0.85


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "node_modules" / "hyperframes").exists(),
                    reason="needs node and the repo's node_modules")
def test_build_flags_a_text_box_in_the_band(tmp_path):
    kit = tmp_path / "assets" / "mg" / "_kit"
    (kit / "slots").mkdir(parents=True)
    (kit / "surface.css").write_text(".t { position: absolute; left: 100px; font-size: 90px; color: #fff; }")
    (tmp_path / "slots.json").write_text(json.dumps({"caption_band": {"present": True, "y0": 0.6, "y1": 0.68}}))
    (kit / "slots" / "1.json").write_text(json.dumps({"key": "1", "duration": 2,
        "body": "<div class='t' style='top:1200px'>94%</div><div class='t' style='top:200px'>COST</div>", "timeline": ""}))
    r = subprocess.run([sys.executable, str(ROOT / "tools/motiongraphics/build.py"), "--session", str(tmp_path)],
                       capture_output=True, text=True, timeout=300)
    out = json.loads(r.stdout)
    if out.get("band_check"):
        pytest.skip(out["band_check"])
    assert out["band_crossings"] == ["1"]
    assert [h["text"] for h in out["slots"][0]["crosses_caption_band"]] == ["94%"]
