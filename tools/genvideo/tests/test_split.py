"""Two-run split (SPEC.md Part 6, M9.3): push partitions the slots, apply merges both halves, without Kaggle."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genvideo import run as G  # noqa: E402

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
                                reason="needs ffmpeg")


@pytest.fixture
def make_session(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_ffmpeg", lambda *a: subprocess.run(["ffmpeg", "-v", "error", *a], capture_output=True, text=True))
    monkeypatch.setattr(G, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(G, "kaggle_username", lambda: "me")

    def make(durations):
        s = tmp_path / f"split-{len(durations)}"
        s.mkdir()
        t, shots = 0.0, []
        for n, d in enumerate(durations, 1):
            shots.append({"shot_number": n, "start": t, "end": t + d, "visual": {"type": "AI_VIDEO", "desc": f"shot {n}"}})
            t += d
        (s / "plan.json").write_text(json.dumps({"shots": shots}))
        return s
    return make


def dry_run(session, capsys, split=2):
    G.cmd_push(argparse.Namespace(session=str(session), model="anisora", accelerator="t4", preset="static",
                                  style="cinematic", shots="", chain=1, seed_from_assets=False, dry_run=True,
                                  lipsync="off", ref_strength=1.0, split=split, half="",
                                  frames=0, fps=0, width=0, height=0, steps=0, guidance=0.0))
    return json.loads(capsys.readouterr().out)


def test_five_slots_split_evenly(make_session, capsys):
    out = dry_run(make_session([0.9, 3.2, 3.4, 1.9, 1.8]), capsys)
    a, b = out["kernels"]
    assert a["kernel"] == "me/esta-gen-split-5" and b["kernel"] == "me/esta-gen-split-5-b"
    assert sorted(a["slots"] + b["slots"], key=int) == ["1", "2", "3", "4", "5"] and not set(a["slots"]) & set(b["slots"])
    biggest = max(s["frames"] for s in out["slots"])
    assert abs(a["frames"] - b["frames"]) <= biggest


def test_three_slots_stay_one_run(make_session, capsys):
    assert len(dry_run(make_session([1.0, 2.0, 3.0]), capsys)["kernels"]) == 1
    assert len(dry_run(make_session([1.0, 2.0, 3.0, 4.0]), capsys, split=1)["kernels"]) == 1


def stub_half(out_dir, keys):
    out_dir.mkdir(parents=True)
    results = {}
    for k in keys:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=832x480:rate=16",
                        "-t", "2", str(out_dir / f"gen_{k}.mp4")], check=True)
        results[k] = {"file": f"gen_{k}.mp4", "frames": 32, "fps": 16, "preset": "static", "shot_number": int(k)}
    (out_dir / "gen_results.json").write_text(json.dumps({"results": results, "errors": {}}))


def write_state(session, halves):
    G._state_path(session).write_text(json.dumps({"kernel": "me/a", "kernels": [
        {"half": h, "kernel": f"me/{h}", "slots": keys} for h, keys in halves]}))


def test_apply_merges_both_halves(make_session, capsys):
    s = make_session([2, 2, 2, 2])
    write_state(s, [("a", ["1", "3"]), ("b", ["2", "4"])])
    stub_half(s / "assets" / "gen_out", ["1", "3"])
    stub_half(s / "assets" / "gen_out_b", ["2", "4"])
    G.cmd_apply(argparse.Namespace(session=str(s), kernel="", output_dir="", skip_download=True))
    out = json.loads(capsys.readouterr().out)
    assert out["generated"] == 4 and out["missing"] == []
    feed = [json.loads(line) for line in (s / "assets_progress.jsonl").read_text().splitlines()]
    assert sorted(r["shot_number"] for r in feed) == [1, 2, 3, 4]


def test_apply_publishes_the_half_that_finished(make_session, capsys):
    s = make_session([2, 2, 2, 2])
    write_state(s, [("a", ["1", "3"]), ("b", ["2", "4"])])
    stub_half(s / "assets" / "gen_out", ["1", "3"])
    G.cmd_apply(argparse.Namespace(session=str(s), kernel="", output_dir="", skip_download=True))
    out = json.loads(capsys.readouterr().out)
    assert out["generated"] == 2 and out["missing"] == ["2", "4"]
    assert set(out["errors"]) == {"2", "4"}


def test_status_names_the_half_that_never_started(make_session, capsys, monkeypatch):
    s = make_session([2, 2, 2, 2])
    G._state_path(s).write_text(json.dumps({"kernel": "me/a", "kernels": [
        {"half": "a", "kernel": "me/a", "slots": ["1", "3"], "ok": True},
        {"half": "b", "kernel": "me/b", "slots": ["2", "4"], "ok": False}]}))
    polled = []
    monkeypatch.setattr(G, "kernel_status", lambda ref: (polled.append(ref), ("running", ""))[1])
    G.cmd_status(argparse.Namespace(session=str(s), kernel=""))
    out = json.loads(capsys.readouterr().out)
    assert out["not_started"] == ["b"] and polled == ["me/a"] and out["state"] == "running"
    assert {k["half"]: k["state"] for k in out["kernels"]} == {"a": "running", "b": "not_started"}


def test_reapplying_publishes_nothing_twice(make_session, capsys):
    s = make_session([2, 2, 2, 2])
    write_state(s, [("a", ["1", "3"]), ("b", ["2", "4"])])
    stub_half(s / "assets" / "gen_out", ["1", "3"])
    stub_half(s / "assets" / "gen_out_b", ["2", "4"])
    args = argparse.Namespace(session=str(s), kernel="", output_dir="", skip_download=True)
    G.cmd_apply(args)
    capsys.readouterr()
    rows = (s / "assets_progress.jsonl").read_text().splitlines()
    G.cmd_apply(args)
    out = json.loads(capsys.readouterr().out)
    assert out["generated"] == 0 and sorted(out["already_published"]) == ["1", "2", "3", "4"]
    assert (s / "assets_progress.jsonl").read_text().splitlines() == rows
