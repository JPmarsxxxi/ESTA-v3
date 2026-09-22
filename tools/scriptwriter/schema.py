"""Schema for script_metadata.json.

Tracks the full provenance of how a script was produced: the raw AI
draft, the humanizer-pass draft, the user-finalized version (canonical),
plus the talking points used, regen counts, and research sources cited.

The canonical script lives in sessions/<id>/script.md (just the user's
final text). This metadata file lives alongside it.

Keeping ai_draft and humanized_draft in metadata is intentional — the
future profile-update skill learns the user's voice by comparing the
deltas across AI → humanized → user-finalized.
"""

from datetime import datetime
from typing import TypedDict


class ScriptMetadata(TypedDict, total=False):
    session_id: str
    written_at: str

    target_word_count: int
    target_hook: int
    target_body: int
    target_cta: int
    final_word_count: int
    final_hook_words: int
    final_body_words: int
    final_cta_words: int

    talking_points: list[str]
    talking_points_regens: int
    script_regens: int
    user_edited_talking_points: bool
    user_finalized: bool
    user_skipped_humanization: bool

    ai_draft: str
    humanized_draft: str

    research_sources: list[str]
    example_scripts_used: int
    llm_provider: str


def default_script_metadata(session_id: str) -> ScriptMetadata:
    return {
        "session_id": session_id,
        "written_at": datetime.now().isoformat(),
        "target_word_count": 0,
        "target_hook": 0,
        "target_body": 0,
        "target_cta": 0,
        "final_word_count": 0,
        "final_hook_words": 0,
        "final_body_words": 0,
        "final_cta_words": 0,
        "talking_points": [],
        "talking_points_regens": 0,
        "script_regens": 0,
        "user_edited_talking_points": False,
        "user_finalized": False,
        "user_skipped_humanization": False,
        "ai_draft": "",
        "humanized_draft": "",
        "research_sources": [],
        "example_scripts_used": 0,
        "llm_provider": "claude",
    }


# ── Found-audio arrangement (scriptwriter:arranger → audio:assemble) ───────────
# In found-audio flows the "script" is not prose — it is an ordered selection of
# real clips from audio_pool.json. The arranger writes a human-readable script.md
# AND this machine-readable arrangement.json, which audio:assemble (Phase 5)
# stitches into audio.wav.

class ArrangementClip(TypedDict, total=False):
    order: int          # 1-based position along the spine
    beat: str           # "HOOK" | "BODY" | "CTA"
    layer: str          # "spine" (sequential narration) | "bed" (continuous underlay)
    pool_id: str        # "<source>:<id>" — keys into a clip in audio_pool.json
    file: str           # local media path (copied from the matching audio_pool clip)
    in_point: float     # start within the source clip, seconds (best-effort estimate)
    out_point: float    # end within the source clip, seconds
    start: float        # timeline start, seconds — beds set this; spine clips may omit
    gain_db: float      # level offset; beds typically negative (e.g. -14)
    role: str           # "voice" | "music" | "sfx" | "ambience" | "clip"
    transcript: str     # what's heard if voice/clip (ground-truthed later by timestamps)
    note: str           # why this clip / what it does at this beat


class Arrangement(TypedDict, total=False):
    session_id: str
    arranged_at: str
    source_pool: str        # "audio_pool.json"
    duration_est: float     # estimated total seconds
    clips: list[ArrangementClip]


def default_arrangement(session_id: str) -> Arrangement:
    return {
        "session_id": session_id,
        "arranged_at": datetime.now().isoformat(),
        "source_pool": "audio_pool.json",
        "duration_est": 0.0,
        "clips": [],
    }
