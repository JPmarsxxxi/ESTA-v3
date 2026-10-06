"""Words spoken during each shot: inspo via faster-whisper, ours from timestamps.json. Writes speech.json {id: text}."""
import json
import time
from pathlib import Path

OUT = Path(__file__).parent
INSPO = str(OUT / "inspo" / "videoplayback-2.mp4")
TS = Path(__file__).resolve().parents[4] / "sessions" / "do-alphas-even-exist-2026-09-29" / "timestamps.json"


def words_in(words: list[dict], a: float, b: float) -> str:
    return " ".join(w["word"].strip() for w in words if a - 0.05 <= (w["start"] + w["end"]) / 2 < b + 0.05)


def main() -> None:
    from faster_whisper import WhisperModel
    t0 = time.time()
    cache = OUT / "inspo_words.json"
    if cache.exists():
        words = json.loads(cache.read_text(encoding="utf-8"))
    else:
        try:
            model = WhisperModel("small", device="cuda", compute_type="float16")
            segs, _ = model.transcribe(INSPO, word_timestamps=True, vad_filter=True)
            words = [{"word": w.word, "start": w.start, "end": w.end} for s in segs for w in s.words]
        except Exception as e:  # noqa: BLE001 - no CUDA runtime for ctranslate2: CPU int8 instead
            print("cuda failed, cpu:", str(e)[:120])
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segs, _ = model.transcribe(INSPO, word_timestamps=True, vad_filter=True)
            words = [{"word": w.word, "start": w.start, "end": w.end} for s in segs for w in s.words]
        cache.write_text(json.dumps(words), encoding="utf-8")
    ours = [w for s in json.loads(TS.read_text(encoding="utf-8")).get("segments", []) for w in s.get("words", [])] \
        or json.loads(TS.read_text(encoding="utf-8")).get("words", [])
    out = {}
    for s in json.loads((OUT / "shots.json").read_text(encoding="utf-8")):
        out[s["id"]] = words_in(words if s["side"] == "inspo" else ours, s["start"], s["end"])
    (OUT / "speech.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(words)} inspo words, {len(ours)} ours, {sum(bool(v) for v in out.values())}/{len(out)} shots with speech, "
          f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
