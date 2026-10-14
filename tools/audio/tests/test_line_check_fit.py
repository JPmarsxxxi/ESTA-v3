"""SPEC.md Part 12 F9-F10: the per-line TTS check, and fitting the stitched voiceover to a target length."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.audio import line_check as L  # noqa: E402
from tools.audio import stitch as S  # noqa: E402


def test_negation_flip_is_flagged():
    r = L.compare("You can't time the market.", "You can time the market.")
    assert r["flag"] and r["negation"] and r["wer"] <= L.WER_MAX


def test_wer_over_threshold_is_flagged():
    r = L.compare("the clock was wrong by eleven minutes", "the clock was long by seven")
    assert r["flag"] and not r["negation"] and r["wer"] > L.WER_MAX


def test_clean_line_passes():
    r = L.compare("It *never* had an edge [pause] it's gambling.", "It never had an edge, it's gambling.")
    assert not r["flag"] and r["wer"] == 0


def test_missing_apostrophe_is_not_a_flip():
    assert not L.compare("Don't buy it.", "Dont buy it.")["flag"]


def test_check_writes_voice_check(tmp_path):
    (tmp_path / "voice_script.json").write_text(json.dumps({"lines": [
        {"id": "L01", "text": "You can't win."}, {"id": "L02", "text": "Nobody wins."}]}))
    lines = tmp_path / "voice_build" / "lines"
    lines.mkdir(parents=True)
    for i in ("L01", "L02"):
        (lines / f"line_{i}.wav").write_bytes(b"")
    heard = {"line_L01.wav": "You can win.", "line_L02.wav": "Nobody wins."}
    out = L.check(tmp_path, transcribe=lambda p: heard[p.name])
    assert out["flagged"] == ["L01"]
    assert json.loads((tmp_path / "voice_check.json").read_text())["flagged"] == ["L01"]


def _tone(path: Path, seconds: float) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
                    "-ar", "48000", "-ac", "1", str(path)], check=True)


def _session(tmp_path, lengths, pause_ms):
    lines = tmp_path / "voice_build" / "lines"
    lines.mkdir(parents=True)
    job = {"word_count": 10 * len(lengths), "voice_sample": "x.wav", "line_count": len(lengths), "lines": []}
    for i, sec in enumerate(lengths):
        _tone(lines / f"line_L{i:02d}.wav", sec)
        job["lines"].append({"id": f"L{i:02d}", "text": " ".join(["word"] * 10), "pace": 1.0, "pause_after_ms": pause_ms})
    (tmp_path / "voice_script.json").write_text(json.dumps(job))
    return tmp_path


def test_target_seconds_is_hit_within_a_second(tmp_path):
    s = _session(tmp_path, [6.0] * 10, 800)  # 60 s speech + 8 s pauses = 68 s
    res = S.stitch(s, target_seconds=62)
    assert abs(res["duration"] - 62) < 1.0
    assert res["fit"]["words_to_cut"] == 0 and res["fit"]["tempo"] <= S.MAX_TEMPO
    job = json.loads((s / "voice_script.json").read_text())
    assert job["lines"][0]["pace"] > 1.0  # the fit is kept for later --only redos


def test_target_out_of_reach_reports_words_to_cut(tmp_path):
    s = _session(tmp_path, [6.0] * 10, 500)  # 65 s; the limits reach about 54.2 s
    res = S.stitch(s, target_seconds=45)
    assert res["fit"]["tempo"] == S.MAX_TEMPO and res["fit"]["pause_scale"] == S.MIN_PAUSE
    assert res["fit"]["words_to_cut"] > 0 and any("cut about" in w for w in res["warnings"])


def test_short_voiceover_is_left_alone(tmp_path):
    s = _session(tmp_path, [3.0] * 4, 400)
    res = S.stitch(s, target_seconds=60)
    assert res["fit"]["tempo"] == 1.0 and abs(res["duration"] - 13.6) < 0.2
