"""TypedDicts for assets.json output."""

from typing import TypedDict


class AssetCandidate(TypedDict):
    source: str      # pexels | pixabay | giphy | wikimedia | archive | youtube
    type: str        # video | image | gif
    url: str
    thumb: str
    title: str
    id: str
    width: int
    height: int
    ext: str
    duration: float  # seconds, 0 for images


class ShotAsset(TypedDict):
    shot_number: int
    ok: bool
    source: str
    asset_type: str   # video | image | gif | placeholder
    url: str
    file: str         # local path relative to session dir. For cached YouTube
                      # sources, points into source_pool/ (multiple shots may
                      # reference the same file with different in/out points).
    search_query: str
    in_point: float   # seconds into source file where this shot's content begins
    out_point: float  # seconds into source file where it ends (0/0 for static images)
    error: str        # empty string if ok
    visual_verdict: str        # "match" | "mismatch" | "unvalidated" | ""
    visual_confidence: int     # 0-100 — meaningful only when visual_verdict is "match"/"mismatch"


class AssetsOutput(TypedDict):
    session_id: str
    shots_total: int
    shots_fetched: int
    shots_failed: int
    shots: dict        # shot_number (str) -> ShotAsset
    timestamp: str
