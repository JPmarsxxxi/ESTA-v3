"""faster-whisper transcription with word-level timestamps.

Lifted from notebook Cell 8. Constants match the notebook verbatim —
do not change threading, VAD, or silence threshold values without
re-validating against the reference.
"""

import json
import os
from datetime import datetime
from pathlib import Path

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Notebook-ground-truth constants
CPU_THREADS = 12
NUM_WORKERS = 4
VAD_MIN_SILENCE_MS = 300
VAD_THRESHOLD = 0.5
BEAM_SIZE = 5
INTER_SEGMENT_SILENCE_THRESHOLD = 0.3   # seconds
INTRA_SEGMENT_WORD_GAP_THRESHOLD = 0.15  # seconds


def transcribe(audio_path: Path, model_size: str = "small") -> dict:
    """Transcribe audio and return word-level timestamps + silence map.

    Args:
        audio_path: path to the audio WAV file.
        model_size: "base", "small", or "medium". Default "small" gives
            ±100ms accuracy — sufficient for 30fps video (33ms/frame).

    Returns:
        TimestampsData dict ready to be serialised to timestamps.json.
    """
    import huggingface_hub
    from faster_whisper import WhisperModel

    model_path = huggingface_hub.snapshot_download(
        f"Systran/faster-whisper-{model_size}",
        local_files_only=False,
        local_dir_use_symlinks=False,
    )

    model = WhisperModel(
        model_path,
        device="cpu",
        compute_type="int8",
        cpu_threads=CPU_THREADS,
        num_workers=NUM_WORKERS,
        local_files_only=True,
    )

    transcribe_start = datetime.now()
    # NOTE: faster-whisper has no batch_size parameter — do not add it.
    segments_iter, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=VAD_MIN_SILENCE_MS,
            threshold=VAD_THRESHOLD,
        ),
        beam_size=BEAM_SIZE,
    )

    formatted_segments = []
    full_text_parts = []
    total_words = 0

    # Write segments to .jsonl as they arrive so the plan skill can
    # poll partial results without waiting for full transcription.
    progress_path = audio_path.parent / "timestamps_progress.jsonl"
    with open(progress_path, "w", encoding="utf-8") as progress_f:
        for seg_idx, segment in enumerate(segments_iter):
            seg_text = segment.text.strip()
            full_text_parts.append(seg_text)

            words = []
            for word in segment.words:
                words.append({
                    "word": word.word.strip(),
                    "start": round(word.start, 3),
                    "end": round(word.end, 3),
                    "duration": round(word.end - word.start, 3),
                    "probability": round(word.probability, 3),
                })
                total_words += 1

            seg_data = {
                "index": seg_idx,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "duration": round(segment.end - segment.start, 3),
                "text": seg_text,
                "words": words,
            }
            formatted_segments.append(seg_data)
            progress_f.write(json.dumps(seg_data) + "\n")
            progress_f.flush()

    transcribe_time = (datetime.now() - transcribe_start).total_seconds()

    silence_points = _detect_silences(formatted_segments)
    total_duration = round(formatted_segments[-1]["end"], 3) if formatted_segments else 0.0

    return {
        "full_text": " ".join(full_text_parts),
        "total_duration": total_duration,
        "num_segments": len(formatted_segments),
        "num_words": total_words,
        "segments": formatted_segments,
        "silence_points": silence_points,
        "metadata": {
            "engine": "faster-whisper",
            "model": model_size,
            "accuracy": "±100ms (excellent for 30fps video)",
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "audio_file": str(audio_path),
            "transcription_time_seconds": round(transcribe_time, 2),
            "vad_enabled": True,
            "cpu_threads": CPU_THREADS,
            "timestamp": datetime.now().isoformat(),
        },
    }


def _detect_silences(segments: list) -> list:
    silence_points = []

    for i in range(len(segments) - 1):
        gap = segments[i + 1]["start"] - segments[i]["end"]
        if gap > INTER_SEGMENT_SILENCE_THRESHOLD:
            silence_points.append({
                "start": round(segments[i]["end"], 3),
                "end": round(segments[i + 1]["start"], 3),
                "duration": round(gap, 3),
                "type": "inter_segment",
            })

    for seg in segments:
        words = seg["words"]
        for i in range(len(words) - 1):
            gap = words[i + 1]["start"] - words[i]["end"]
            if gap > INTRA_SEGMENT_WORD_GAP_THRESHOLD:
                silence_points.append({
                    "start": round(words[i]["end"], 3),
                    "end": round(words[i + 1]["start"], 3),
                    "duration": round(gap, 3),
                    "type": "intra_segment",
                })

    silence_points.sort(key=lambda x: x["start"])
    return silence_points
