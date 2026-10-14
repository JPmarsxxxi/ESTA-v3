"""SPEC.md Part 12 F4: the idea-first planner emits every visual type, material and lane, and the ai_video rule."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import validate_plan  # noqa: E402
from tools.plan import ideas, lanes  # noqa: E402

SCRIPT = ("Every five minutes the crowd bets on Bitcoin . And on paper the crowd is reliably wrong . "
          "I read it through a poker book . Then the edge flipped .")
REFS = {
    "a0": {"kind": "footage", "material": "live_action", "subject_motion": "low", "motion": {"move": "push_in", "amount": 0.1}},
    "a1": {"kind": "graphic", "material": "render_3d", "subject_motion": "none", "ai_preset": "static"},
    "a2": {"kind": "footage", "material": "illustration", "ai_look": True, "subject_motion": "high", "ai_preset": "push_in"},
    "a3": {"kind": "graphic", "material": "kinetic_type", "text_extra": True},
}


def session(tmp_path):
    words, t = [], 0.0
    for w in SCRIPT.split():
        if w == ".":
            words[-1]["word"] += "."
            t += 0.3
            continue
        words.append({"word": w, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.4
    end = words[-1]["end"]
    (tmp_path / "timestamps.json").write_text(json.dumps({"segments": [{"words": words}]}))
    (tmp_path / "audio_metadata.json").write_text(json.dumps({"duration_seconds": end}))
    q = end / 4
    slots = [{"slot": i + 1, "start": round(i * q, 3), "end": round((i + 1) * q, 3), "target_dur": round(q, 3),
              "ref_shot": f"a{i}"} for i in range(4)]
    (tmp_path / "slots.json").write_text(json.dumps({"slots": slots, "refs": REFS}))
    (tmp_path / "ideas.txt").write_text(
        "@Every five minutes the crowd bets on Bitcoin.|crowd betting\n"
        "@And on paper the crowd is reliably wrong.|crowd off a cliff\n"
        "@I read it through a poker book.|poker book\n"
        "@Then the edge flipped.|mirror flip\n")
    return tmp_path


def visuals(tmp_path, skel):
    out = []
    for k in sorted({s["idea"] for s in skel}, key=int):
        out.append(f"@{k}")
        for s in [s for s in skel if s["idea"] == k]:
            out.append(f"|m||{s['subject']} step {s['step']}|youtube:{s['subject']} clip;{s['subject']} b roll")
    (tmp_path / "visuals.txt").write_text("\n".join(out))


def test_cut_and_build_route_by_material(tmp_path):
    s = session(tmp_path)
    assert ideas.cut(s)["ideas"] == 4
    skel = json.loads((s / "ideas_skeleton.json").read_text())
    visuals(s, skel)
    out = ideas.build(s)
    shots = json.loads((s / "plan.json").read_text())["shots"]
    assert out["shots"] == len(shots) >= 4
    for sh in shots:
        v = sh["visual"]
        assert v["material"] in lanes.MATERIALS and v["lane"] in lanes.LANES
        assert v["type"] in lanes.LANE_TYPES[v["lane"]]
    by_ref = {sh["ref_shot"]: sh["visual"] for sh in shots}
    assert by_ref["a2"]["type"] == "AI_VIDEO" and by_ref["a2"]["generate"]["preset"] == "push_in"  # ai_look ref
    assert by_ref["a1"]["lane"] == "genimage" and by_ref["a1"]["type"] == "MOTION_GRAPHICS"
    assert by_ref["a0"]["lane"] == "footage" and by_ref["a0"]["type"] == "REAL_FOOTAGE"
    assert by_ref["a3"]["lane"] == "hyperframes"
    words = validate_plan.load_words(json.loads((s / "timestamps.json").read_text()))
    problems = validate_plan.check(shots, words, validate_plan.voice_end(s, words))["failures"]
    assert not [p for f in problems for p in f["problems"] if "cut" in p or "gap" in p or "starts at" in p]


def test_typed_line_that_cant_make_the_material_carries_a_fallback():
    v, _, _ = ideas.visual_for("F|m||a glass sphere", REFS["a1"], "sphere", "fair_use_ok")
    assert v["lane"] == "footage" and "can't make render_3d" in v["lane_fallback"]
    v, _, _ = ideas.visual_for("G|m||a glass sphere", REFS["a1"], "sphere", "fair_use_ok")
    assert v["lane"] == "genimage" and "lane_fallback" not in v  # a generated still animated in HyperFrames


def test_reaction_line_may_use_giphy():
    v, _, _ = ideas.visual_for("F|l|R|shocked face", REFS["a0"], "shock", "fair_use_ok")
    assert v["desc"].startswith("Reaction:") and v["search_sources"][0]["source"] == "giphy"
    assert not validate_plan.sourcing_problems({"shot_number": 1, "visual": v})


def test_cel_animation_never_becomes_a_still():
    ref = {"kind": "still", "material": "cel_animation", "subject_motion": "low"}
    assert lanes.route(ref, "fair_use_ok")["type"] == "REAL_FOOTAGE"
    assert lanes.route(ref, "free_only")["type"] == "AI_VIDEO"
