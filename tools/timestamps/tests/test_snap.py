"""SPEC.md Part 12 F8: whisper's words snap to the script's tokens, keeping whisper's timing."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.timestamps import snap as S  # noqa: E402


def w(word, a, b):
    return {"word": word, "start": a, "end": b, "duration": round(b - a, 3), "probability": 0.9}


ASR = [w("the", 0.0, 0.2), w("seal", 0.2, 0.5), w("test", 0.5, 0.8), w("said", 0.8, 1.0), w("0", 1.0, 1.2),
       w(".53", 1.2, 1.5), w("on", 1.5, 1.6), w("um", 1.6, 1.8), w("the", 1.8, 1.9), w("back", 1.9, 2.2), w("test", 2.2, 2.5)]
SCRIPT = "the Sealtest said 0.53 on the backtest"


def session(tmp_path):
    (tmp_path / "timestamps.json").write_text(json.dumps({
        "full_text": "", "num_words": len(ASR), "segments": [{"index": 0, "start": 0, "end": 2.5, "text": "", "words": ASR}],
        "metadata": {}}))
    (tmp_path / "voice_script.json").write_text(json.dumps({"lines": [{"id": "L01", "text": SCRIPT}]}))
    return tmp_path


def test_snap_returns_script_tokens_with_times_kept(tmp_path):
    s = session(tmp_path)
    out = S.snap(s)
    assert out["snapped"]
    ts = json.loads((s / "timestamps.json").read_text())
    words = ts["segments"][0]["words"]
    assert [x["word"] for x in words] == SCRIPT.split()
    by = {x["word"]: x for x in words}
    assert (by["said"]["start"], by["said"]["end"]) == (0.8, 1.0)          # matched word: timing untouched
    assert (by["Sealtest"]["start"], by["Sealtest"]["end"]) == (0.2, 0.8)  # replaced run spans its whisper words
    assert (by["0.53"]["start"], by["0.53"]["end"]) == (1.0, 1.5)
    assert (by["backtest"]["start"], by["backtest"]["end"]) == (1.9, 2.5)
    assert ts["metadata"]["snapped_to_script"] and ts["full_text"] == SCRIPT
    original = json.loads((s / "timestamps.original-asr.json").read_text())
    assert [x["word"] for x in original["segments"][0]["words"]] == [x["word"] for x in ASR]


def test_snap_runs_once(tmp_path):
    s = session(tmp_path)
    S.snap(s)
    assert S.snap(s)["snapped"] is False


def test_self_recorded_take_is_left_as_heard(tmp_path):
    s = session(tmp_path)
    (s / "voice_script.json").unlink()
    (s / "script.md").write_text("[HOOK]\n" + SCRIPT)
    (s / "audio_metadata.json").write_text(json.dumps({"method": "self_record"}))
    assert S.snap(s)["snapped"] is False
    (s / "audio_metadata.json").write_text(json.dumps({"method": "xtts"}))
    assert S.snap(s)["snapped"] is True


def test_unrelated_script_is_not_forced_on_the_transcript(tmp_path):
    s = session(tmp_path)
    (s / "voice_script.json").write_text(json.dumps({"lines": [{"id": "L01", "text": "completely different words here"}]}))
    assert S.snap(s)["snapped"] is False
