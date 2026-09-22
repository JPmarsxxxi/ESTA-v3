"""Pool analysis — the audio-comprehension layer for the found-audio flow.

Gives the scriptwriter `arranger` real content (transcripts) + timing so it can
(a) select clips by what they actually SAY, not their titles, and (b) cut a
spoken line to exact timestamps. Borrows the assets pipeline's economy: don't
brute-force everything — get understanding the cheapest way that works.

Tiered, so we don't waste compute/credits:
  1. NON-SPEECH clips (music / sfx / ambience by `kind`) → skipped entirely.
     There's no speech to transcribe; they stay title/duration-selected and
     their exact cut doesn't matter.
  2. YOUTUBE clips → try captions first via youtube_transcript_api (text +
     timing, NO download, NO whisper — same trick assets uses for video). Only
     fall back to whisper if a clip has no captions.
  3. Remaining speech clips (archive spoken word, wikimedia, caption-less
     youtube) → faster-whisper, model loaded ONCE and only if at least one clip
     needs it. Clips longer than the cap are skipped (almost always junk).

Each understood clip gets `transcript`, `cues` ([{start,end,text}]), and (from
whisper) word-level `words` — enough for the arranger to find a phrase and set
in/out. Reuses tools/timestamps/transcribe.py's faster-whisper config.

    conda run --no-capture-output -n esta python tools/audio/run.py analyze-pool \
      --session sessions/<id> [--model small]
"""

import json
import os
from datetime import datetime
from pathlib import Path

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

CPU_THREADS = 12
NUM_WORKERS = 4
VAD_MIN_SILENCE_MS = 300
VAD_THRESHOLD = 0.5
BEAM_SIZE = 5

MAX_TRANSCRIBE_S = 300.0       # skip whisper on clips longer than this
SPEECH_MIN_WORDS = 4
SPEECH_MIN_AVG_PROB = 0.5
NON_SPEECH_KINDS = {"music", "sfx", "ambience"}   # no speech → don't transcribe
SPEECH_KINDS = {"clip", "found", "voice"}         # plausibly spoken → worth understanding


def _youtube_captions(video_id: str):
    """YouTube captions (text + segment timing) without downloading. Same source
    the assets pipeline uses for transcript moment-finding. None if absent."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        raw = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US", "en-GB"])
    except Exception:
        return None
    cues = []
    for s in raw:
        text = s.get("text") if isinstance(s, dict) else getattr(s, "text", None)
        start = s.get("start") if isinstance(s, dict) else getattr(s, "start", None)
        dur = s.get("duration") if isinstance(s, dict) else getattr(s, "duration", None)
        if text is None or start is None:
            continue
        cues.append({"start": round(float(start), 3),
                     "end": round(float(start) + float(dur or 0), 3),
                     "text": text.strip()})
    return cues or None


def _load_model(model_size: str):
    import huggingface_hub
    from faster_whisper import WhisperModel
    model_path = huggingface_hub.snapshot_download(
        f"Systran/faster-whisper-{model_size}",
        local_files_only=False, local_dir_use_symlinks=False,
    )
    return WhisperModel(model_path, device="cpu", compute_type="int8",
                        cpu_threads=CPU_THREADS, num_workers=NUM_WORKERS, local_files_only=True)


def _whisper(model, path: Path):
    segs, info = model.transcribe(
        str(path), word_timestamps=True, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=VAD_MIN_SILENCE_MS, threshold=VAD_THRESHOLD),
        beam_size=BEAM_SIZE,
    )
    # faster-whisper returns numpy scalars — cast to native Python so the
    # enriched pool stays JSON-serializable.
    cues, words, parts = [], [], []
    for seg in segs:
        t = seg.text.strip()
        parts.append(t)
        cues.append({"start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "text": t})
        for w in (seg.words or []):
            words.append({"word": w.word.strip(), "start": round(float(w.start), 3),
                          "end": round(float(w.end), 3), "prob": round(float(w.probability), 3)})
    text = " ".join(p for p in parts if p).strip()
    avg = (sum(w["prob"] for w in words) / len(words)) if words else 0.0
    has = bool(len(words) >= SPEECH_MIN_WORDS and avg >= SPEECH_MIN_AVG_PROB)
    return text, cues, words, has


def analyze(session_dir: Path, model_size: str = "small") -> dict:
    pool_path = session_dir / "audio_pool.json"
    if not pool_path.exists():
        raise FileNotFoundError("audio_pool.json missing — run audio found-fetch first")
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    clips = pool.get("clips", [])

    counts = {"captioned": 0, "whispered": 0, "non_speech": 0, "skipped_long": 0, "no_file": 0, "speech": 0}
    need_whisper = []
    started = datetime.now()

    # Pass 1 — cheap tiers: skip non-speech, use youtube captions.
    for c in clips:
        f = c.get("file", "")
        if not f or not Path(f).exists():
            c.update(analyzed=False, has_speech=None, analysis_note="no file"); counts["no_file"] += 1; continue
        if c.get("kind") in NON_SPEECH_KINDS:
            c.update(analyzed=True, has_speech=False, transcript="", understanding="none",
                     analysis_note="non-speech (music/sfx) — title/duration selection"); counts["non_speech"] += 1; continue
        if c.get("source") == "youtube":
            caps = _youtube_captions(c.get("id", ""))
            if caps:
                text = " ".join(x["text"] for x in caps).strip()
                c.update(analyzed=True, has_speech=bool(text), transcript=text, cues=caps,
                         understanding="captions")
                counts["captioned"] += 1
                if text:
                    counts["speech"] += 1
                print(f"[analyze] {c['source']}:{c['id']} | captions | {text[:60]}...", flush=True)
                continue
        if float(c.get("duration", 0) or 0) > MAX_TRANSCRIBE_S:
            c.update(analyzed=False, has_speech=None,
                     analysis_note=f"too long (>{int(MAX_TRANSCRIBE_S)}s) and no captions"); counts["skipped_long"] += 1; continue
        if c.get("kind") in SPEECH_KINDS:
            need_whisper.append(c)
        else:
            c.update(analyzed=True, has_speech=False, transcript="", understanding="none",
                     analysis_note="kind not speech-bearing"); counts["non_speech"] += 1

    # Pass 2 — whisper only what's left, model loaded once and only if needed.
    if need_whisper:
        model = _load_model(model_size)
        for c in need_whisper:
            try:
                text, cues, words, has = _whisper(model, Path(c["file"]))
                c.update(analyzed=True, has_speech=has, understanding="whisper", avg_prob=round(
                    (sum(w["prob"] for w in words) / len(words)) if words else 0.0, 3))
                if has:
                    c.update(transcript=text, cues=cues, words=words); counts["speech"] += 1
                else:
                    c["transcript"] = ""; c.pop("cues", None); c.pop("words", None)
                counts["whispered"] += 1
                print(f"[analyze] {c['source']}:{c['id']} | whisper | speech={has} | "
                      f"{(text[:60] + '...') if text else '(none)'}", flush=True)
            except Exception as exc:
                c.update(analyzed=False, has_speech=None, analysis_note=f"error: {exc}")
                print(f"[analyze] {c['source']}:{c['id']} FAILED: {exc}", flush=True)

    pool["analyzed_at"] = datetime.now().isoformat()
    pool["analysis"] = {"model": model_size, **counts}
    pool_path.write_text(json.dumps(pool, indent=2, ensure_ascii=False), encoding="utf-8")

    digest = {
        "session_id": session_dir.name,
        "analyzed_at": pool["analyzed_at"],
        "model": model_size,
        "seconds": round((datetime.now() - started).total_seconds(), 1),
        "counts": counts,
        "speech": [
            {"pool_id": f"{c['source']}:{c['id']}", "kind": c.get("kind"),
             "understanding": c.get("understanding"), "title": c.get("title", ""),
             "transcript": c.get("transcript", "")}
            for c in clips if c.get("has_speech")
        ],
    }
    (session_dir / "audio_pool_analysis.json").write_text(
        json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "output": str(session_dir / "audio_pool_analysis.json"), **counts}


def cmd_analyze_pool(args) -> None:
    print(json.dumps(analyze(Path(args.session), args.model)))
