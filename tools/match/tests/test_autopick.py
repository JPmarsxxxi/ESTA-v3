"""Auto-pick filters, ref-shot likeness and the Haiku judge, without models or network."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import autopick as P  # noqa: E402
from tools.match import describe as D  # noqa: E402
from tools.match.common import DEFAULT_MATCH  # noqa: E402


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(P, "match_config", lambda: DEFAULT_MATCH)


def shot(typ="REAL_FOOTAGE", dur=4.0):
    return {"shot_number": 1, "start": 10.0, "end": 10.0 + dur, "visual": {"type": typ}}


def video(i, length, source="pexels"):
    return {"file": f"v{i}.mp4", "asset_type": "video", "source": source, "source_duration": length, "in_point": 0.0}


def image(i):
    return {"file": f"p{i}.jpg", "asset_type": "image", "source": "pexels", "source_duration": 0}


def test_short_videos_never_chosen_when_a_long_one_exists():
    kept, short = P.filter_candidates(shot(), [video(1, 2.0), video(2, 6.0), video(3, 3.9)])
    assert [c["file"] for c in kept] == ["v2.mp4"] and not short


def test_in_point_counts_against_length():
    c = {**video(1, 6.0, "youtube"), "in_point": 3.0}
    assert P.filter_candidates(shot(), [c]) == ([c], True)


def test_longest_flagged_when_none_fills_the_shot():
    kept, short = P.filter_candidates(shot(), [video(1, 2.0), video(2, 3.0)])
    assert [c["file"] for c in kept] == ["v2.mp4"] and short


def test_kind_mismatch_never_chosen():
    assert P.filter_candidates(shot(), [image(1)]) == ([], False)
    kept, _ = P.filter_candidates(shot("REAL_IMAGE"), [image(1), video(2, 9.0)])
    assert [c["file"] for c in kept] == ["p1.jpg"]


def test_giphy_fits_either_kind_and_any_length():
    g = video(1, 1.0, "giphy")
    assert P.filter_candidates(shot("REAL_IMAGE"), [g]) == ([g], False)
    assert P.filter_candidates(shot(), [g]) == ([g], False)


def test_ranking_uses_the_ref_shot_keyframe(tmp_path, monkeypatch):
    # Candidates 0 and 2 are equally close to the inspo as a whole; only candidate 2 matches the ref shot.
    plan = {"shots": [{**shot(dur=2.0), "ref_shot": "r1", "audio": "x", "visual": {"type": "REAL_FOOTAGE", "desc": "d"}}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    files = []
    for k in range(3):
        f = tmp_path / f"c{k}.mp4"
        f.write_bytes(b"x")
        files.append({**video(k, 9.0), "file": str(f)})
    eye = np.eye(4)
    monkeypatch.setattr(P, "_gather", lambda session, n, per: {"candidates": files})
    monkeypatch.setattr(P.scorer, "load_inspo", lambda session: {"shots": [{"id": "r0"}, {"id": "r1"}], "dino": eye[[0, 2]]})
    monkeypatch.setattr(P, "media_frames", lambda path, a, b: [np.full((2, 2, 3), int(Path(path).stem[1:]))])
    monkeypatch.setattr(P, "save_jpg", lambda arr, path, max_side=640: path)
    monkeypatch.setattr(P, "judge", lambda items, log: ({}, 0.0, []))
    monkeypatch.setattr(P, "JOBS_DIR", tmp_path / "jobs")

    class Emb:
        def dino(self, frames):
            return np.stack([eye[int(f[0, 0, 0])] for f in frames])

        def siglip_images(self, frames):
            return np.zeros((len(frames), 4))

        def siglip_texts(self, texts):
            return np.zeros((len(texts), 4))

    monkeypatch.setattr("tools.match.common.Embedder", Emb)
    out = P.run(tmp_path, log=lambda m: None)
    assert out["shots"][1]["file"] == "c2.mp4"


def test_judge_batches_and_parses(tmp_path, monkeypatch):
    from PIL import Image
    img = tmp_path / "f.jpg"
    Image.new("RGB", (64, 36)).save(img)
    calls = []

    def call(argv, message):
        calls.append(json.loads(message))
        ids = [c["text"].split()[1].rstrip(".") for c in json.loads(message)["message"]["content"]
               if c["type"] == "text" and c["text"].startswith("Shot ") and "candidate" not in c["text"]]
        return json.dumps({"type": "result", "total_cost_usd": 0.02,
                           "result": json.dumps({i: {"best": 2, "reject": [1], "why": "w"} for i in ids})})

    monkeypatch.setattr(D, "_call", call)
    items = [{"n": n, "finals": [img, img, img], "desc": "d", "audio": "a", "ref_image": img, "ref_desc": "r"}
             for n in range(1, 13)]
    verdicts, cost, errors = P.judge(items, log=lambda m: None)
    assert len(calls) == 2 and len(verdicts) == 12 and verdicts[5]["best"] == 2 and not errors
    images = sum(c["type"] == "image" for c in calls[0]["message"]["content"])
    assert images in (8, 40)  # 2 or 10 shots x (ref + 3 candidates)


def test_fill_slows_a_nearly_long_enough_clip():
    assert P.fill(video(1, 3.0), 4.0) == {"speed": 0.75}


def test_fill_repeats_a_short_giphy_loop():
    assert P.fill(video(1, 1.0, "giphy"), 4.0) == {"repeat": 4}


def test_fill_slows_and_repeats_a_short_stock_clip():
    assert P.fill(video(1, 1.0), 4.0) == {"speed": 0.6, "repeat": 3, "short_clip": True}


def test_fill_leaves_long_clips_and_stills_alone():
    assert P.fill(video(1, 9.0), 4.0) == {} and P.fill(image(1), 4.0) == {}


def test_best_window_finds_the_middle():
    scores = np.array([0, 0, 0, 0, 5, 5, 5, 0, 0, 0], dtype=float)
    assert P.best_window(scores, 0.5, 1.5) == 4


def _fake_run(tmp_path, monkeypatch, cands, verdict=None, frames_at=None):
    plan = {"shots": [{**shot(dur=2.0), "audio": "x", "visual": {"type": "REAL_FOOTAGE", "desc": "d"}}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    for c in cands:
        Path(c["file"]).write_bytes(b"x")
    eye = np.eye(8)
    monkeypatch.setattr(P, "_gather", lambda session, n, per: {"candidates": cands})
    monkeypatch.setattr(P.scorer, "load_inspo", lambda session: None)
    monkeypatch.setattr(P, "media_frames", lambda path, a, b: [np.full((2, 2, 3), int(Path(path).stem[1:]))])
    if frames_at:
        monkeypatch.setattr(P, "frames_at", frames_at)
    monkeypatch.setattr(P, "save_jpg", lambda arr, path, max_side=640: path)
    monkeypatch.setattr(P, "judge", lambda items, log: ({1: verdict} if verdict else {}, 0.0, []))
    monkeypatch.setattr(P, "JOBS_DIR", tmp_path / "jobs")

    class Emb:
        def dino(self, frames):
            return np.stack([eye[int(f[0, 0, 0]) % 8] for f in frames])

        def siglip_images(self, frames):
            # A frame's value is its fit to the shot text.
            return np.stack([np.full(8, float(f[0, 0, 0])) for f in frames])

        def siglip_texts(self, texts):
            return np.ones((len(texts), 8)) / 8

    monkeypatch.setattr("tools.match.common.Embedder", Emb)
    return P.run(tmp_path, log=lambda m: None)


def test_long_clip_gets_its_best_window(tmp_path, monkeypatch):
    long = {**video(0, 60.0), "file": str(tmp_path / "c0.mp4")}

    def frames_at(path, times):
        # The matching scene sits at 30-32 s; everything else scores 0.
        return [np.full((2, 2, 3), 7 if 30 <= t < 32 else 0) for t in times]

    out = _fake_run(tmp_path, monkeypatch, [long], frames_at=frames_at)
    assert out["shots"][1]["in_point"] == 30.0


def test_youtube_keeps_its_finder_window(tmp_path, monkeypatch):
    yt = {**video(0, 600.0, "youtube"), "file": str(tmp_path / "c0.mp4"), "in_point": 412.0}
    out = _fake_run(tmp_path, monkeypatch, [yt], frames_at=lambda path, times: pytest.fail("re-windowed youtube"))
    assert out["shots"][1]["in_point"] == 412.0


def test_all_finalists_rejected_takes_the_fourth(tmp_path, monkeypatch):
    # Candidate k's frames score k, so the ranking is c4, c3, c2, c1.
    cands = [{**video(k, 5.0), "file": str(tmp_path / f"c{k}.mp4")} for k in (1, 2, 3, 4)]
    out = _fake_run(tmp_path, monkeypatch, cands, verdict={"best": 1, "reject": [1, 2, 3], "why": "watermarks"})
    assert out["shots"][1]["file"] == "c1.mp4"
