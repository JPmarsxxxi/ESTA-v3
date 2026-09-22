"""Schema for audio_metadata.json.

Tracks how the audio was produced, its acoustic properties, and the
provenance fields the timestamps + brainbox skills downstream will
need. The canonical audio file lives at sessions/<id>/audio.wav.
"""

from datetime import datetime
from typing import Literal, TypedDict


class AudioMetadata(TypedDict, total=False):
    session_id: str
    audio_file: str        # path to sessions/<id>/audio.wav

    method: Literal[
        "indextts2",         # expressive per-line VO (IndexTTS2 + Seed-VC guide takes)
        "xtts",
        "self_recorded",
        "found_assembled",   # stitched from a found-audio arrangement (assemble mode)
        "failed",
        "cancelled",
        "placeholder",
    ]

    # acoustic properties (from validate.validate_wav on the final file)
    duration_seconds: float
    duration_minutes: float
    channels: int
    sample_rate: int
    file_size_mb: float

    # provenance
    script_word_count: int
    voice_sample: str | None         # path under voice_samples/ if xtts
    takes_recorded: int | None       # how many takes attempted if self_recorded
    xtts_speed: float | None         # XTTS speed param if xtts
    xtts_gpu: bool | None            # whether GPU was used if xtts
    xtts_load_time_seconds: float | None
    xtts_gen_time_seconds: float | None
    source_clips: int | None         # how many arrangement clips were stitched if found_assembled
    line_count: int | None           # synthesis units in voice_script.json if indextts2
    guide_lines: list[str] | None    # line ids voiced from a user take via Seed-VC

    timestamp: str


def default_audio_metadata(session_id: str) -> AudioMetadata:
    return {
        "session_id": session_id,
        "audio_file": "",
        "method": "cancelled",
        "duration_seconds": 0.0,
        "duration_minutes": 0.0,
        "channels": 0,
        "sample_rate": 0,
        "file_size_mb": 0.0,
        "script_word_count": 0,
        "voice_sample": None,
        "takes_recorded": None,
        "xtts_speed": None,
        "xtts_gpu": None,
        "xtts_load_time_seconds": None,
        "xtts_gen_time_seconds": None,
        "timestamp": datetime.now().isoformat(),
    }
