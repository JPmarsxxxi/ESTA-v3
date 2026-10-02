"""slots.py on synthetic words and inspo shots."""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match import slots as SL  # noqa: E402


def words(n, step=0.4, gap=0.1, lead=0.0):
    return [{"word": f"w{i}", "start": lead + i * step, "end": lead + i * step + step - gap} for i in range(n)]


def inspo(durs):
    return [{"id": f"i{i}", "dur": d, "tags": {}, "motion": {}, "keyframe": ""} for i, d in enumerate(durs)]


def tiles(out, end):
    assert out[0]["start"] == 0 and abs(out[-1]["end"] - end) < 1e-6
    assert all(a["end"] == b["start"] for a, b in zip(out, out[1:]))


def test_tiles_voiceover_and_cuts_on_boundaries():
    w = words(150)  # 60 s of speech
    out = SL.propose(w, 61.0, inspo([2.0, 3.0, 1.5] * 10))
    tiles(out, 61.0)
    cuts = set(SL.boundaries(w))
    assert all(s["end"] in cuts for s in out[:-1])


def test_normalised_position_real_seconds():
    # Inspo 30 s of 3 s shots, our voice 60 s: twice as many slots, each still ~3 s.
    w = words(150)
    out = SL.propose(w, 60.0, inspo([3.0] * 10))
    assert 18 <= len(out) <= 22
    assert abs(statistics.median(s["dur"] for s in out) - 3.0) <= 0.3
    # Position is normalised: halfway through our video maps to the inspo's middle shot.
    mid = next(s for s in out if s["start"] >= 30)
    assert mid["ref_shot"] in ("i4", "i5")


def test_alts_window():
    out = SL.propose(words(150), 60.0, inspo([2.0] * 30))
    s = next(s for s in out if s["ref_shot"] == "i10")
    assert s["alts"] == ["i7", "i8", "i9", "i11", "i12", "i13"]


def test_leading_and_trailing_silence_covered():
    w = words(20, lead=1.5)  # speech from 1.5 s to ~9.5 s
    out = SL.propose(w, 12.0, inspo([2.0] * 6))
    tiles(out, 12.0)


def test_long_word_is_one_slot():
    w = [{"word": "a", "start": 0, "end": 0.3}, {"word": "loooong", "start": 0.4, "end": 3.4},
         {"word": "b", "start": 3.5, "end": 3.8}, {"word": "c", "start": 3.9, "end": 4.2}]
    out = SL.propose(w, 4.3, inspo([0.5] * 10))
    tiles(out, 4.3)
    assert any(abs(s["start"] - 0.35) < 1e-6 and abs(s["end"] - 3.45) < 1e-6 for s in out)


def test_short_last_slot_merges():
    # A 3 s target reaching the end with only ~0.4 s left: the stub joins the slot before it.
    w = words(25)  # 10 s
    out = SL.propose(w, 10.2, inspo([3.0] * 4))
    tiles(out, 10.2)
    assert out[-1]["dur"] >= 0.4 * out[-1]["target_dur"]


def test_overlapping_whisper_words_clamped():
    ts = {"segments": [{"words": [{"word": "a", "start": 0, "end": 1.0}, {"word": "b", "start": 0.8, "end": 1.5}]}]}
    w = SL.load_words(ts)
    assert w[1]["start"] >= w[0]["end"]
