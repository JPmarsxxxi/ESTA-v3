"""TypedDicts for plan.json output."""

from typing import TypedDict


class Visual(TypedDict):
    type: str          # REAL_FOOTAGE | REAL_IMAGE | MOTION_GRAPHICS
    desc: str
    search_query: str  # 3-5 word query used by assets skill
    fx: list[str]


class TextOverlay(TypedDict):
    caption: str       # empty string if none
    style: str
    pos: str           # top | bottom | center


class AudioLayer(TypedDict):
    music: str         # empty string if none
    sfx: list[str]


class CompositeSlot(TypedDict, total=False):
    """One panel of a multi-asset shot. Fetched exactly like a shot's own asset."""
    desc: str
    search_query: str
    search_sources: list[dict]
    type: str                   # REAL_FOOTAGE | REAL_IMAGE | MOTION_GRAPHICS
    specificity: str
    position: dict              # {x, y} fractions of frame from centre — overrides layout
    scale: dict                 # {x, y} — overrides layout


class Composite(TypedDict, total=False):
    """Several assets sharing one frame: split screens, insets, triptychs.

    Slot 0 is the shot's own asset (normal key), so a shot renders as usual
    until the extra panels land; slots 1+ are fetched under "<n>-slot<k>".
    `layout` names a preset in render's LAYOUTS; per-slot position/scale
    override it. Capped at 3 panels — one video track each.
    """
    layout: str                 # side_by_side | stack | triptych | inset
    slots: list[CompositeSlot]


class Shot(TypedDict):
    shot_number: int
    start: float       # real timing once reconciled; estimated initially
    end: float
    start_est: float   # 150 wpm estimate — never overwritten by reconcile
    end_est: float
    audio: str         # exact sentence from script
    visual: Visual
    text: TextOverlay
    audio_layer: AudioLayer
    transition: str    # cut | fade | zoom | wipe
    composite: Composite  # optional — multiple assets sharing the frame


class EditingNotes(TypedDict):
    pacing: str
    avg_shot_est: float
    method: str


class VideoMetadata(TypedDict):
    title: str
    duration_est: float
    style: str
    shot_count: int
    chunk_count: int


class Plan(TypedDict):
    session_id: str
    timing_source: str     # "estimated" | "timestamps"
    video_metadata: VideoMetadata
    shots: list[Shot]
    editing_notes: EditingNotes
    generated_at: str
