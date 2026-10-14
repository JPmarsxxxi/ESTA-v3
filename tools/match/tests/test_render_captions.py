"""SPEC.md Part 12 goal D: render writes the inspo's caption style, and no subtitles when it has none;
from_openreel.py carries the style to the emitter."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.opencut import from_openreel as F  # noqa: E402
from tools.render import run as R  # noqa: E402

WORDS = [{"word": w, "start": 0.4 * i, "end": 0.4 * i + 0.3, "probability": 0.9} for i, w in enumerate("same size opposite sign".split())]
CAPTIONS = {"present": True, "band": {"y0": 0.7, "y1": 0.76}, "colour": "#3cdc5a", "highlight": None, "font_class": "serif",
            "case": "lower", "words_per_chunk": 1.0, "animation": "word_pop"}


def session(tmp_path, captions):
    (tmp_path / "plan.json").write_text(json.dumps({"shots": [
        {"shot_number": 1, "start": 0.0, "end": 1.6, "visual": {"type": "REAL_FOOTAGE", "desc": "x"}}]}))
    (tmp_path / "timestamps.json").write_text(json.dumps({"segments": [
        {"start": 0, "end": 1.5, "text": "same size opposite sign", "words": WORDS}]}))
    style = {"visual_style": "mixed"}
    if captions is not ...:
        style["look"] = {"captions": captions}
    (tmp_path / "style_analysis.json").write_text(json.dumps(style))
    out = R.build(tmp_path)
    return out["project"] if "project" in out else out


def test_render_writes_the_inspo_caption_style(tmp_path):
    project = session(tmp_path, CAPTIONS)
    sub = project["timeline"]["subtitles"][0]
    assert sub["animationStyle"] == "word_pop"
    st = sub["style"]
    assert (st["color"], st["fontClass"], st["case"], st["band"]) == ("#3cdc5a", "serif", "lower", {"y0": 0.7, "y1": 0.76})
    style = F.inspo_caption_style(project["timeline"])
    assert style == {"present": True, "fontClass": "serif", "colour": "#3cdc5a", "highlight": "#3cdc5a", "case": "lower",
                     "band": {"y0": 0.7, "y1": 0.76}, "animation": "word_pop"}
    blocks = F.build_captions(project["timeline"]["subtitles"])
    assert [b["content"] for b in blocks] == ["same", "size", "opposite", "sign"]  # one word per chunk, case left to the emitter
    assert all(b["words"] == [] for b in blocks)  # word_pop: no karaoke sweep


def test_no_caption_layer_means_no_subtitles(tmp_path):
    project = session(tmp_path, {"present": False, "reason": "no speech"})
    assert project["timeline"]["subtitles"] == [] and project["timeline"]["captions"] == {"present": False}
    assert F.inspo_caption_style(project["timeline"]) == {"present": False}


def test_unread_inspo_keeps_todays_style(tmp_path):
    for captions in (..., None):
        project = session(tmp_path, captions)
        sub = project["timeline"]["subtitles"][0]
        assert sub["style"] == R.SUBTITLE_STYLE and sub["animationStyle"] == "karaoke"
        assert F.inspo_caption_style(project["timeline"]) is None
        assert F.build_captions(project["timeline"]["subtitles"])[0]["content"].isupper()
