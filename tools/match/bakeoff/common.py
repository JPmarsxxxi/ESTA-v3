"""Shared paths and slugging for the M5.1 bake-off tools.

Split out because extract.py, candidates.py and key_build.py all need the
same video-slug -> key/<slug>/ mapping, and drift between them would silently
scatter a video's frames/labels across two different directories.
"""

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY_DIR = HERE / "key"
NEGATIVE_DIR = KEY_DIR / "negative_style"


def slug_for(video_path: str) -> str:
    stem = Path(video_path).stem
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def video_dir(slug: str) -> Path:
    return KEY_DIR / slug


def ensure_video_dir(slug: str) -> Path:
    d = video_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    return d
