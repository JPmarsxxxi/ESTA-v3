"""Found-audio fetch — Phase 3 of notes/smart-pipeline-and-found-audio.md.

Searches free audio/SFX/music sources by theme and downloads a tagged pool into
sessions/<id>/audio_pool/, writing sessions/<id>/audio_pool.json. This is the
input the scriptwriter `arranger` mode (Phase 4) synthesises the narration from,
and that audio `assemble` (Phase 5) stitches into audio.wav.

Search functions mirror tools/assets/search.py: each returns a list of candidate
dicts and NEVER raises (returns [] on any error) so the orchestrator aggregates
freely. A candidate is:

    {source, kind, title, id, download_url, page_url, duration, license,
     attribution, ext, query}

Licensing: honors requirements.licensing. `free_only` skips YouTube (arbitrary
copyrighted uploads); every other source here is CC / PD / royalty-free.

Notes on source availability (resolved during build):
- Pixabay has no public *audio* API (images/video only) — omitted.
- Free Music Archive's public API is discontinued — omitted.
- LibriVox audio is hosted on the Internet Archive, so `mediatype:audio` search
  already surfaces it — no separate LibriVox integration.
"""

import json
import sys
from pathlib import Path

UA = "ESTA-Pipeline/1.0 (video generation; found-audio)"

# Sources skipped when requirements.licensing == "free_only" (copyrighted grabs).
_FAIR_USE_ONLY_SOURCES = {"youtube"}

# YouTube length cap — drop full movies / hours-long compilations a search may
# surface (we want a short clip, not a 1.7 GB film). A capped clip's audio is
# small enough to fetch whole; the arranger trims it to the line.
MAX_YT_DURATION = 600.0

AUDIO_EXTS = (".mp3", ".ogg", ".oga", ".wav", ".flac", ".m4a", ".aac", ".opus")


# ── per-source search (each returns list[dict], never raises) ─────────────────

def search_freesound(query: str, api_key: str, limit: int = 5,
                     max_duration: float | None = None) -> list:
    """Freesound — SFX, ambience, field recordings (CC). Uses the HQ preview mp3
    as the download URL (full-quality download needs OAuth2; previews don't).

    max_duration: when set, ask the API for sounds no longer than this and sort
    shortest-first. Relevance sort surfaces long field recordings/loops, so a
    punctuation SFX search ("record scratch", "riser") otherwise returns nothing
    usable — filtering server-side gets short takes directly."""
    if not api_key:
        return []
    try:
        import requests
        params = {
            "query": query, "token": api_key, "page_size": limit,
            "fields": "id,name,previews,duration,license,username,url",
        }
        if max_duration is not None:
            # Constrain length server-side but keep RELEVANCE ranking (the default):
            # sorting by duration returns the shortest loosely-matching blip
            # ('engine rev' -> a 0.3s creak), whereas relevance within a short-only
            # filter returns the best-matching sound that's already brief. Floor at
            # 0.3s to drop click/fragment noise.
            params["filter"] = f"duration:[0.3 TO {max_duration}]"
        r = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params=params,
            headers={"User-Agent": UA}, timeout=12,
        )
        if r.status_code != 200:
            return []
        out = []
        for h in r.json().get("results", []):
            dl = (h.get("previews") or {}).get("preview-hq-mp3", "")
            if not dl:
                continue
            out.append({
                "source": "freesound", "kind": "sfx",
                "title": (h.get("name") or "")[:80], "id": str(h.get("id", "")),
                "download_url": dl, "page_url": h.get("url", ""),
                "duration": round(float(h.get("duration", 0) or 0), 2),
                "license": h.get("license", ""), "attribution": h.get("username", ""),
                "ext": "mp3", "query": query,
            })
        return out
    except Exception:
        return []


def search_openverse_audio(query: str, limit: int = 5) -> list:
    """Openverse audio index — CC music/audio aggregated across sources. No key."""
    try:
        import requests
        r = requests.get(
            "https://api.openverse.org/v1/audio/",
            params={"q": query, "page_size": limit},
            headers={"User-Agent": UA}, timeout=12,
        )
        if r.status_code != 200:
            return []
        out = []
        for a in r.json().get("results", []):
            dl = a.get("url", "")
            if not dl:
                continue
            raw_ext = dl.split("?")[0].rsplit(".", 1)[-1].lower()
            ext = raw_ext if raw_ext in {"mp3", "ogg", "oga", "wav", "flac"} else "mp3"
            dur_ms = a.get("duration") or 0
            out.append({
                "source": "openverse", "kind": "music",
                "title": (a.get("title") or "")[:80], "id": str(a.get("id", "")),
                "download_url": dl, "page_url": a.get("foreign_landing_url", ""),
                "duration": round(float(dur_ms) / 1000.0, 2) if dur_ms else 0.0,
                "license": f"{a.get('license','')} {a.get('license_version','')}".strip(),
                "attribution": a.get("creator", ""), "ext": ext, "query": query,
            })
        return out
    except Exception:
        return []


def search_archive_audio(query: str, limit: int = 4) -> list:
    """Internet Archive (mediatype:audio) — found voices: OTR, PD film audio,
    speeches, music, LibriVox spoken word. License varies by item."""
    try:
        import requests
        r = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"({query}) AND mediatype:audio",
                "fl[]": ["identifier", "title", "licenseurl"],
                "rows": limit, "page": 1, "output": "json",
                "sort": "downloads desc",
            },
            headers={"User-Agent": UA}, timeout=15,
        )
        if r.status_code != 200:
            return []
        out = []
        for doc in r.json().get("response", {}).get("docs", []):
            identifier = doc.get("identifier", "")
            try:
                meta = requests.get(
                    f"https://archive.org/metadata/{identifier}",
                    headers={"User-Agent": UA}, timeout=10,
                ).json()
                afiles = [
                    f for f in meta.get("files", [])
                    if f.get("name", "").lower().endswith(AUDIO_EXTS)
                ]
                if not afiles:
                    continue
                # smallest audio file = likely a single track, not a full set
                af = min(afiles, key=lambda f: int(f.get("size", 0) or 1 << 40))
                ext = af["name"].rsplit(".", 1)[-1].lower()
                out.append({
                    "source": "archive", "kind": "found",
                    "title": (doc.get("title", "") or identifier)[:80], "id": identifier,
                    "download_url": f"https://archive.org/download/{identifier}/{af['name']}",
                    "page_url": f"https://archive.org/details/{identifier}",
                    "duration": round(float(af.get("length", 0) or 0), 2) if str(af.get("length", "")).replace(".", "").isdigit() else 0.0,
                    "license": doc.get("licenseurl", "") or "archive/varies",
                    "attribution": f"archive.org/{identifier}", "ext": ext, "query": query,
                })
            except Exception:
                continue
        return out
    except Exception:
        return []


def search_wikimedia_audio(query: str, limit: int = 3) -> list:
    """Wikimedia Commons audio (filetype:audio) — PD/CC speeches, pronunciations,
    music. No key."""
    try:
        import requests
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            headers={"User-Agent": UA},
            params={
                "action": "query", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"filetype:audio {query}", "gsrlimit": limit,
                "prop": "imageinfo", "iiprop": "url|size|mime", "format": "json",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return []
        out = []
        for page in r.json().get("query", {}).get("pages", {}).values():
            ii = (page.get("imageinfo") or [{}])[0]
            if "audio" not in ii.get("mime", "") and "ogg" not in ii.get("mime", ""):
                continue
            url = ii.get("url", "")
            if not url:
                continue
            url_clean = url.split("?")[0]
            ext = url_clean.rsplit(".", 1)[-1].lower() if "." in url_clean else "ogg"
            out.append({
                "source": "wikimedia", "kind": "voice",
                "title": page.get("title", "")[:80], "id": str(page.get("pageid", "")),
                "download_url": url_clean, "page_url": url_clean,
                "duration": 0.0, "license": "wikimedia/varies",
                "attribution": page.get("title", ""), "ext": ext, "query": query,
            })
        return out
    except Exception:
        return []


def search_ccmixter(query: str, limit: int = 3) -> list:
    """ccMixter — CC music, remixes, acapella/vocal stems. No key. Best-effort:
    the API schema is loose, so we tolerate missing fields."""
    try:
        import requests
        r = requests.get(
            "http://ccmixter.org/api/query",
            params={"f": "json", "search": query, "limit": limit, "sort": "rank"},
            headers={"User-Agent": UA}, timeout=12,
        )
        if r.status_code != 200:
            return []
        out = []
        for up in r.json():
            files = up.get("files") or []
            audio = next((f for f in files if str(f.get("download_url", "")).lower().endswith(AUDIO_EXTS)), None)
            if not audio:
                continue
            dl = audio.get("download_url", "")
            ext = dl.rsplit(".", 1)[-1].lower()
            out.append({
                "source": "ccmixter", "kind": "music",
                "title": (up.get("upload_name") or "")[:80], "id": str(up.get("upload_id", "")),
                "download_url": dl, "page_url": up.get("file_page_url", ""),
                "duration": 0.0, "license": up.get("license_name", "CC"),
                "attribution": up.get("user_name", ""), "ext": ext, "query": query,
            })
        return out
    except Exception:
        return []


def search_youtube_audio(query: str, limit: int = 3) -> list:
    """YouTube via the yt_dlp Python API — copyrighted dialogue/songs/clips.
    Gated to fair_use_ok by the orchestrator. Audio is extracted at download
    time. NOTE: use the library, NOT the yt-dlp executable — the .exe is blocked
    by Device Guard on this machine (assets/search.py uses the API for the same
    reason)."""
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        out = []
        for v in (info or {}).get("entries", []) or []:
            vid = v.get("id", "")
            if not vid:
                continue
            dur = float(v.get("duration") or 0)
            if not (0 < dur <= MAX_YT_DURATION):
                continue  # skip full movies / long compilations / unknown-length
            out.append({
                "source": "youtube", "kind": "clip",
                "title": (v.get("title") or "")[:80], "id": vid,
                "download_url": f"https://www.youtube.com/watch?v={vid}",
                "page_url": f"https://www.youtube.com/watch?v={vid}",
                "duration": round(dur, 2),
                "license": "copyrighted/fair-use",
                "attribution": v.get("uploader", "") or v.get("channel", ""),
                "ext": "mp3", "query": query,
            })
        return out
    except Exception:
        return []


SOURCE_FNS = {
    "freesound":  lambda q, keys, n: search_freesound(q, keys.get("freesound_key", ""), n),
    "openverse":  lambda q, keys, n: search_openverse_audio(q, n),
    "archive":    lambda q, keys, n: search_archive_audio(q, n),
    "wikimedia":  lambda q, keys, n: search_wikimedia_audio(q, n),
    "ccmixter":   lambda q, keys, n: search_ccmixter(q, n),
    "youtube":    lambda q, keys, n: search_youtube_audio(q, n),
}

# Default source order by licensing stance.
DEFAULT_SOURCES_FREE = ["freesound", "openverse", "archive", "wikimedia", "ccmixter"]
DEFAULT_SOURCES_FAIR = ["youtube", "freesound", "archive", "openverse", "wikimedia", "ccmixter"]


# ── download ──────────────────────────────────────────────────────────────────

def _download_direct(url: str, dest: Path) -> bool:
    try:
        import requests
        with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=60) as r:
            if r.status_code != 200:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        return dest.exists() and dest.stat().st_size > 0
    except Exception:
        return False


def _download_youtube_audio(url: str, dest_stem: Path) -> Path | None:
    """Extract bestaudio to mp3 via the yt_dlp Python API + ffmpeg postprocessor
    (the .exe is Device-Guard-blocked here). dest_stem has no extension."""
    try:
        import yt_dlp
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        opts = {
            "quiet": True, "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": str(dest_stem) + ".%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3", "preferredquality": "0"}],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        hits = list(dest_stem.parent.glob(dest_stem.name + ".*"))
        mp3 = [h for h in hits if h.suffix.lower() == ".mp3"]
        return (mp3 or hits)[0] if hits else None
    except Exception:
        return None


# ── orchestrator ────────────────────────────────────────────────────────────

def _load_keys() -> dict:
    import yaml
    cfg = Path(__file__).resolve().parents[2] / "config.yaml"
    try:
        return (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("apis", {})
    except Exception:
        return {}


def _session_licensing(session_dir: Path) -> str:
    try:
        val = json.loads((session_dir / "requirements.json").read_text(encoding="utf-8")).get("licensing")
        if val in ("free_only", "fair_use_ok"):
            return val
    except Exception:
        pass
    return "fair_use_ok"


def fetch_pool(session_dir: Path, queries: list[str], sources: list[str] | None = None,
               per_source: int = 4, download: bool = True) -> dict:
    licensing = _session_licensing(session_dir)
    keys = _load_keys()
    pool_dir = session_dir / "audio_pool"

    if sources is None:
        sources = DEFAULT_SOURCES_FREE if licensing == "free_only" else DEFAULT_SOURCES_FAIR
    # Gate copyrighted sources under free_only.
    active = [s for s in sources if not (licensing == "free_only" and s in _FAIR_USE_ONLY_SOURCES)]
    skipped = [s for s in sources if s not in active]

    seen: set[str] = set()
    clips: list[dict] = []
    for query in queries:
        for src in active:
            fn = SOURCE_FNS.get(src)
            if not fn:
                continue
            for cand in fn(query, keys, per_source):
                key = f"{cand['source']}:{cand['id']}"
                if key in seen:
                    continue
                seen.add(key)
                clips.append(cand)
            print(f"[found-fetch] {src} [{query!r}]: pool now {len(clips)}", flush=True)

    downloaded = 0
    if download:
        for c in clips:
            stem = pool_dir / f"{c['source']}_{c['id']}"
            if c["source"] == "youtube":
                # idempotent: reuse an already-extracted file if present
                have = list(pool_dir.glob(f"{c['source']}_{c['id']}.*")) if pool_dir.exists() else []
                have = [h for h in have if h.stat().st_size > 0]
                if have:
                    c["file"] = str(have[0]); c["ext"] = have[0].suffix.lstrip("."); downloaded += 1
                    continue
                got = _download_youtube_audio(c["download_url"], stem)
                if got:
                    c["file"] = str(got); c["ext"] = got.suffix.lstrip("."); downloaded += 1
                else:
                    c["file"] = ""
            else:
                dest = pool_dir / f"{c['source']}_{c['id']}.{c['ext']}"
                if dest.exists() and dest.stat().st_size > 0:
                    c["file"] = str(dest); downloaded += 1          # idempotent reuse
                elif _download_direct(c["download_url"], dest):
                    c["file"] = str(dest); downloaded += 1
                else:
                    c["file"] = ""

    pool = {
        "session_id": session_dir.name,
        "queries": queries,
        "licensing": licensing,
        "sources_used": active,
        "sources_skipped_licensing": skipped,
        "counts": {"candidates": len(clips), "downloaded": downloaded},
        "clips": clips,
    }
    (session_dir / "audio_pool.json").write_text(
        json.dumps(pool, indent=2, ensure_ascii=False), encoding="utf-8")
    return pool


def cmd_found_fetch(args) -> None:
    session_dir = Path(args.session)
    if not (session_dir / "requirements.json").exists():
        print(json.dumps({"ok": False, "error": "requirements.json missing"}))
        sys.exit(1)
    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None
    pool = fetch_pool(
        session_dir, args.queries, sources=sources,
        per_source=args.per_source, download=not args.no_download,
    )
    print(json.dumps({
        "ok": True, "output": str(session_dir / "audio_pool.json"),
        "licensing": pool["licensing"], "sources_used": pool["sources_used"],
        "sources_skipped_licensing": pool["sources_skipped_licensing"],
        **pool["counts"],
    }))
