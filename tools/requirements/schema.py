"""Schema and default skeleton for requirements.json.

This is the contract — any downstream skill (research, scriptwriter, etc.)
that reads requirements.json should import from here so field names cannot
drift between skills.
"""

from datetime import datetime
from typing import Literal, TypedDict, Union


class ExampleScript(TypedDict):
    text: str
    length: int
    source: str  # "user_paste" or "user_file"


class ScriptStats(TypedDict):
    word_count: int
    char_count: int
    estimated_duration_min: float


class Requirements(TypedDict, total=False):
    session_id: str
    created_at: str

    topic: str
    style: str  # preset (see validators.STYLE_PRESETS) or custom, lowercased
    duration_range: str  # normalized form e.g. "2-3 minutes"
    # Frame orientation — the format dial read by render (dimensions),
    # editing-principles.md and sound-design.md (pacing/continuity/loudness).
    # "vertical" (9:16, phone/social), "horizontal" (16:9, YouTube/desktop),
    # "square" (1:1). Defaults to "vertical" (the product default).
    orientation: str  # "vertical" | "horizontal" | "square"
    comments: str

    # Project-wide licensing stance. Governs which sources audio:found-fetch and
    # the assets skill may use. "free_only" = CC/PD/royalty-free sources only;
    # "fair_use_ok" = also allow copyrighted grabs (YouTube clips, press photos).
    licensing: str  # "free_only" | "fair_use_ok"

    # List of provided examples, OR sentinel string "ASSET_COLLECTOR_PLACEHOLDER"
    # when none provided (tells future asset-collector skill to find references).
    example_scripts: Union[list[ExampleScript], str]

    # Script source branch
    script_source: Literal["generate", "user_uploaded"]
    skip_scriptwriter: bool
    script_text: str | None       # populated only when user_uploaded
    script_file: str | None       # populated only when user_uploaded
    script_stats: ScriptStats | None  # populated only when user_uploaded


def default_requirements(session_id: str) -> Requirements:
    """Empty skeleton with session_id and created_at populated."""
    return {
        "session_id": session_id,
        "created_at": datetime.now().isoformat(),
        "topic": "",
        "style": "",
        "duration_range": "",
        "orientation": "vertical",
        "comments": "",
        "licensing": "free_only",
        "example_scripts": "ASSET_COLLECTOR_PLACEHOLDER",
        "script_source": "generate",
        "skip_scriptwriter": False,
        "script_text": None,
        "script_file": None,
        "script_stats": None,
    }
