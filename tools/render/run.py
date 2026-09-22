"""Render tool — assembles sessions/<id>/<id>.openreel.json from pipeline outputs.

Reads requirements.json, plan.json, timestamps.json, assets.json, audio.wav +
audio_metadata.json and emits an OpenReel v1.0.0 project that the web editor
loads directly. Deterministic assembly — no LLM. ffprobe supplies media metadata.

    conda run --no-capture-output -n esta python tools/render/run.py build \
      --session sessions/<id>

The output matches the @openreel/core Project schema (packages/core/src/types).
Source media is referenced untrimmed (E1); per-clip inPoint/outPoint carry the
trim, so the editor can extend cuts.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCHEMA_VERSION = "1.0.0"

# Vertical short-form is the product default. Override with --width/--height.
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2

# Video tracks — V1 spine (REAL_FOOTAGE/REAL_IMAGE), V2 reserved for the user
# to drop overlays into, V3 motion graphics. Distribution is by visual.type.
VIDEO_TRACK_MAIN = "track-video-main"
VIDEO_TRACK_OVERLAY = "track-video-overlay"
VIDEO_TRACK_GRAPHICS = "track-video-graphics"

# Audio tracks — stemmed by role from arrangement.json for found-audio sessions
# so voice/music/ambience can be mixed independently. Standard-VO sessions put
# audio.wav on Voice and leave Music/Ambience empty for the user to drop into.
AUDIO_TRACK_VOICE = "track-audio-voice"
AUDIO_TRACK_MUSIC = "track-audio-music"
AUDIO_TRACK_AMBIENCE = "track-audio-ambience"

_ROLE_TO_TRACK = {
    "voice":    AUDIO_TRACK_VOICE,
    "music":    AUDIO_TRACK_MUSIC,
    "ambience": AUDIO_TRACK_AMBIENCE,
    "sfx":      AUDIO_TRACK_AMBIENCE,  # SFX rides on the ambience/atmosphere lane
}


def _video_track_for(visual_type: str) -> str:
    """Route a shot to its video track by visual type. MOTION_GRAPHICS gets V3;
    everything else lands on V1. V2 (overlay) stays empty for user b-roll."""
    if visual_type == "MOTION_GRAPHICS":
        return VIDEO_TRACK_GRAPHICS
    return VIDEO_TRACK_MAIN

SUBTITLE_STYLE = {
    "fontFamily": "Inter, sans-serif",
    "fontSize": 64,
    "color": "#ffffff",
    "backgroundColor": "rgba(0,0,0,0.4)",
    "position": "bottom",
    "highlightColor": "#fde047",
    "upcomingColor": "#ffffff",
}

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".webm"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _load(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_asset_shots(session_dir: Path) -> dict:
    """Per-shot asset results keyed by str(shot_number).

    Merges the final assets.json (present once the assets run completes) with
    the live assets_progress.jsonl feed — one `_fetch_shot` result per line,
    appended as each shot finishes (tools/assets/run.py:605). A progress line
    has the same shape as an assets.json shot entry, so they overlay directly;
    the progress file is authoritative for the latest state of a shot (the
    `shot` subcommand re-appends on retry), so later lines win.

    This is what lets render run the instant plan.json exists, mid-assets-run:
    shots already downloaded get real media, the rest ship as stream-pending
    placeholders (media-shot-N) the editor hydrates as the feed delivers them.
    """
    shots: dict[str, dict] = {}
    assets = _load(session_dir / "assets.json", {}) or {}
    for k, v in (assets.get("shots") or {}).items():
        shots[str(k)] = v

    progress = session_dir / "assets_progress.jsonl"
    if progress.exists():
        for line in progress.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            n = r.get("shot_number")
            if n is not None:
                shots[str(n)] = r  # later line wins over assets.json + earlier lines
    return shots


def _asset_url(file_path: str, session_name: str) -> str:
    """Map a stored file path to the URL the editor/asset-server expects.

    assets.json stores e.g. 'sessions\\<id>\\assets\\source_pool\\yt_x.mp4';
    the asset-server serves sessions/ under /api/sessions. Returns
    '/api/sessions/<id>/assets/source_pool/yt_x.mp4'.
    """
    if not file_path:
        return ""
    rel = file_path.replace("\\", "/")
    marker = "sessions/"
    idx = rel.find(marker)
    if idx >= 0:
        rel = rel[idx + len(marker):]          # '<id>/assets/...'
    else:
        rel = f"{session_name}/{rel.lstrip('/')}"
    return "/api/sessions/" + rel


def _ffprobe(path: Path) -> dict:
    """Media metadata via ffprobe. Returns zeros on any failure (never raises)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        info = json.loads(r.stdout or "{}")
    except Exception:
        info = {}

    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = info.get("format", {})

    def _fps(s: dict) -> float:
        rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
        try:
            num, den = rate.split("/")
            den = float(den)
            return round(float(num) / den, 3) if den else 0.0
        except Exception:
            return 0.0

    try:
        dur = float(fmt.get("duration") or v.get("duration") or a.get("duration") or 0)
    except Exception:
        dur = 0.0

    return {
        "duration": round(dur, 3),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "frameRate": _fps(v) if v else 0,
        "codec": v.get("codec_name") or a.get("codec_name") or "",
        "sampleRate": int(a.get("sample_rate") or 0),
        "channels": int(a.get("channels") or 0),
        "fileSize": int(fmt.get("size") or 0),
    }


def _transform(position: dict | None = None, scale: dict | None = None,
               fit_mode: str = "cover") -> dict:
    return {
        "position": position or {"x": 0, "y": 0},
        "scale": scale or {"x": 1, "y": 1},
        "rotation": 0,
        "anchor": {"x": 0.5, "y": 0.5},
        "opacity": 1,
        "fitMode": fit_mode,
    }


# ── composite shots (multiple assets in one frame) ───────────────────────────
#
# A shot may carry a `composite` block: several assets sharing the frame — two
# images side by side, a reaction inset over footage. The schema already had
# everything needed (per-clip position/scale, three video tracks); what was
# missing was a way for the plan to ASK for it. Slot 0 keeps the shot's normal
# asset key so single-asset behaviour is untouched; slots 1+ are fetched under
# "<n>-slot<k>" — the same convention the overlay block uses.
#
# Positions are fractions of the frame from centre, so they hold at any
# orientation. "contain" is the fit for split panels: "cover" would crop each
# panel to the slot box and throw away the thing being compared.
LAYOUTS: dict[str, list[dict]] = {
    "side_by_side": [
        {"position": {"x": -0.25, "y": 0}, "scale": {"x": 0.5, "y": 0.5}},
        {"position": {"x": 0.25, "y": 0}, "scale": {"x": 0.5, "y": 0.5}},
    ],
    "stack": [
        {"position": {"x": 0, "y": -0.25}, "scale": {"x": 0.5, "y": 0.5}},
        {"position": {"x": 0, "y": 0.25}, "scale": {"x": 0.5, "y": 0.5}},
    ],
    "triptych": [
        {"position": {"x": -0.333, "y": 0}, "scale": {"x": 0.333, "y": 0.333}},
        {"position": {"x": 0, "y": 0}, "scale": {"x": 0.333, "y": 0.333}},
        {"position": {"x": 0.333, "y": 0}, "scale": {"x": 0.333, "y": 0.333}},
    ],
    # Full-frame base with a smaller inset in the corner.
    "inset": [
        {"position": {"x": 0, "y": 0}, "scale": {"x": 1, "y": 1}},
        {"position": {"x": 0.3, "y": -0.3}, "scale": {"x": 0.34, "y": 0.34}},
    ],
}

# Slots beyond the first need their own track — clips on one track cannot
# overlap in time. Three video tracks means three slots; past that the plan is
# asking for more than the timeline can express.
_SLOT_TRACKS = [VIDEO_TRACK_MAIN, VIDEO_TRACK_OVERLAY, VIDEO_TRACK_GRAPHICS]
MAX_COMPOSITE_SLOTS = len(_SLOT_TRACKS)


def _slot_layout(composite: dict, index: int) -> dict:
    """Per-slot position/scale: explicit on the slot wins, else the named layout."""
    slots = composite.get("slots") or []
    slot = slots[index] if index < len(slots) else {}
    if slot.get("position") or slot.get("scale"):
        return {"position": slot.get("position") or {"x": 0, "y": 0},
                "scale": slot.get("scale") or {"x": 1, "y": 1}}
    preset = LAYOUTS.get(composite.get("layout", "side_by_side"))
    if preset and index < len(preset):
        return preset[index]
    return {"position": {"x": 0, "y": 0}, "scale": {"x": 1, "y": 1}}


def _media_type(asset_type: str) -> str:
    """OpenReel MediaItem.type is video|audio|image. gif rides as image
    (the editor has a gif decoder); video stays video; everything else image."""
    if asset_type == "video":
        return "video"
    return "image"


# ── editing-principles.md craft (deterministic; §1) ──────────────────────────

def _dimensions_for_orientation(orientation: str) -> tuple[int, int]:
    """requirements.orientation → frame dimensions (editing-principles §3 format
    dial). Defaults to vertical."""
    o = (orientation or "vertical").strip().lower()
    if o in ("horizontal", "landscape", "16:9", "wide"):
        return 1920, 1080
    if o in ("square", "1:1"):
        return 1080, 1080
    return DEFAULT_WIDTH, DEFAULT_HEIGHT  # vertical 1080x1920


def _ken_burns_keyframes(duration: float, index: int) -> list[dict]:
    """R1 — slow scale animation on a still so it's always breathing and the cut
    reads as flow, not a slap. Alternates zoom-in / zoom-out per image so the
    stills aren't identical (J3 variety). Keyframe time is clip-local seconds;
    properties scale.x/scale.y are read by video-engine.getAnimatedTransform."""
    start_s, end_s = (1.0, 1.08) if index % 2 == 0 else (1.08, 1.0)
    end_t = round(max(duration, 0.1), 3)
    kfs: list[dict] = []
    for axis in ("scale.x", "scale.y"):
        kfs.append({"id": f"kb-{index}-{axis}-a", "time": 0.0,
                    "property": axis, "value": start_s, "easing": "linear"})
        kfs.append({"id": f"kb-{index}-{axis}-b", "time": end_t,
                    "property": axis, "value": end_s, "easing": "linear"})
    return kfs


def _zoom_keyframes(duration: float, shot_n: int, direction: str = "in") -> list[dict]:
    """`fx: ["zoom_in"]` — a slow push on a MOVING clip.

    Same scale channel Ken Burns uses, but plan-driven rather than automatic:
    R1 only animates stills, so before this a shot that explicitly asked to push
    in just sat there. Kept gentle (8%) — this rides on top of footage that is
    already moving, so it should read as pressure, not a punch.
    """
    a, b = (1.0, 1.08) if direction == "in" else (1.08, 1.0)
    end_t = round(max(duration, 0.1), 3)
    kfs: list[dict] = []
    for axis in ("scale.x", "scale.y"):
        kfs.append({"id": f"zm-{shot_n}-{axis}-a", "time": 0.0,
                    "property": axis, "value": a, "easing": "linear"})
        kfs.append({"id": f"zm-{shot_n}-{axis}-b", "time": end_t,
                    "property": axis, "value": b, "easing": "linear"})
    return kfs


def _dissolves_for(clips: list[dict], duration: float = 0.4) -> list[dict]:
    """R5 — crossfade between consecutive clips on a track to kill the staccato.
    Style-gated by the caller (hard cuts for high-energy). Sits on the track's
    `transitions`, referencing each adjacent clip pair."""
    trans: list[dict] = []
    for a, b in zip(clips, clips[1:]):
        trans.append({
            "id": f"trans-{a['id']}-{b['id']}",
            "clipAId": a["id"],
            "clipBId": b["id"],
            "type": "crossfade",
            "duration": duration,
            "params": {},
        })
    return trans


# ── audio stemming ───────────────────────────────────────────────────────────

def _build_audio(
    session_dir: Path,
    session_name: str,
    audio_meta: dict,
    timestamps: dict,
    video_clips: list[dict],
    media_items: list[dict],
) -> tuple[list[dict], list[dict], list[dict], float]:
    """Build clips for the three audio tracks. Mutates `media_items` to register
    each source it uses.

    Found-audio sessions (arrangement.json + audio_pool.json present) stem the
    arrangement by role onto Voice / Music / Ambience tracks — each pool source
    becomes a deduped media item, each arrangement entry a clip with in/out
    trim and per-clip volume converted from `gain_db`.

    Standard-VO sessions put `audio.wav` on Voice and leave Music/Ambience
    empty so the user can drop their own beds/SFX in.

    Returns (voice_clips, music_clips, ambience_clips, total_audio_duration).
    """
    arrangement = _load(session_dir / "arrangement.json", None)
    pool = _load(session_dir / "audio_pool.json", None)

    voice_clips: list[dict] = []
    music_clips: list[dict] = []
    ambience_clips: list[dict] = []
    audio_dur = 0.0

    # ── Found-audio path: stem the arrangement onto Voice/Music/Ambience ──────
    if arrangement and pool:
        # arrangement.pool_id is "source:id"; index pool clips the same way.
        pool_by_id = {f"{c['source']}:{c['id']}": c for c in pool.get("clips", [])}
        seen_sources: set[str] = set()

        # Spine clips play sequentially (mirroring audio:assemble — "each starts
        # where the previous ended unless it has an explicit start"). The
        # arranger leaves spine `start` null for that auto-sequencing, so we
        # carry a running cursor here rather than defaulting every clip to 0
        # (which would stack the whole narration at t=0). The spine total is
        # also the timeline length, used to cap bed/music clips so a long in/out
        # window can't overrun the video with a dead music tail.
        def _entry_dur(e: dict) -> float:
            return round(max(float(e.get("out_point", 0) or 0)
                             - float(e.get("in_point", 0) or 0), 0.1), 3)

        spine_total = round(sum(
            _entry_dur(e) for e in arrangement.get("clips", [])
            if e.get("layer") == "spine"
        ), 3)
        spine_cursor = 0.0

        for entry in arrangement.get("clips", []):
            pool_id = entry.get("pool_id", "")
            src = pool_by_id.get(pool_id)
            if not src:
                continue

            in_pt = float(entry.get("in_point", 0) or 0)
            out_pt = float(entry.get("out_point", 0) or 0)
            raw_dur = round(max(out_pt - in_pt, 0.1), 3)
            explicit_start = entry.get("start", None)
            is_spine = entry.get("layer") == "spine"

            if is_spine and explicit_start is None:
                # auto-sequence: place where the previous spine clip ended
                start = round(spine_cursor, 3)
                duration = raw_dur
                spine_cursor = round(spine_cursor + raw_dur, 3)
            elif is_spine:
                start = float(explicit_start)
                duration = raw_dur
                spine_cursor = round(start + raw_dur, 3)
            else:
                # bed / ambience: cap the clip's end to the timeline length so a
                # wide source window doesn't extend the project past the video.
                start = float(explicit_start or 0)
                duration = raw_dur
                if spine_total > 0:
                    duration = round(min(raw_dur, max(spine_total - start, 0.1)), 3)
                out_pt = round(in_pt + duration, 3)

            audio_dur = max(audio_dur, start + duration)

            # gain_db → linear volume multiplier. e.g. -15 dB ≈ 0.178.
            gain_db = float(entry.get("gain_db", 0) or 0)
            volume = round(10 ** (gain_db / 20.0), 4)

            media_id = f"media-pool-{src['source']}-{src['id']}"
            # Register the source media once even if several arrangement entries
            # reuse it with different in/out points — the editor maps one media
            # item → many timeline clips, exactly the E1 source-pool contract.
            if pool_id not in seen_sources:
                seen_sources.add(pool_id)
                file_path = src.get("file", "")
                fp = Path(file_path)
                url = _asset_url(file_path, session_name)
                meta = (
                    _ffprobe(fp) if fp.exists()
                    else {
                        "duration": float(src.get("duration", 0) or 0),
                        "width": 0, "height": 0, "frameRate": 0, "codec": "",
                        "sampleRate": 0, "channels": 0, "fileSize": 0,
                    }
                )
                media_items.append({
                    "id": media_id,
                    "name": (src.get("title") or pool_id)[:80],
                    "type": "audio",
                    "fileHandle": None,
                    "blob": None,
                    "metadata": meta,
                    "thumbnailUrl": url or None,
                    "originalUrl": url or None,
                    "waveformData": None,
                    "isPlaceholder": True,
                })

            role = entry.get("role", "ambience")
            track_id = _ROLE_TO_TRACK.get(role, AUDIO_TRACK_AMBIENCE)
            clip = {
                "id": f"clip-aud-{entry.get('order', len(voice_clips) + len(music_clips) + len(ambience_clips))}",
                "mediaId": media_id,
                "trackId": track_id,
                "startTime": round(start, 3),
                "duration": duration,
                "inPoint": round(in_pt, 3),
                "outPoint": round(out_pt, 3),
                "effects": [],
                "audioEffects": [],
                "transform": _transform(),
                "volume": volume,
                "keyframes": [],
            }
            if track_id == AUDIO_TRACK_VOICE:
                voice_clips.append(clip)
            elif track_id == AUDIO_TRACK_MUSIC:
                music_clips.append(clip)
            else:
                ambience_clips.append(clip)

        return voice_clips, music_clips, ambience_clips, audio_dur

    # ── Standard-VO path: audio.wav on Voice; Music/Ambience empty ───────────
    audio_path = session_dir / "audio.wav"
    if audio_path.exists():
        audio_dur = float(
            audio_meta.get("duration_seconds")
            or timestamps.get("total_duration")
            or (video_clips[-1]["startTime"] + video_clips[-1]["duration"] if video_clips else 0)
        )
        audio_url = _asset_url(f"sessions/{session_name}/audio.wav", session_name)
        media_items.append({
            "id": "media-voiceover",
            "name": "Voiceover",
            "type": "audio",
            "fileHandle": None,
            "blob": None,
            "metadata": {
                "duration": round(audio_dur, 3),
                "width": 0, "height": 0, "frameRate": 0, "codec": "pcm",
                "sampleRate": int(audio_meta.get("sample_rate") or 0),
                "channels": int(audio_meta.get("channels") or 0),
                "fileSize": 0,
            },
            "thumbnailUrl": audio_url,
            "originalUrl": audio_url,
            "waveformData": None,
            "isPlaceholder": True,
        })
        voice_clips.append({
            "id": "clip-voiceover",
            "mediaId": "media-voiceover",
            "trackId": AUDIO_TRACK_VOICE,
            "startTime": 0,
            "duration": round(audio_dur, 3),
            "inPoint": 0,
            "outPoint": round(audio_dur, 3),
            "effects": [],
            "audioEffects": [],
            "transform": _transform(),
            "volume": 1,
            "keyframes": [],
        })

    # ── SFX layer (standard-VO) ─────────────────────────────────────────────
    # Found-audio sessions stem everything from arrangement.json, but a normal
    # voiceover video had no way to place a sound at a moment. sfx.json is that
    # way: a flat list of cues, each landing on the Ambience lane so it sits
    # under the voice (sound-design §0 — voice intelligible above all).
    #
    #   {"cues": [{"at": 12.4, "file": "...", "gain": 0.35, "label": "whoosh",
    #              "in": 0.0, "out": 0.8}]}
    #
    # `in`/`out` are optional source trims — which is how a shot's own diegetic
    # audio gets reused: point at the video file and window it to the moment.
    sfx = _load(session_dir / "sfx.json", None)
    for i, cue in enumerate((sfx or {}).get("cues", [])):
        raw = str(cue.get("file", "")).replace("\\", "/")
        if not raw:
            continue
        fp = Path(raw)
        if not fp.is_absolute() and not fp.exists():
            fp = session_dir / raw
        if not fp.exists():
            continue
        meta = _ffprobe(fp)
        src_dur = float(meta.get("duration") or 0)
        in_pt = round(float(cue.get("in", 0) or 0), 3)
        out_pt = float(cue.get("out") or 0) or src_dur
        out_pt = round(min(out_pt, src_dur) if src_dur else out_pt, 3)
        dur = round(max(out_pt - in_pt, 0.05), 3)
        start = round(float(cue.get("at", 0) or 0), 3)

        mid = f"media-sfx-{i}"
        url = _asset_url(str(fp).replace("\\", "/"), session_name)
        media_items.append({
            "id": mid,
            "name": cue.get("label") or fp.stem,
            "type": "audio",
            "fileHandle": None,
            "blob": None,
            "metadata": {
                "duration": round(src_dur, 3),
                "width": 0, "height": 0, "frameRate": 0,
                "codec": meta.get("codec", ""),
                "sampleRate": int(meta.get("sampleRate") or 0),
                "channels": int(meta.get("channels") or 0),
                "fileSize": int(meta.get("fileSize") or 0),
            },
            "thumbnailUrl": url,
            "originalUrl": url,
            "waveformData": None,
            "isPlaceholder": True,
        })
        ambience_clips.append({
            "id": f"clip-sfx-{i}",
            "mediaId": mid,
            "trackId": AUDIO_TRACK_AMBIENCE,
            "startTime": start,
            "duration": dur,
            "inPoint": in_pt,
            "outPoint": out_pt,
            "effects": [],
            "audioEffects": [],
            "transform": _transform(),
            # Default well under the voice — an SFX that competes with narration
            # is a mixing bug, not a punchline.
            "volume": round(float(cue.get("gain", 0.35) or 0.35), 3),
            "keyframes": [],
        })
        audio_dur = max(audio_dur, start + dur)

    return voice_clips, music_clips, ambience_clips, audio_dur


# ── build ────────────────────────────────────────────────────────────────────

def build(session_dir: Path, width: int | None = None, height: int | None = None) -> dict:
    session_name = session_dir.name
    requirements = _load(session_dir / "requirements.json", {}) or {}
    plan = _load(session_dir / "plan.json", {}) or {}
    timestamps = _load(session_dir / "timestamps.json", {}) or {}
    audio_meta = _load(session_dir / "audio_metadata.json", {}) or {}
    style = _load(session_dir / "style_analysis.json", {}) or {}

    # Format dial — orientation drives dimensions unless an explicit CLI override
    # was passed (editing-principles §3). Defaults to vertical.
    if width is None or height is None:
        ow, oh = _dimensions_for_orientation(requirements.get("orientation", "vertical"))
        width = width if width is not None else ow
        height = height if height is not None else oh

    # R5 dissolves are style-gated: dreamy/calm → crossfades; punchy/high-energy
    # → hard cuts. Default to dissolves when energy is unknown (montage-leaning).
    energy = str(style.get("energy_level", "")).lower()
    use_dissolves = energy not in ("high", "very high", "intense", "frenetic")

    shots = plan.get("shots", [])
    # Timeline structure comes from plan.json alone; assets are a hydration
    # concern. Merge the streaming feed so render reflects whatever's downloaded
    # so far and can run before the assets pass finishes (E1/streaming).
    asset_shots = _load_asset_shots(session_dir)

    media_items: list[dict] = []
    video_clips: list[dict] = []
    placeholders = 0
    image_idx = 0  # for alternating Ken Burns direction across stills

    for shot in shots:
        n = shot.get("shot_number")
        start = float(shot.get("start", shot.get("start_est", 0)) or 0)
        end = float(shot.get("end", shot.get("end_est", start)) or start)
        duration = max(round(end - start, 3), 0.1)
        visual = shot.get("visual", {})
        name = (visual.get("desc") or shot.get("audio") or f"Shot {n}")[:80]

        media_id = f"media-shot-{n}"
        asset = asset_shots.get(str(n)) or {}
        ok = bool(asset.get("ok")) and bool(asset.get("file"))
        file_path = asset.get("file", "") if ok else ""

        if ok and Path(file_path).exists():
            meta = _ffprobe(Path(file_path))
            mtype = _media_type(asset.get("asset_type", "video"))
            url = _asset_url(file_path, session_name)
            in_pt = float(asset.get("in_point", 0) or 0)
            src_dur = meta["duration"]
            if mtype == "video":
                out_pt = round(in_pt + duration, 3)
                if src_dur > 0:
                    out_pt = min(out_pt, src_dur)
                if out_pt <= in_pt:
                    out_pt = round(in_pt + duration, 3)
            else:
                in_pt, out_pt = 0.0, duration
        else:
            placeholders += 1
            meta = {"duration": duration, "width": width, "height": height,
                    "frameRate": DEFAULT_FPS, "codec": "", "sampleRate": 0,
                    "channels": 0, "fileSize": 0}
            mtype = "video"
            url = ""
            in_pt, out_pt = 0.0, duration

        media_items.append({
            "id": media_id,
            "name": name,
            "type": mtype,
            "fileHandle": None,
            "blob": None,
            "metadata": meta,
            "thumbnailUrl": url or None,
            "originalUrl": url or None,
            "waveformData": None,
            # Editor contract: hydratePlaceholders() only fetches items flagged
            # isPlaceholder, then flips them to false once the blob is loaded.
            # So every item ships flagged — fetched items (originalUrl set) get
            # hydrated; gap items (no url) stay flagged as the "Missing" badge.
            "isPlaceholder": True,
        })

        composite = shot.get("composite") or None
        if composite:
            lay0 = _slot_layout(composite, 0)
            base_transform = _transform(lay0["position"], lay0["scale"], "contain")
        else:
            base_transform = _transform()

        clip = {
            "id": f"clip-shot-{n}",
            "mediaId": media_id,
            "trackId": _video_track_for(visual.get("type", "")),
            "startTime": round(start, 3),
            "duration": duration,
            "inPoint": round(in_pt, 3),
            "outPoint": round(out_pt, 3),
            "effects": [],
            "audioEffects": [],
            "transform": base_transform,
            "volume": 1,
            "keyframes": [],
        }
        fx = visual.get("fx") or []
        if "slow_motion" in fx:
            clip["speed"] = 0.5
        # R1 — Ken Burns on stills so the frame is always moving (anti-jarring).
        # Only real images, not gap placeholders (those have no media yet).
        if mtype == "image" and url:
            clip["keyframes"] = _ken_burns_keyframes(duration, image_idx)
            image_idx += 1
        # Plan-requested push-in on footage. The plan skill advertises zoom_in in
        # its fx vocabulary, so a shot asking for it must actually get it —
        # otherwise the movement the plan designed silently disappears. Stills
        # already breathe via R1 above, so don't stack a second scale ramp.
        elif ("zoom_in" in fx or "zoom_out" in fx) and url:
            clip["keyframes"] = _zoom_keyframes(
                duration, n, "out" if "zoom_out" in fx else "in")
        # A composite's panels are deliberately framed against each other, so a
        # Ken Burns drift on one panel and not another reads as a mistake.
        if composite:
            clip["keyframes"] = []
        video_clips.append(clip)

        # ── composite slots 1+ : the rest of the panels sharing this frame ──
        # Slot 0 is the clip above (normal asset key). Each further slot is its
        # own fetched asset on its own track, spanning the same time range.
        if composite:
            for k in range(1, min(len(composite.get("slots") or []), MAX_COMPOSITE_SLOTS)):
                s_asset = asset_shots.get(f"{n}-slot{k}") or {}
                s_file = s_asset.get("file", "") if s_asset.get("ok") else ""
                if not (s_file and Path(s_file).exists()):
                    continue  # still downloading — the panel appears when it lands
                s_meta = _ffprobe(Path(s_file))
                s_type = _media_type(s_asset.get("asset_type", "image"))
                s_dur = float(s_meta.get("duration") or 0) or duration
                lay = _slot_layout(composite, k)
                slot_spec = (composite.get("slots") or [])[k]
                media_items.append({
                    "id": f"media-shot-{n}-slot{k}",
                    "name": (slot_spec.get("desc") or f"Shot {n} panel {k + 1}")[:80],
                    "type": s_type,
                    "fileHandle": None, "blob": None,
                    "metadata": s_meta,
                    "thumbnailUrl": _asset_url(s_file, session_name),
                    "originalUrl": _asset_url(s_file, session_name),
                    "waveformData": None,
                    "isPlaceholder": True,
                })
                video_clips.append({
                    "id": f"clip-shot-{n}-slot{k}",
                    "mediaId": f"media-shot-{n}-slot{k}",
                    "trackId": _SLOT_TRACKS[k],
                    "startTime": round(start, 3),
                    "duration": duration,
                    "inPoint": 0.0,
                    "outPoint": round(min(s_dur, duration), 3) if s_type == "video" else duration,
                    "effects": [], "audioEffects": [],
                    "transform": _transform(lay["position"], lay["scale"], "contain"),
                    "volume": 0,      # panels are picture only; the VO carries sound
                    "keyframes": [],
                })

        # ── overlay: generated motion-graphic floating over this shot (E2) ──
        # plan.json may carry an optional per-shot `overlay` block; the
        # motion-graphics skill renders it (transparent VP9 WebM) and appends
        # its result to assets_progress.jsonl keyed "<n>-overlay". Only emit
        # the clip once the rendered file exists — an absent overlay is an
        # enhancement still cooking, not a "Missing" placeholder.
        if shot.get("overlay"):
            o_asset = asset_shots.get(f"{n}-overlay") or {}
            o_ok = bool(o_asset.get("ok")) and bool(o_asset.get("file"))
            o_file = o_asset.get("file", "") if o_ok else ""
            if o_file and Path(o_file).exists():
                o_meta = _ffprobe(Path(o_file))
                o_url = _asset_url(o_file, session_name)
                o_name = (shot["overlay"].get("desc") or f"Overlay {n}")[:80]
                media_items.append({
                    "id": f"media-shot-{n}-overlay",
                    "name": o_name,
                    "type": "video",
                    "fileHandle": None,
                    "blob": None,
                    "metadata": o_meta,
                    "thumbnailUrl": o_url or None,
                    "originalUrl": o_url or None,
                    "waveformData": None,
                    "isPlaceholder": True,
                })
                o_src_dur = o_meta["duration"]
                o_out = round(min(duration, o_src_dur), 3) if o_src_dur > 0 else duration
                video_clips.append({
                    "id": f"clip-shot-{n}-overlay",
                    "mediaId": f"media-shot-{n}-overlay",
                    "trackId": VIDEO_TRACK_GRAPHICS,
                    "startTime": round(start, 3),
                    "duration": duration,
                    "inPoint": 0.0,
                    "outPoint": o_out,
                    "effects": [],
                    "audioEffects": [],
                    "transform": _transform(),
                    "volume": 1,
                    "keyframes": [],
                })

    # ── audio: stem into Voice / Music / Ambience (or VO-only for standard) ──
    voice_clips, music_clips, ambience_clips, audio_dur = _build_audio(
        session_dir, session_name, audio_meta, timestamps, video_clips, media_items,
    )

    # ── subtitles (karaoke, word-level from timestamps) ─────────────────────────
    subtitles: list[dict] = []
    for i, seg in enumerate(timestamps.get("segments", [])):
        words = [
            {"text": w.get("word", ""), "startTime": round(float(w.get("start", 0)), 3),
             "endTime": round(float(w.get("end", 0)), 3)}
            for w in seg.get("words", [])
        ]
        subtitles.append({
            "id": f"subtitle-seg-{i}",
            "text": seg.get("text", ""),
            "startTime": round(float(seg.get("start", 0)), 3),
            "endTime": round(float(seg.get("end", 0)), 3),
            "animationStyle": "karaoke",
            "style": SUBTITLE_STYLE,
            "words": words,
        })

    # ── tracks (3 video + 3 audio) ───────────────────────────────────────────
    # Partition shot clips by the trackId each shot was assigned in the loop
    # above. V2 stays empty unless future overlays are added; for arrangements
    # without motion graphics, V3 is also empty. Empty tracks are deliberate
    # scaffolding — the editor renders them as ready-to-fill lanes.
    main_clips     = [c for c in video_clips if c["trackId"] == VIDEO_TRACK_MAIN]
    overlay_clips  = [c for c in video_clips if c["trackId"] == VIDEO_TRACK_OVERLAY]
    graphics_clips = [c for c in video_clips if c["trackId"] == VIDEO_TRACK_GRAPHICS]

    def _track(track_id: str, ttype: str, name: str, clips: list[dict],
               muted: bool, transitions: list[dict] | None = None) -> dict:
        return {
            "id": track_id, "type": ttype, "name": name,
            "clips": clips, "transitions": transitions or [],
            "locked": False, "hidden": False, "muted": muted, "solo": False,
        }

    # R5 — dissolves on the Main spine (style-gated). The user can still hard-cut
    # by deleting transitions in the editor; this is the crafted default.
    main_transitions = _dissolves_for(main_clips) if use_dissolves else []

    # NLE-conventional stacking: higher-indexed video tracks render ON TOP, so
    # the timeline shows V3 → V2 → V1 from top down, then audio below it.
    tracks = [
        # Video tracks are muted (source audio never fights the audio tracks).
        _track(VIDEO_TRACK_GRAPHICS, "video", "Graphics", graphics_clips, muted=True),
        _track(VIDEO_TRACK_OVERLAY,  "video", "Overlay",  overlay_clips,  muted=True),
        _track(VIDEO_TRACK_MAIN,     "video", "Main",     main_clips,     muted=True, transitions=main_transitions),
        _track(AUDIO_TRACK_VOICE,    "audio", "Voice",    voice_clips,    muted=False),
        _track(AUDIO_TRACK_MUSIC,    "audio", "Music",    music_clips,    muted=False),
        _track(AUDIO_TRACK_AMBIENCE, "audio", "Ambience", ambience_clips, muted=False),
    ]

    last_video_end = max((c["startTime"] + c["duration"] for c in video_clips), default=0)
    duration = round(max(audio_dur, last_video_end), 3)

    now_ms = int(time.time() * 1000)
    title = (plan.get("video_metadata", {}) or {}).get("title") or requirements.get("topic") or session_name

    project = {
        "id": f"esta-{session_name}",
        "name": title,
        "createdAt": now_ms,
        "modifiedAt": now_ms,
        "settings": {
            "width": width, "height": height, "frameRate": DEFAULT_FPS,
            "sampleRate": DEFAULT_SAMPLE_RATE, "channels": DEFAULT_CHANNELS,
        },
        "mediaLibrary": {"items": media_items},
        "timeline": {
            "tracks": tracks,
            "subtitles": subtitles,
            "duration": duration,
            "markers": [],
        },
    }
    return {
        "version": SCHEMA_VERSION,
        "project": project,
        "_summary": {
            "media_items": len(media_items),
            "video_clips": len(video_clips),
            "video_tracks": {
                "main": len(main_clips),
                "overlay": len(overlay_clips),
                "graphics": len(graphics_clips),
            },
            "audio_tracks": {
                "voice": len(voice_clips),
                "music": len(music_clips),
                "ambience": len(ambience_clips),
            },
            "placeholders": placeholders,
            "subtitles": len(subtitles),
            "duration": duration,
            "has_audio": bool(voice_clips or music_clips or ambience_clips),
        },
    }


def cmd_build(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    if not (session_dir / "plan.json").exists():
        print(json.dumps({"ok": False, "error": "plan.json missing — run the plan skill first"}))
        sys.exit(1)

    result = build(session_dir, args.width, args.height)
    summary = result.pop("_summary")
    out_path = session_dir / f"{session_dir.name}.openreel.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"ok": True, "output": str(out_path), **summary}))


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA render tool — OpenReel project assembler")
    sub = parser.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("build", help="Assemble <session>.openreel.json for a session")
    b.add_argument("--session", required=True, help="Path to session dir")
    # Default None → orientation from requirements.json drives dimensions.
    b.add_argument("--width", type=int, default=None)
    b.add_argument("--height", type=int, default=None)
    args = parser.parse_args()

    try:
        if args.mode == "build":
            cmd_build(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
