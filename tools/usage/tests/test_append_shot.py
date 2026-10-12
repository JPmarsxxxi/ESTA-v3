"""tools/plan/append_shot.py: append-only plan streaming and plan.json assembly."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "plan" / "append_shot.py"


def _run(mode, session, stdin, *extra):
    return subprocess.run([sys.executable, str(TOOL), mode, "--session", str(session), *extra], input=stdin,
                          capture_output=True, text=True, encoding="utf-8")


def _shot(n, desc="x"):
    return {"shot_number": n, "audio": "line", "visual": {"type": "REAL_FOOTAGE", "desc": desc}}


def test_append_one_array_and_jsonl(tmp_path):
    assert _run("append", tmp_path, json.dumps(_shot(1))).returncode == 0
    assert _run("append", tmp_path, json.dumps([_shot(2), _shot(3)])).returncode == 0
    assert _run("append", tmp_path, json.dumps(_shot(4)) + "\n" + json.dumps(_shot(5)) + "\n").returncode == 0
    lines = (tmp_path / "plan_progress.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["shot_number"] for x in lines] == [1, 2, 3, 4, 5]


def test_duplicate_refused_then_replaced_in_place(tmp_path):
    _run("append", tmp_path, json.dumps([_shot(1), _shot(2)]))
    r = _run("append", tmp_path, json.dumps(_shot(1, "new")))
    assert r.returncode == 1 and "--replace" in r.stderr
    assert _run("append", tmp_path, json.dumps(_shot(1, "new")), "--replace").returncode == 0
    rows = [json.loads(x) for x in (tmp_path / "plan_progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(s["shot_number"], s["visual"]["desc"]) for s in rows] == [(1, "new"), (2, "x")]


def test_rejects_non_shot(tmp_path):
    r = _run("append", tmp_path, '{"shot_number": "1", "visual": {}}')
    assert r.returncode == 1 and not (tmp_path / "plan_progress.jsonl").exists()


def test_build_assembles_plan_in_shot_order(tmp_path):
    _run("append", tmp_path, json.dumps([_shot(2), _shot(1)]))
    header = {"timing_source": "estimated", "video_metadata": {"title": "t"}, "editing_notes": {"method": "m"}}
    assert _run("build", tmp_path, json.dumps(header)).returncode == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert [s["shot_number"] for s in plan["shots"]] == [1, 2]
    assert plan["video_metadata"] == {"title": "t", "shot_count": 2}
    assert plan["session_id"] == tmp_path.name and plan["generated_at"]
