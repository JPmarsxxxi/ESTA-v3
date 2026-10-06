"""Words spoken over each inspo shot, so the describe lane can judge what the editor was illustrating.

    python tools/match/speech.py --profile cache/inspo/<hash>

The whole inspo is transcribed once (faster-whisper `small`, word timestamps) and cached as
`<profile>/words.json`; each shot then takes the words whose midpoint falls inside it.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import read_json, utf8_stdout, write_json  # noqa: E402


def transcribe(video: Path, log=print) -> list[dict]:
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel("small", device="cuda", compute_type="float16")
        segs, _ = model.transcribe(str(video), word_timestamps=True, vad_filter=True)
        return [{"word": w.word.strip(), "start": w.start, "end": w.end} for s in segs for w in s.words]
    except Exception as e:  # noqa: BLE001 - no CUDA runtime for ctranslate2 (cublas missing): CPU int8
        log(f"[speech] cuda failed, cpu int8: {str(e)[:120]}")
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(video), word_timestamps=True, vad_filter=True)
        return [{"word": w.word.strip(), "start": w.start, "end": w.end} for s in segs for w in s.words]


def words_in(words: list[dict], a: float, b: float) -> str:
    return " ".join(w["word"] for w in words if a - 0.05 <= (w["start"] + w["end"]) / 2 < b + 0.05).strip()


def profile_words(d: Path, log=print) -> list[dict]:
    """Cached transcript of the profile's video. A silent inspo caches an empty list."""
    cache = d / "words.json"
    words = read_json(cache)
    if words is None:
        words = transcribe(d / "video.mp4", log)
        write_json(cache, words)
    return words


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Transcribe an inspo profile's video")
    ap.add_argument("--profile", required=True)
    d = Path(ap.parse_args().profile)
    words = profile_words(d)
    prof = read_json(d / "profile.json") or {}
    said = sum(bool(words_in(words, s["start"], s["end"])) for s in prof.get("shots", []))
    print(f"{len(words)} words; {said}/{len(prof.get('shots', []))} shots have speech")


if __name__ == "__main__":
    main()
