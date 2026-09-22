"""Convert a rendered <session>.openreel.json into an OpenCut-friendly intermediate.

This is the spike serializer for mounting ESTA's pipeline output on the
opencut-classic timeline engine. It deliberately does NOT emit OpenCut's native
`SerializedProject` (scenes + integer-tick `MediaTime` + per-type `params`).
Instead it emits a small, plain-seconds intermediate (`esta-import.json`) that a
thin TypeScript seed step inside OpenCut turns into a real project using
OpenCut's OWN constructors (`mediaTimeFromSeconds`, element creators,
`storageService.saveMediaAsset`/`saveProject`).

Rationale: the native schema's tricky bits — MediaTime ticks, trimStart/trimEnd,
required ParamValues per element type — are exactly the things best produced by
OpenCut's own helpers, not hand-encoded here. So this file owns only the
structural mapping (tracks → main/overlay/audio, clips → elements, media URLs),
and the TS side owns native construction.

Mapping (OpenReel → OpenCut):
  - timeline.tracks (flat: 3 video + 3 audio) → { main, overlay[], audio[] }
      "Main"  video track            → main (the base VideoTrack)
      "Graphics"/"Overlay" video     → overlay[] (float on top)
      "Voice"/"Music"/"Ambience"     → audio[]
  - clip {startTime,duration,inPoint,outPoint} → element {startTime,duration,
      inPoint,outPoint} (TS converts in/out → trimStart/trimEnd via sourceDuration)
  - mediaLibrary.items → media[] (url = originalUrl; kind from item.type)
  - subtitles[]        → text[] (one block per segment; karaoke words preserved
      but flattened to text for the spike)

Usage:
  python tools/opencut/from_openreel.py --session sessions/<id>
  # writes sessions/<id>/esta-import.json

  python tools/opencut/from_openreel.py --session sessions/<id> --originals
  # same, but pointed at the original sources instead of assets/proxies/ —
  # this is the import to EXPORT from. OpenCut encodes whatever the timeline
  # references, so a proxied import would ship a crf-23 downscale as the final
  # video. Proxies are for scrubbing; originals are for delivery.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _probe_proxy_dims(path: Path) -> tuple[int, int]:
    """Real pixel dims of a generated proxy (differs from the original source)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True).stdout.split()
        return int(out[0]), int(out[1])
    except Exception:
        return 0, 0


# OpenReel track names (from tools/render/run.py) → OpenCut lane.
MAIN_VIDEO_TRACK = "Main"
OVERLAY_VIDEO_TRACKS = {"Graphics", "Overlay"}
AUDIO_TRACKS = {"Voice", "Music", "Ambience"}


def _kind_for(media_type: str) -> str:
    """OpenCut element kind from an OpenReel MediaItem.type."""
    if media_type == "video":
        return "video"
    if media_type == "audio":
        return "audio"
    return "image"  # gif/image ride as image


def _video_element(clip: dict, media: dict) -> dict:
    kind = _kind_for(media.get("type", "video"))
    meta = media.get("metadata", {}) or {}
    # Carry the clip's keyframes through verbatim (OpenReel form: time in
    # clip-local seconds, property like "scale.x"/"scale.y", value, easing).
    # The seed translates property → OpenCut path + seconds → MediaTime ticks.
    keyframes = [
        {"time": round(float(k.get("time", 0)), 3),
         "property": k.get("property", ""),
         "value": k.get("value")}
        for k in (clip.get("keyframes") or [])
    ]
    return {
        "mediaId": clip["mediaId"],
        "kind": kind,  # "video" | "image"
        "name": media.get("name", "")[:80],
        "startTime": round(float(clip.get("startTime", 0)), 3),
        "duration": round(float(clip.get("duration", 0)), 3),
        "inPoint": round(float(clip.get("inPoint", 0)), 3),
        "outPoint": round(float(clip.get("outPoint", 0)), 3),
        # sourceDuration lets the TS side compute trimEnd = sourceDuration - outPoint.
        # Images report ~0 here; the seed treats them as static (no trim).
        "sourceDuration": round(float(meta.get("duration", 0) or 0), 3),
        "speed": clip.get("speed"),
        "keyframes": keyframes,  # [] when none
    }


def _audio_element(clip: dict, media: dict) -> dict:
    meta = media.get("metadata", {}) or {}
    return {
        "mediaId": clip["mediaId"],
        "name": media.get("name", "")[:80],
        "startTime": round(float(clip.get("startTime", 0)), 3),
        "duration": round(float(clip.get("duration", 0)), 3),
        "inPoint": round(float(clip.get("inPoint", 0)), 3),
        "outPoint": round(float(clip.get("outPoint", 0)), 3),
        "sourceDuration": round(float(meta.get("duration", 0) or 0), 3),
        "volume": round(float(clip.get("volume", 1) or 1), 4),
    }


# ── captions ─────────────────────────────────────────────────────────────────
# Render emits one karaoke subtitle per SEGMENT with a word-level `words` array.
# A whole spoken sentence held on screen for 5s is a document, not a caption —
# the word timings are the whole point, and flattening them threw that away.
# So chunk each segment into short phrases on its own words, and hand OpenCut one
# styled, animated text element per phrase.

CAPTION_MAX_WORDS = 3
CAPTION_MAX_SECONDS = 1.1
# How long a caption may linger past its own last word, waiting for the next
# phrase. Long enough to bridge a breath, short enough that a real pause clears.
CAPTION_MAX_HOLD = 0.45
# Punctuation ends a phrase early: the break should land where the speaker
# actually stopped, not mid-clause because we hit a word count.
CAPTION_BREAK_CHARS = (".", ",", "!", "?", "…", ";", ":")

# fontSize is NOT pixels. OpenCut renders text at
#   px = fontSize * canvasHeight / FONT_SIZE_SCALE_REFERENCE   (reference = 90)
# so one unit ≈ height/90 px, and its own subtitle default is 5. Everything in
# CAPTION_STYLE is in those units; treating them as pixels renders one letter the
# size of the screen. Position and width caps depend on the frame, so they're
# computed per project in caption_style_for() rather than baked for 1080x1920.
FONT_SIZE_REFERENCE = 90
CAPTION_FONT_UNITS = 6            # ≈128px tall on a 1920 frame; scales with height
CAPTION_HEIGHT_FRACTION = 0.72    # baseline sits ~72% down the frame


def caption_style_for(width: int, height: int) -> tuple[dict, int]:
    """Caption style + max chars-per-line, derived from the project frame so
    captions read the same on vertical, landscape, or square."""
    px = CAPTION_FONT_UNITS * height / FONT_SIZE_REFERENCE
    # Anton runs ~0.46em per char; keep a line within ~92% of the frame width.
    max_chars = max(6, int((width * 0.92) / (px * 0.46)))
    # transform.positionY is in PIXELS, offset from the vertical centre (unlike
    # fontSize, which is in /90 units) — so +422 on a 1920 frame is ~72% down.
    pos_y = round((CAPTION_HEIGHT_FRACTION - 0.5) * height)
    style = {
        "fontFamily": "Anton",   # condensed heavy display — the caption-forward look
        "fontSize": CAPTION_FONT_UNITS,
        "color": "#FFFFFF",
        "textAlign": "center",
        "letterSpacing": 0,
        "lineHeight": 1.1,
        "background.enabled": True,
        "background.color": "#000000CC",
        "background.cornerRadius": 10,
        "background.paddingX": 22,
        "background.paddingY": 12,
        "transform.positionY": pos_y,
    }
    return style, max_chars


def _chunk_words(words: list[dict], max_chars: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        nxt = cur + [w]
        width = len(" ".join(str(x.get("text", "")).strip() for x in nxt))
        # Break BEFORE adding, when the word would overflow the line — otherwise
        # the chunk is already too wide by the time we notice.
        if cur and width > max_chars:
            chunks.append(cur)
            cur = [w]
        else:
            cur = nxt
        text = str(w.get("text", "")).strip()
        span = float(cur[-1].get("endTime", 0)) - float(cur[0].get("startTime", 0))
        if (len(cur) >= CAPTION_MAX_WORDS
                or span >= CAPTION_MAX_SECONDS
                or text.endswith(CAPTION_BREAK_CHARS)):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_captions(subtitles: list[dict], width: int = 1080, height: int = 1920) -> list[dict]:
    caption_style, max_chars = caption_style_for(width, height)
    out: list[dict] = []
    for sub in subtitles:
        words = sub.get("words") or []
        if not words:
            # No word timings (older sessions) — keep the segment as one block.
            start = round(float(sub.get("startTime", 0)), 3)
            end = round(float(sub.get("endTime", start)), 3)
            out.append({"startTime": start, "duration": round(max(end - start, 0.1), 3),
                        "content": sub.get("text", ""), "params": dict(caption_style),
                        "keyframes": []})
            continue

        for chunk in _chunk_words(words, max_chars):
            start = round(float(chunk[0].get("startTime", 0)), 3)
            end = round(float(chunk[-1].get("endTime", start)), 3)
            dur = round(max(end - start, 0.12), 3)
            content = " ".join(str(w.get("text", "")).strip() for w in chunk).strip()
            if not content:
                continue
            # Uppercase: at this size and weight it reads as a caption rather
            # than a sentence, and keeps block height uniform across cuts.
            content = content.upper()

            # Pop-in: fast scale settling to 1, plus a couple of frames of fade.
            # Short enough to land inside even a 0.2s word.
            pop = min(0.09, dur * 0.35)
            keyframes = [
                {"property": "scale.x", "time": 0.0, "value": 0.86},
                {"property": "scale.y", "time": 0.0, "value": 0.86},
                {"property": "scale.x", "time": round(pop, 3), "value": 1.0},
                {"property": "scale.y", "time": round(pop, 3), "value": 1.0},
                {"property": "opacity", "time": 0.0, "value": 0.0},
                {"property": "opacity", "time": round(min(0.05, dur * 0.2), 3), "value": 1.0},
            ]
            out.append({
                "startTime": start,
                "duration": dur,
                "content": content,
                "params": dict(caption_style),
                "keyframes": keyframes,
            })

    # Hold each caption until the next one starts. A chunk only spans its own
    # words, so without this the caption blinks out in every inter-word pause —
    # visible flicker on a track that should read as continuous. Capped so a long
    # silence (or a segment boundary) doesn't leave a stale line on screen.
    for cur, nxt in zip(out, out[1:]):
        gap_end = float(nxt["startTime"])
        own_end = float(cur["startTime"]) + float(cur["duration"])
        hold_to = min(gap_end, own_end + CAPTION_MAX_HOLD)
        if hold_to > own_end:
            cur["duration"] = round(hold_to - float(cur["startTime"]), 3)
    return out


def convert(session_dir: Path, use_proxies: bool = True) -> dict:
    name = session_dir.name
    src = session_dir / f"{name}.openreel.json"
    if not src.exists():
        # Fall back to the legacy project.openreel.json some early sessions used.
        legacy = session_dir / "project.openreel.json"
        if legacy.exists():
            src = legacy
        else:
            raise FileNotFoundError(f"No openreel.json in {session_dir}")

    doc = json.loads(src.read_text(encoding="utf-8"))
    project = doc.get("project", doc)  # tolerate bare-project files
    settings = project.get("settings", {})
    items = {m["id"]: m for m in project.get("mediaLibrary", {}).get("items", [])}
    tracks = project.get("timeline", {}).get("tracks", [])

    # Auto-prefer a proxy when one exists. tools/media/proxy.py downscales
    # oversized sources into assets/proxies/<same-name>; the editor decodes those
    # instead of 4K originals. Doing the swap HERE means proxies "just work" — no
    # separate repoint step, and a session with no proxies is unaffected.
    #
    # The catch: OpenCut's exporter encodes whatever the timeline references, so
    # a proxied import ships that crf-23 veryfast downscale as the FINAL video —
    # the original 4K source never reaches the encoder. Hence --originals: edit
    # against proxies for a smooth timeline, then re-import with use_proxies=False
    # before the export that actually goes out.
    proxy_names = ({p.name for p in (session_dir / "assets" / "proxies").glob("*")}
                   if use_proxies else set())

    def _proxied(url: str) -> str:
        base = url.replace("\\", "/").rsplit("/", 1)[-1]
        if base in proxy_names and "/assets/source_pool/" in url:
            return url.replace("/assets/source_pool/", "/assets/proxies/")
        return url

    used_media: dict[str, dict] = {}

    def _register(media_id: str) -> dict | None:
        m = items.get(media_id)
        if not m:
            return None
        if media_id not in used_media:
            meta = m.get("metadata", {}) or {}
            url = _proxied(m.get("originalUrl") or m.get("thumbnailUrl") or "")
            entry = {
                "id": media_id,
                "url": url,
                "mediaType": _kind_for(m.get("type", "video")),
                "name": m.get("name", "")[:80],
                "sourceDuration": round(float(meta.get("duration", 0) or 0), 3),
                "width": int(meta.get("width", 0) or 0),
                "height": int(meta.get("height", 0) or 0),
                "fps": float(meta.get("frameRate", 0) or 0),
                "hasAudio": int(meta.get("channels", 0) or 0) > 0,
            }
            # A proxy has different pixel dims than the original; correct them so
            # the editor's fit/scale math matches what it actually decodes.
            if "/assets/proxies/" in url:
                pf = session_dir / "assets" / "proxies" / url.rsplit("/", 1)[-1]
                pw, ph = _probe_proxy_dims(pf)
                if pw and ph:
                    entry["width"], entry["height"] = pw, ph
            used_media[media_id] = entry
        return m

    main_elements: list[dict] = []
    main_transitions: list[dict] = []
    main_muted = True  # render mutes every video lane; default safe if absent
    overlay_tracks: list[dict] = []
    audio_lanes: list[dict] = []

    for track in tracks:
        tname = track.get("name", "")
        ttype = track.get("type", "")
        clips = track.get("clips", [])
        if not clips:
            continue  # skip empty scaffolding lanes for the spike

        if ttype == "video" and tname == MAIN_VIDEO_TRACK:
            # Load-bearing: source clips keep their own audio (YouTube rips especially),
            # and render mutes the video lanes so nothing competes with the voiceover.
            # Dropping this flag let the whole main spine talk over the VO.
            main_muted = bool(track.get("muted", True))
            for c in clips:
                m = _register(c["mediaId"])
                if m and used_media.get(c["mediaId"], {}).get("url"):
                    main_elements.append(_video_element(c, m))
            # Carry transitions (crossfades) for the seed to fake via overlap.
            main_transitions = [
                {"clipAId": t.get("clipAId"), "clipBId": t.get("clipBId"),
                 "type": t.get("type", "crossfade"),
                 "duration": round(float(t.get("duration", 0.4)), 3)}
                for t in (track.get("transitions") or [])
            ]
        elif ttype == "video" and tname in OVERLAY_VIDEO_TRACKS:
            els = []
            for c in clips:
                m = _register(c["mediaId"])
                if m and used_media.get(c["mediaId"], {}).get("url"):
                    els.append(_video_element(c, m))
            if els:
                overlay_tracks.append({"name": tname, "elements": els,
                                       "muted": bool(track.get("muted", True))})
        elif ttype == "audio" and tname in AUDIO_TRACKS:
            els = []
            for c in clips:
                m = _register(c["mediaId"])
                if m and used_media.get(c["mediaId"], {}).get("url"):
                    els.append(_audio_element(c, m))
            if els:
                audio_lanes.append({"name": tname, "elements": els,
                                    "muted": bool(track.get("muted", False))})

    proj_w = int(settings.get("width", 1080))
    proj_h = int(settings.get("height", 1920))
    text_blocks = build_captions(
        project.get("timeline", {}).get("subtitles", []), proj_w, proj_h)

    # Only ship media actually referenced by a kept element.
    media = [used_media[mid] for mid in used_media if used_media[mid]["url"]]

    return {
        "project": {
            "id": f"esta-{name}",
            "name": project.get("name", name),
            "width": int(settings.get("width", 1080)),
            "height": int(settings.get("height", 1920)),
            "fps": int(settings.get("frameRate", 30)),
        },
        "media": media,
        "tracks": {
            "main": {"name": "Main", "elements": main_elements,
                     "transitions": main_transitions, "muted": main_muted},
            "overlay": overlay_tracks,
            "audio": audio_lanes,
        },
        "text": text_blocks,
        "_summary": {
            "media": len(media),
            "main": len(main_elements),
            "overlay": sum(len(t["elements"]) for t in overlay_tracks),
            "audio": sum(len(t["elements"]) for t in audio_lanes),
            "text": len(text_blocks),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenReel project → OpenCut import intermediate")
    ap.add_argument("--session", required=True, help="Path to sessions/<id>")
    ap.add_argument("--out", default=None, help="Output path (default: <session>/esta-import.json)")
    ap.add_argument("--emit", default=None,
                    help="Also copy the import here (e.g. the OpenCut clone's "
                         "apps/web/public/esta-import.json), so seed + edit is one command")
    ap.add_argument("--originals", action="store_true",
                    help="Point the timeline at the original sources instead of the "
                         "downscaled proxies. Use this for the import you EXPORT from: "
                         "OpenCut encodes whatever the timeline references, so a proxied "
                         "import would ship a crf-23 re-encode as the final video.")
    args = ap.parse_args()

    session_dir = Path(args.session)
    try:
        result = convert(session_dir, use_proxies=not args.originals)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)

    summary = result.pop("_summary")
    out = Path(args.out) if args.out else session_dir / "esta-import.json"
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    out.write_text(payload, encoding="utf-8")
    emitted = None
    if args.emit:
        emit = Path(args.emit)
        emit.parent.mkdir(parents=True, exist_ok=True)
        emit.write_text(payload, encoding="utf-8")
        emitted = str(emit)
    print(json.dumps({"ok": True, "output": str(out), "emitted": emitted,
                      "proxies": not args.originals, **summary}))


if __name__ == "__main__":
    main()
