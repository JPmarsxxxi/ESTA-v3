"""H.264 window cuts for picks the editor can't export (SPEC.md Part 12, F6).

Headless Chrome stalled exporting timelines at AV1 and VP9 clips. At pick time a non-H.264 video gets an H.264
cut of just its used window (plus half a second each side, so the cut stays draggable), and the pick points at
the cut with its in/out shifted to match. H.264 sources and stills pass through untouched.
"""

import subprocess
from pathlib import Path

PAD = 0.5
VIDEO = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v"}


def video_codec(path: Path) -> str:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""


def h264_window(path: Path, in_point: float, out_point: float, tag) -> tuple[Path, float, float]:
    """(file, in, out) to use: the source itself, or an H.264 cut of [in - PAD, out + PAD] named <stem>_h264_<tag>."""
    path = Path(path)
    if path.suffix.lower() not in VIDEO or "_h264_" in path.stem:
        return path, in_point, out_point
    codec = video_codec(path)
    if not codec or codec == "h264":
        return path, in_point, out_point
    a = max(0.0, float(in_point or 0) - PAD)
    b = float(out_point or a + 3) + PAD
    dst = path.with_name(f"{path.stem}_h264_{tag}.mp4")
    if not (dst.exists() and dst.stat().st_size > 1024):
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(path),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", str(dst)], capture_output=True, text=True)
        if r.returncode != 0:
            dst.unlink(missing_ok=True)
            return path, in_point, out_point
    return dst, round(float(in_point or 0) - a, 3), round(float(out_point or 0) - a, 3)
