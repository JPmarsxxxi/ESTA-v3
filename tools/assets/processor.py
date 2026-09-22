"""Trim and speed-adjust downloaded video clips to match shot target duration.

Called after every video download to normalise clips before render. Images
and GIFs are returned unchanged — render handles GIF-to-video conversion.
"""

import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".webm"}
MAX_SPEED = 2.0   # don't stretch beyond 2× — looks unnatural
TOLERANCE = 0.15  # skip processing if within 15% of target


def process_clip(src: Path, dest: Path, target_dur: float) -> Path:
    """Trim (and optionally speed-adjust) src to target_dur seconds.

    Returns dest on success, src if processing is unnecessary or fails.
    Speed is capped at MAX_SPEED — clips too short to fill the shot without
    excessive stretch are left at their natural duration for render to handle.
    """
    if src.suffix.lower() not in VIDEO_EXTS:
        return src

    src_dur = _get_duration(src)
    if src_dur <= 0 or target_dur <= 0:
        return src

    if abs(src_dur - target_dur) / target_dur <= TOLERANCE:
        return src  # close enough

    if src_dur >= target_dur:
        return _ffmpeg_process(src, dest, trim_dur=target_dur, speed=1.0)
    else:
        speed = target_dur / src_dur
        if speed <= MAX_SPEED:
            return _ffmpeg_process(src, dest, trim_dur=src_dur, speed=speed)
        else:
            return src  # too short to stretch cleanly; render will loop/pad


def _get_duration(path: Path) -> float:
    """Return video duration in seconds via ffprobe. Returns 0.0 on failure."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _ffmpeg_process(src: Path, dest: Path, trim_dur: float, speed: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-i", str(src), "-t", f"{trim_dur:.3f}"]

    if speed != 1.0:
        cmd += ["-filter:v", f"setpts={1.0 / speed:.4f}*PTS"]

    # Strip audio — voiceover is the primary audio track mixed in render.
    # crf 20 (near-visually-lossless): D1 guarantees >=720p source, so this
    # second-generation re-encode shouldn't also shed quality at crf 23.
    cmd += ["-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", str(dest)]

    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        return dest if dest.exists() else src
    except Exception as exc:
        print(f"[processor] ffmpeg failed ({src.name}): {exc}", file=sys.stderr, flush=True)
        return src
