"""The side-by-side review page on a synthetic mapped session (real inspo keyframes from the bake-off)."""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import review as RV  # noqa: E402

FRAMES = Path(__file__).resolve().parents[1] / "experiments" / "describe_bakeoff" / "frames"


def session(tmp_path, n_shots=2):
    prof = tmp_path / "prof"
    (prof / "keyframes").mkdir(parents=True)
    frames = sorted(FRAMES.glob("i*.jpg"))
    shots, plan = [], []
    for i in range(n_shots):
        kf = f"keyframes/i{i}.jpg"
        shutil.copy(frames[i % len(frames)], prof / kf)
        shots.append({"id": f"i{i}", "start": 2.0 * i, "end": 2.0 * i + 2, "dur": 2.0, "keyframe": kf,
                      "tags": {"kind": "footage", "content": "single_focus", "description": f"inspo look {i}"},
                      "motion": {"move": "pan_left"}})
        plan.append({"shot_number": i + 1, "start": 2.0 * i, "end": 2.0 * i + 2.2, "audio": f"line {i}", "ref_shot": f"i{i}",
                     "ref_target_dur": 2.0, "camera": {"move": "pan_left", "amount": 0.4},
                     "visual": {"type": "REAL_FOOTAGE", "desc": f"our shot {i}"}})
    (prof / "profile.json").write_text(json.dumps({"shots": shots}))
    s = tmp_path / "sess"
    s.mkdir()
    (s / "inspo_profiles.json").write_text(json.dumps({"profiles": [str(prof)]}))
    (s / "plan.json").write_text(json.dumps({"shots": plan}))
    (s / "plan_validation.json").write_text(json.dumps({"failures": [{"problems": ["shot 2: gap of 0.40 s before shot 3 (4.20-4.60 s)"]}]}))
    (s / "assets_progress.jsonl").write_text(json.dumps({"shot_number": 1, "ok": True, "file": "x.mp4", "source": "pexels",
                                                         "short_clip": True, "speed": 0.6, "repeat": 3}) + "\n")
    ours = tmp_path / "ours.jpg"
    shutil.copy(frames[-1], ours)
    report = {"overall": 71.5, "pass": False, "sections": {"e": {"score": 80.0}},
              "shots": [{"n": i + 1, "dur": 2.2, "kind": "footage", "theme": 30.0 if i == 0 else 90.0,
                         "keyframe": str(ours)} for i in range(n_shots)]}
    return s, report


def rows(page):
    return page.split('<section class="row')[1:]


def test_final_rows_pair_both_keyframes(tmp_path):
    s, report = session(tmp_path)
    page = RV.write(s, "final", report).read_text()
    r1, r2 = rows(page)
    assert r1.count('class="kf ') == 2 and r2.count('class="kf ') == 2
    # Our keyframe is one file for both shots: embedded once. Plus two distinct inspo frames.
    assert page.count("data:image/jpeg;base64,") == 3
    assert "2.20 s vs target 2.00 s (+10%)" in r1
    assert "inspo look 0" in r1 and "our shot 0" in r1 and "pan_left (ref: pan_left)" in r1
    assert "short_clip" in r1 and "speed 0.6x, repeat 3" in r1 and "low theme" in r1
    assert "validator: gap of 0.40 s" in r2 and r2.startswith(" bad")


def test_plan_stage_shows_ref_only(tmp_path):
    s, report = session(tmp_path)
    r1 = rows(RV.write(s, "plan", report).read_text())[0]
    assert r1.count('class="kf ') == 1 and "plan stage: no media yet" in r1


def test_unmapped_plan(tmp_path):
    s, report = session(tmp_path)
    plan = json.loads((s / "plan.json").read_text())
    for sh in plan["shots"]:
        sh.pop("ref_shot")
    (s / "plan.json").write_text(json.dumps(plan))
    assert "no ref_shot (plan not mapped)" in RV.write(s, "final", report).read_text()


def test_two_hundred_shots_stay_under_5mb(tmp_path):
    s, report = session(tmp_path, n_shots=200)
    # Every shot gets its own keyframe, as in a real final edit.
    frames = sorted(FRAMES.glob("*.jpg"))
    for i, r in enumerate(report["shots"]):
        r["keyframe"] = str(frames[-(i % len(frames)) - 1])
    assert RV.write(s, "final", report).stat().st_size < 5 * 1024 * 1024


def test_animation_and_generate_preset_shown(tmp_path):
    s, report = session(tmp_path)
    prof = json.loads((s / "inspo_profiles.json").read_text())["profiles"][0]
    p = Path(prof) / "profile.json"
    data = json.loads(p.read_text())
    data["shots"][0]["tags"]["animation"] = {"reveal": "types_on", "speed": "fast"}
    p.write_text(json.dumps(data))
    plan = json.loads((s / "plan.json").read_text())
    plan["shots"][1]["visual"]["type"] = "AI_VIDEO"
    plan["shots"][1]["visual"]["generate"] = {"preset": "crash_zoom_in"}
    (s / "plan.json").write_text(json.dumps(plan))
    r1, r2 = rows(RV.write(s, "final", report).read_text())
    assert "Animates: types_on, fast" in r1 and "generated: crash_zoom_in" in r2


def test_generation_and_lipsync_failures_flagged(tmp_path):
    s, report = session(tmp_path)
    (s / "assets_progress.jsonl").write_text(json.dumps({"shot_number": 2, "ok": True, "file": "g.mp4", "source": "genvideo",
                                                         "lipsync": "no face found"}) + "\n")
    (s / "gen_video.json").write_text(json.dumps({"errors": {"1": "CUDA out of memory"}}))
    r1, r2 = rows(RV.write(s, "final", report).read_text())
    assert "generation failed: CUDA out of memory" in r1 and "lip-sync: no face found" in r2


def test_stock_picks_flagged_and_counted_in_the_header(tmp_path, monkeypatch):
    from tools.match import autopick as P
    monkeypatch.setattr(P, "assets_config", lambda: {})
    s, report = session(tmp_path, n_shots=20)
    plan = json.loads((s / "plan.json").read_text())
    plan["shots"][1]["visual"].update({"type": "MOTION_GRAPHICS", "retyped_from": "REAL_FOOTAGE", "retype_reason": "stock_cap"})
    (s / "plan.json").write_text(json.dumps(plan))
    page = RV.write(s, "final", report).read_text()
    r1, r2 = rows(page)[:2]
    assert "stock pick (pexels)" in r1 and "retyped from REAL_FOOTAGE to a graphic: stock_cap" in r2
    assert "stock: 1/20 shots (cap 3)" in page
