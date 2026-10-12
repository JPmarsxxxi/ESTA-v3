"""No photo or video twice within 10 shots (SPEC.md Part 10, decision 10)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import autopick as A  # noqa: E402


def yt(vid, t=0):
    return {"url": f"https://www.youtube.com/watch?v={vid}", "file": f"{vid}_{t}.mp4", "in_point": t}


def test_media_key_follows_the_video_not_the_cut():
    assert A.media_key(yt("2YJsp-JtlpU", 0)) == A.media_key(yt("2YJsp-JtlpU", 40)) == "yt:2YJsp-JtlpU"
    assert A.media_key({"url": "https://upload.wikimedia.org/a.png"}) == "https://upload.wikimedia.org/a.png"


def test_repeat_within_ten_takes_the_next_best():
    taken = {"yt:AAAAAAAAAAA": {12}}
    c, rep = A.avoid_repeat(20, [yt("AAAAAAAAAAA", 5), yt("BBBBBBBBBBB")], taken)
    assert A.media_key(c) == "yt:BBBBBBBBBBB" and rep is None


def test_repeat_beyond_ten_is_fine():
    c, rep = A.avoid_repeat(30, [yt("AAAAAAAAAAA", 5), yt("BBBBBBBBBBB")], {"yt:AAAAAAAAAAA": {12}})
    assert A.media_key(c) == "yt:AAAAAAAAAAA" and rep is None


def test_no_other_candidate_keeps_the_repeat_and_flags_it():
    c, rep = A.avoid_repeat(20, [yt("AAAAAAAAAAA", 5)], {"yt:AAAAAAAAAAA": {18, 25}})
    assert A.media_key(c) == "yt:AAAAAAAAAAA" and rep == 18
