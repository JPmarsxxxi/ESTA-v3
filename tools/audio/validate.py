"""WAV file validation and inspection.

Used both for voice-sample validation (XTTS path) and final-audio
validation. Warnings are NOT errors — they surface the notebook's
duration hints (e.g., voice samples should ideally be 6-12s for XTTS).
"""

import wave
from pathlib import Path
from typing import TypedDict


class WavInfo(TypedDict):
    path: str
    duration: float        # seconds
    channels: int
    sample_rate: int       # Hz
    size_mb: float
    warnings: list[str]


def validate_wav(path: Path) -> WavInfo:
    """Inspect a WAV file and return its metadata plus any warnings."""
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        channels = wav.getnchannels()
        duration = frames / rate if rate else 0.0

    size_mb = path.stat().st_size / (1024 * 1024)

    warnings: list[str] = []
    if duration < 3:
        warnings.append(
            f"Short ({duration:.1f}s). XTTS prefers 6-12s voice samples."
        )
    elif duration > 20:
        warnings.append(
            f"Long ({duration:.1f}s). XTTS prefers 6-12s voice samples."
        )

    return {
        "path": str(path),
        "duration": duration,
        "channels": channels,
        "sample_rate": rate,
        "size_mb": size_mb,
        "warnings": warnings,
    }
