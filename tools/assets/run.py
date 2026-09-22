"""CLI entry point for the assets skill.

Called by SKILL.md via:
    conda run -n esta python tools/assets/run.py fetch --session sessions/<id>

Streams shots from plan_progress.jsonl as they arrive (written by the plan skill),
falls back to plan.json when it exists. Searches each shot across sources in
cascading rounds (stop early at TARGET_CANDIDATES), downloads the best candidate,
processes the clip to match shot duration, writes progress to assets_progress.jsonl,
and writes final assets.json.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET_CANDIDATES = 5  # stop cascading once we have this many candidates
# D1: resolution floor for downloaded YouTube clips. Overridable per-shot via the
# `shot --min-height` flag (which sets ESTA_MIN_VIDEO_HEIGHT) — lower it for
# vintage/SD source material (e.g. a 1976 film) where no 720p upload exists.
MIN_VIDEO_HEIGHT = int(os.environ.get("ESTA_MIN_VIDEO_HEIGHT", "720"))
# D2: float-comparison tolerance for the duration floor. A segment cut to exactly
# the target length subtracts to e.g. 3.1999999999999886 — well inside a frame at
# any sane fps, so treat it as meeting the floor.
_DURATION_FLOOR_EPSILON = 0.05

# Default source order when visual.search_sources is absent (old plans).
# Pinterest joins REAL_IMAGE low/medium as a moodboard-style addition; the
# plan SKILL promotes it to FIRST position when a shot's desc cues aesthetic /
# vibe / minimalist content.
_DEFAULT_SOURCES = {
    ("REAL_FOOTAGE", "high"):   [("youtube", 1), ("archive", 1)],
    ("REAL_FOOTAGE", "medium"): [("pexels_video", 1), ("pixabay_video", 1), ("archive", 2), ("youtube", 3)],
    ("REAL_FOOTAGE", "low"):    [("pexels_video", 1), ("pixabay_video", 1), ("archive", 2), ("youtube", 3)],
    ("REAL_IMAGE",   "high"):   [("google_images", 1), ("wikimedia", 2)],
    ("REAL_IMAGE",   "medium"): [("pexels_image", 1), ("pixabay_image", 1), ("pinterest", 2), ("wikimedia", 2)],
    ("REAL_IMAGE",   "low"):    [("pexels_image", 1), ("pixabay_image", 1), ("pinterest", 2), ("wikimedia", 2)],
    ("MOTION_GRAPHICS", "high"):   [("giphy", 1), ("pixabay_image", 1)],
    ("MOTION_GRAPHICS", "medium"): [("giphy", 1), ("pixabay_image", 1)],
    ("MOTION_GRAPHICS", "low"):    [("giphy", 1), ("pixabay_image", 1)],
}

# Sources that surface copyrighted material (arbitrary uploads / editorial press
# photos). Skipped when requirements.licensing == "free_only"; everything else
# (Pexels/Pixabay/Wikimedia/Archive/Giphy/Openverse) is royalty-free / CC / PD.
_FAIR_USE_ONLY_SOURCES = {"youtube", "google_images"}

# Presentation metadata for the picker's source bank. The bank ITSELF is always
# derived from _build_source_fn_map's keys (see cmd_sources) so a new source
# shows up in the UI the moment it's searchable — these dicts only decorate it.
_SOURCE_KIND = {
    "pexels_video": "video", "pixabay_video": "video", "archive": "video",
    "youtube": "video", "giphy": "gif",
    "pexels_image": "image", "pixabay_image": "image", "wikimedia": "image",
    "openverse": "image", "google_images": "image", "pinterest": "image",
}
# config.apis key each source needs; absent = keyless (no API key required).
_SOURCE_API_KEY = {
    "pexels_video": "pexels_key", "pexels_image": "pexels_key",
    "pixabay_video": "pixabay_key", "pixabay_image": "pixabay_key",
    "giphy": "giphy_key",
}


# ── Config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    import yaml
    cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _session_licensing(session_dir: Path) -> str:
    """Project licensing stance from requirements.json. Absent (older sessions)
    -> 'fair_use_ok' so existing behavior is unchanged; only an explicit
    'free_only' restricts sources."""
    req_path = session_dir / "requirements.json"
    try:
        val = json.loads(req_path.read_text(encoding="utf-8")).get("licensing")
        if val in ("free_only", "fair_use_ok"):
            return val
    except Exception:
        pass
    return "fair_use_ok"


# ── Shot streaming ────────────────────────────────────────────────────────────

def _stream_shots(progress_path: Path, plan_path: Path, poll_interval: int = 2, timeout: int = 900):
    """Yield shots from plan_progress.jsonl as they arrive, then drain plan.json."""
    cursor = 0
    seen: set[int] = set()
    deadline = time.time() + timeout

    while time.time() < deadline:
        if progress_path.exists():
            with open(progress_path, encoding="utf-8") as f:
                f.seek(cursor)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            shot = json.loads(line)
                            n = shot["shot_number"]
                            if n not in seen:
                                seen.add(n)
                                yield shot
                        except json.JSONDecodeError:
                            pass
                cursor = f.tell()

        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                for shot in plan.get("shots", []):
                    n = shot["shot_number"]
                    if n not in seen:
                        seen.add(n)
                        yield shot
            except Exception:
                pass
            return  # plan complete — stop polling

        time.sleep(poll_interval)


# ── Candidate scoring ─────────────────────────────────────────────────────────

def _score_candidate(c: dict, visual_type: str, shot_dur: float, description: str = "") -> float:
    score = 0.0

    # Landscape + resolution
    w, h = c.get("width", 0), c.get("height", 0)
    if w > 0 and h > 0:
        if w >= h:
            score += 2.0
        if w >= 1280:
            score += 1.0

    # Type match: reward candidates that match the intended asset type
    ctype = c.get("type", "")
    if visual_type == "REAL_FOOTAGE" and ctype == "video":
        score += 2.0
    elif visual_type == "REAL_IMAGE" and ctype == "image":
        score += 2.0
    elif visual_type == "MOTION_GRAPHICS" and ctype == "gif":
        score += 2.0

    # Duration fit for video shots
    if visual_type == "REAL_FOOTAGE" and ctype == "video":
        dur = c.get("duration", 0)
        if dur > 0 and shot_dur > 0:
            ratio = min(dur, shot_dur) / max(dur, shot_dur)
            score += ratio * 3.0

    # Keyword overlap between shot description and asset title
    if description:
        desc_words = set(description.lower().split())
        title_words = set(c.get("title", "").lower().split())
        score += len(desc_words & title_words) * 0.5

    # Source preference — content-aware. For meme/reaction or motion-graphics
    # shots, giphy is the canonical library and should beat pexels/pixabay
    # generic stock. For normal real-world content, pexels wins on quality.
    _meme_cues = ("meme", "reaction", "this is fine", "shrug", "facepalm", "face palm", "sike")
    is_meme_coded = bool(description) and any(cue in description.lower() for cue in _meme_cues)
    if is_meme_coded or visual_type == "MOTION_GRAPHICS":
        source_pref = {"giphy": 4, "pexels": 2, "pixabay": 2, "wikimedia": 1, "archive": 1, "youtube": 1}
    else:
        source_pref = {"pexels": 3, "pixabay": 2, "giphy": 2, "wikimedia": 1, "archive": 1, "youtube": 1}
    score += source_pref.get(c.get("source", ""), 0)

    # Visual validation result — a confirmed match must outrank any unvalidated or mismatch
    verdict = c.get("visual_verdict", "")
    vis_conf = c.get("visual_confidence", 50)
    if verdict == "match":
        score += 10.0 + vis_conf / 100 * 5.0
    elif verdict == "mismatch":
        score -= 5.0

    return score


def _pick_best(candidates: list, visual_type: str, shot_dur: float, description: str = "") -> dict | None:
    if not candidates:
        return None
    scored = [(c, _score_candidate(c, visual_type, shot_dur, description)) for c in candidates]
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


# ── Download ──────────────────────────────────────────────────────────────────

def _download_file(url: str, dest: Path, timeout: int = 30) -> bool:
    import requests
    if "wikimedia" in url and "?" in url:
        url = url.split("?")[0]
    headers = {"User-Agent": "ESTA-Pipeline/1.0 (video generation; github.com/esta-v2)"}
    for attempt in range(3):
        try:
            resp = requests.get(url, stream=True, timeout=timeout, headers=headers)
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"[assets] 429 rate limit — retrying in {wait}s", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            return True
        except Exception as exc:
            print(f"[assets] download failed ({url[:60]}): {exc}", file=sys.stderr, flush=True)
            return False
    return False


def _download_youtube_full(url: str, dest: Path) -> bool:
    """Download the best available YouTube quality (E1: no range-trim).

    Copied from the ESTA-Final notebook's proven download (workers/secretary):
    a best-first format with a progressive fallback + a browser user-agent, and
    NO height floor. YouTube now gates 720p+ behind PO tokens for anonymous
    clients, so a hard >=720 floor just turns gated videos into placeholders.
    Best-available keeps real HD wherever YouTube still serves it and degrades
    gracefully to whatever's offered otherwise — always returning footage.

    Source media is kept inviolate — trim lives in assets.json as in_point/
    out_point, applied by render/the editor — so a cut can be extended later.
    """
    try:
        import yt_dlp
        dest.parent.mkdir(parents=True, exist_ok=True)
        opts = {
            "quiet": True,
            "no_warnings": True,
            # Notebook parity: best-available, mp4-preferred, progressive fallback.
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",  # land the video+audio merge as .mp4 (dest ext)
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "outtmpl": str(dest),
            "overwrites": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return dest.exists()
    except Exception as exc:
        print(f"[assets] YouTube download failed: {exc}", file=sys.stderr, flush=True)
        return False


def _probe_resolution(path: Path) -> tuple[int, int]:
    """Return (width, height) of a video's first stream via ffprobe, or (0, 0)."""
    import subprocess
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout.strip()
        if "x" in out:
            w, h = out.split("x")[:2]
            return int(w), int(h)
    except Exception:
        pass
    return 0, 0


def _placeholder_result(n: int, query: str, error: str) -> dict:
    """Uniform failure result so every shot entry carries the full ShotAsset shape."""
    return {
        "shot_number": n, "ok": False,
        "source": "", "asset_type": "placeholder",
        "url": "", "file": "", "search_query": query,
        "in_point": 0.0, "out_point": 0.0,
        "visual_verdict": "", "visual_confidence": 0,
        "error": error,
    }


def _source_path(assets_dir: Path, candidate: dict) -> Path:
    """E1+E2: stable path in the shared source_pool for a candidate's full source.

    Keyed by source + id so shots that share an upload point at ONE file on disk
    (different in/out points). For YouTube the key is the video id parsed from
    the watch URL, so different detected moments of the same upload dedupe.
    """
    src = candidate.get("source", "src")
    ext = candidate.get("ext", "mp4")
    if src == "youtube":
        vid = candidate.get("url", "").split("v=")[-1].split("&")[0] or "unknown"
        key = f"yt_{vid}"
    else:
        key = f"{src}_{candidate.get('id', 'x')}"
    return assets_dir / "source_pool" / f"{key}.{ext}"


# ── Shared source dispatch ───────────────────────────────────────────────────

def _build_source_fn_map(config: dict, *, shot_audio: str, description: str,
                         target_dur: float, instance_markers: dict | None,
                         yt_cache_dir: Path) -> dict:
    """source name → callable(query) → candidates.

    Shared by the auto path (`_fetch_shot`, which then validates + picks one) and
    the picker path (`cmd_candidates`, which downloads them all for a human).
    Both must search identically — only what happens *after* the search differs.
    """
    from tools.assets.search import (
        search_pexels_video, search_pexels_image,
        search_pixabay_video, search_pixabay_image,
        search_giphy, search_wikimedia, search_archive, search_youtube,
        search_openverse, search_google_images, search_pinterest,
    )
    apis = config.get("apis", {})
    pexels_key  = apis.get("pexels_key", "")
    pixabay_key = apis.get("pixabay_key", "")
    giphy_key   = apis.get("giphy_key", "")
    return {
        "pexels_video":  lambda q: search_pexels_video(q, pexels_key) if pexels_key else [],
        "pexels_image":  lambda q: search_pexels_image(q, pexels_key) if pexels_key else [],
        "pixabay_video": lambda q: search_pixabay_video(q, pixabay_key) if pixabay_key else [],
        "pixabay_image": lambda q: search_pixabay_image(q, pixabay_key) if pixabay_key else [],
        "giphy":         lambda q: search_giphy(q, giphy_key) if giphy_key else [],
        "wikimedia":     lambda q: search_wikimedia(q),
        "archive":       lambda q: search_archive(q),
        # YouTube keeps its vision moment-finder even on the picker path: a 4-min
        # movie can't be judged from a thumbnail grid, so finding the moment IS
        # the value. Stock sources get no vision — the human is the validator.
        "youtube":       lambda q: search_youtube(q, shot_audio, description, target_dur, instance_markers, yt_cache_dir),
        "openverse":     lambda q: search_openverse(q),
        "google_images": lambda q: search_google_images(q),
        "pinterest":     lambda q: search_pinterest(q),
    }


# ── Per-shot fetch (cascading search) ────────────────────────────────────────

def _fetch_shot(shot: dict, assets_dir: Path, config: dict) -> dict:
    from tools.assets.processor import _get_duration

    apis = config.get("apis", {})
    pexels_key  = apis.get("pexels_key", "")
    pixabay_key = apis.get("pixabay_key", "")
    giphy_key   = apis.get("giphy_key", "")
    licensing   = config.get("licensing", "fair_use_ok")

    n = shot["shot_number"]
    visual = shot.get("visual", {})
    vtype = visual.get("type", "REAL_FOOTAGE")
    query = visual.get("search_query", "")
    # P0 fix: plan SKILL produces "desc"; old code looked up "description".
    # Result: validator + scoring received empty description, which is the
    # actual root cause of the tonal-mismatch failures (B1 prompt rewrite is
    # only effective once the description actually flows through).
    description = visual.get("desc", "") or visual.get("description", "")
    shot_audio = shot.get("audio", "")
    # B3: instance markers (event_date, location, key_participants,
    # expected_outcome, exclude) let the validator reject a confidently-wrong
    # clip of the right TOPIC but wrong INSTANCE. Optional — None when the plan
    # didn't mark this shot as instance-specific.
    instance_markers = visual.get("instance_markers") or None
    # Real timing when reconcile has run, estimates otherwise. While assets streams
    # from plan_progress.jsonl the two are identical; once timestamps.json lands,
    # start/end carry the true slot length and the estimates can be far off (a slow
    # read stretches a 6.4s estimate into a 7.5s slot), which would cut every clip
    # short of the slot it has to fill.
    shot_dur = max((shot.get("end", 0) - shot.get("start", 0)), 2.0)
    if shot_dur <= 2.0:
        shot_dur = max((shot.get("end_est", 0) - shot.get("start_est", 0)), 2.0)

    # D2: slow_motion shots play the source at half speed, so they need 2x the
    # shot's length of footage. This multiplier gates the duration floor below
    # AND is passed to search_youtube — the moment finder sizes its segment from
    # the length it's given, so handing it the un-multiplied shot_dur would build
    # clips that the floor is then guaranteed to reject.
    fx = visual.get("fx", []) or []
    duration_multiplier = 2.0 if "slow_motion" in fx else 1.0
    min_video_dur = shot_dur * duration_multiplier

    # E2: per-session source-pool cache for worst-quality full-video downloads.
    # Shared across shots and across `shot` retries, so the same upload isn't
    # re-downloaded for visual search/validation when several shots hit it.
    yt_cache_dir = assets_dir / ".cache" / "youtube"

    specificity = visual.get("specificity", "low")
    search_sources = visual.get("search_sources")  # list of {source, queries} — from plan skill

    print(f"[assets] shot {n:02d} | {vtype} | {specificity} | {query!r}", flush=True)

    candidates: list[dict] = []
    seen_ids: set[str] = set()

    def _absorb(new: list) -> None:
        for c in new:
            key = f"{c['source']}:{c['id']}"
            if key not in seen_ids:
                seen_ids.add(key)
                candidates.append(c)

    source_fn_map = _build_source_fn_map(
        config, shot_audio=shot_audio, description=description,
        target_dur=min_video_dur, instance_markers=instance_markers,
        yt_cache_dir=yt_cache_dir,
    )

    def _run_source(source: str, queries: list[str]) -> None:
        """Run one source with its query variants, stop when TARGET reached."""
        if licensing == "free_only" and source in _FAIR_USE_ONLY_SOURCES:
            print(f"[assets]   {source}: skipped (licensing=free_only)", flush=True)
            return
        fn = source_fn_map.get(source)
        if not fn:
            return
        for q in queries:
            if len(candidates) >= TARGET_CANDIDATES:
                return
            if _have_strong_match():
                print(f"[assets]   early exit: 90%+ match already found", flush=True)
                return
            try:
                results = fn(q)
                before = len(candidates)
                _absorb(results)
                added = len(candidates) - before
                print(f"[assets]   {source} [{q!r}]: {len(results)} results (+{added} new)", flush=True)
            except Exception as exc:
                print(f"[assets]   {source}: failed ({exc})", file=sys.stderr, flush=True)

    def _have_strong_match() -> bool:
        return any(
            c.get("visual_verdict") == "match" and c.get("visual_confidence", 0) >= 90
            for c in candidates
        )

    # ── Execute search_sources from plan (preferred path) ─────────────────────
    if search_sources:
        for entry in search_sources:
            if len(candidates) >= TARGET_CANDIDATES:
                break
            if _have_strong_match():
                print(f"[assets]   early exit: 90%+ match already found", flush=True)
                break
            source = entry.get("source", "")
            queries = entry.get("queries", [query])
            _run_source(source, queries)

    else:
        # ── Fallback: type + specificity defaults (old plans without search_sources) ─
        defaults = _DEFAULT_SOURCES.get((vtype, specificity),
                   _DEFAULT_SOURCES.get((vtype, "low"), []))

        # Group by level and run level by level
        from itertools import groupby
        for level, group in groupby(defaults, key=lambda x: x[1]):
            if len(candidates) >= TARGET_CANDIDATES:
                break
            level_sources = list(group)
            tasks: dict[str, callable] = {}
            for source, _ in level_sources:
                fn = source_fn_map.get(source)
                if fn:
                    tasks[source] = fn  # will use primary query

            with ThreadPoolExecutor(max_workers=max(len(tasks), 1)) as pool:
                futs = {pool.submit(fn, query): src for src, fn in tasks.items()}
                for fut in as_completed(futs):
                    src = futs[fut]
                    try:
                        results = fut.result(timeout=15)
                        before = len(candidates)
                        _absorb(results)
                        print(f"[assets]   {src}: {len(results)} results (+{len(candidates)-before} new)", flush=True)
                    except Exception as exc:
                        print(f"[assets]   {src}: failed ({exc})", file=sys.stderr, flush=True)

        # Broad query fallback if still thin
        if len(candidates) < 3 and len(query.split()) > 3:
            broad = " ".join(query.split()[:3])
            print(f"[assets]   broadening to: {broad!r}", flush=True)
            for source, _ in defaults[:2]:
                fn = source_fn_map.get(source)
                if fn:
                    try:
                        _absorb(fn(broad))
                    except Exception:
                        pass

    if not candidates:
        print(f"[assets] shot {n:02d}: no candidates found", flush=True)
        return _placeholder_result(n, query, "no candidates found")

    # D2: enforce duration floor on video candidates (min_video_dur computed
    # above, alongside the slow_motion multiplier). Static images, motion
    # graphics, and Giphy mp4 loops are unaffected.
    def _meets_duration_floor(c: dict) -> bool:
        if c.get("type") != "video":
            return True  # static images / no duration constraint
        if c.get("source") == "giphy":
            return True  # giphy mp4s loop fine
        cdur = c.get("duration", 0) or 0
        # Tolerance: YouTube segments are built as exactly the requested length
        # (best_ts ± target/2), and float subtraction lands a hair under it far
        # more often than not — an exact >= here silently binned every YouTube
        # candidate, validated 95% matches included.
        return cdur >= min_video_dur - _DURATION_FLOOR_EPSILON

    before_floor = len(candidates)
    candidates = [c for c in candidates if _meets_duration_floor(c)]
    dropped = before_floor - len(candidates)
    if dropped:
        print(f"[assets] shot {n:02d}: dropped {dropped} video candidate(s) below {min_video_dur:.1f}s floor", flush=True)

    if not candidates:
        return _placeholder_result(n, query, f"no candidates meet duration floor ({min_video_dur:.1f}s)")

    # C1: visual-validate stock + scraped candidates. Tagging is noisy — keyword
    # scoring alone ships wrong clips — so mirror the YouTube path and attach
    # visual_verdict/visual_confidence. Scoring then ranks a confirmed match
    # above any mismatch, and the B2 floor below fails the shot loudly if every
    # validated candidate is a mismatch.
    #
    # Pexels/Pixabay are API-served with usable tags, so they're validated only
    # at medium/high specificity — low-spec generic b-roll is fine on any
    # on-topic stock and strict validation would only strand it on a placeholder.
    # PINTEREST is different: it's scraped, so it can return non-photo junk
    # (e.g. Pinterest's own gradient UI asset) that keyword/dimension scoring
    # won't catch. So pinterest is validated at EVERY specificity. Verdict-aware
    # ranking buries the junk; low-spec shots still never hard-fail (see B2), so
    # a usable pick always ships.
    if description:
        from tools.assets.search import validate_stock_candidate

        def _should_validate(c: dict) -> bool:
            if c.get("visual_verdict"):
                return False
            src = c.get("source")
            if src == "pinterest":
                return True
            return src in ("pexels", "pixabay") and specificity != "low"

        to_validate = [c for c in candidates if _should_validate(c)]

        def _validate_one(c: dict) -> None:
            res = validate_stock_candidate(c, query, description, shot_audio, instance_markers)
            if res:
                c["visual_confidence"] = res.get("confidence", 50)
                c["visual_verdict"] = "match" if res.get("matches") else "mismatch"
                print(f"[assets] shot {n:02d}: {c['source']} {c['type']} validation: "
                      f"{c['visual_verdict']} ({c['visual_confidence']}%)", flush=True)

        if to_validate:
            with ThreadPoolExecutor(max_workers=min(len(to_validate), 4)) as pool:
                list(pool.map(_validate_one, to_validate))

    # B2: if the validator ran and nothing came back as a confident match, fail
    # loudly rather than silently shipping the "least bad" mismatch with ok=True.
    # Gated to medium/high: those shots demand a confirmed match. Low-spec shots
    # are lenient by design — a validated mismatch is de-ranked by
    # _score_candidate (−5) but still ships if it's all we have, so we never
    # strand an aesthetic b-roll shot on a placeholder.
    validated = [c for c in candidates if c.get("visual_verdict") in ("match", "mismatch")]
    has_strong_match = any(
        c.get("visual_verdict") == "match" and c.get("visual_confidence", 0) >= 50
        for c in validated
    )
    if specificity != "low" and validated and not has_strong_match:
        print(f"[assets] shot {n:02d}: all validated candidates were mismatches — ok=False", flush=True)
        return _placeholder_result(n, query, "no candidates passed visual validation (all mismatch or low confidence)")

    # Sort all candidates by score and try in order until one downloads
    ranked = sorted(candidates,
                    key=lambda c: _score_candidate(c, vtype, shot_dur, description),
                    reverse=True)

    # E1: download the FULL source (untrimmed) into the shared source_pool, and
    # dedupe — if the source is already on disk (this run, an earlier shot, or a
    # prior `shot` retry) reuse it instead of re-downloading. Several shots that
    # share an upload point at ONE file with different in/out points.
    raw_dest = None
    best = None
    for candidate in ranked:
        dest = _source_path(assets_dir, candidate)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists() and dest.stat().st_size > 1024:
            print(f"[assets] shot {n:02d}: source_pool hit → {dest.name} (no re-download)", flush=True)
            best, raw_dest = candidate, dest
            break

        if candidate["source"] == "youtube":
            # Notebook parity: accept the best YouTube serves (no height floor).
            ok = _download_youtube_full(candidate["url"], dest)
        else:
            ok = _download_file(candidate["url"], dest)

        if not ok:
            dest.unlink(missing_ok=True)  # clear partials so a later dedup check can't pick up garbage
            continue

        best, raw_dest = candidate, dest
        break

    if not best or not raw_dest:
        return _placeholder_result(n, query, "all downloads failed")

    # ── E1: record the trim window; leave the source untouched ────────────────
    # No trim, no re-encode. in/out_point are seconds INTO the full source where
    # this shot's content sits; render (and the editor) apply them and can drag
    # the cut wider because every frame is on disk. Static images get 0/0.
    if best["type"] == "video" and raw_dest.suffix.lower() in {".mp4", ".mov", ".avi", ".webm"}:
        source_dur = _get_duration(raw_dest)
        if best["source"] == "youtube":
            in_pt = float(best.get("_yt_start", 0.0))
            out_pt = float(best.get("_yt_end", in_pt + shot_dur))
        else:
            in_pt = 0.0
            out_pt = min(source_dur, shot_dur) if source_dur > 0 else shot_dur
        if source_dur > 0:
            out_pt = min(out_pt, source_dur)
        if out_pt <= in_pt:
            out_pt = in_pt + shot_dur
    else:
        in_pt, out_pt = 0.0, 0.0

    print(f"[assets] shot {n:02d}: ✓ {best['source']} {best['type']} → {raw_dest.name} "
          f"[{in_pt:.1f}s→{out_pt:.1f}s]", flush=True)
    return {
        "shot_number": n, "ok": True,
        "source": best["source"], "asset_type": best["type"],
        "url": best["url"], "file": str(raw_dest),
        "search_query": query,
        "in_point": round(in_pt, 3), "out_point": round(out_pt, 3),
        "visual_verdict": best.get("visual_verdict", ""),
        "visual_confidence": int(best.get("visual_confidence", 0) or 0),
        "error": "",
    }


# ── Main command ──────────────────────────────────────────────────────────────

def _composite_subshots(shot: dict):
    """Yield ("<n>-slot<k>", pseudo-shot) for a composite shot's panels 1..N.

    Slot 0 is the shot's own asset under its normal key, so a composite costs
    nothing for the single-asset path and renders as a normal shot until the
    extra panels land. Each panel is fetched as if it were its own shot — same
    search machinery, same duration floor — because from the fetcher's point of
    view that is exactly what it is.
    """
    composite = shot.get("composite") or {}
    slots = composite.get("slots") or []
    for k in range(1, min(len(slots), 3)):   # 3 video tracks == 3 panels
        slot = slots[k] or {}
        sub = dict(shot)
        sub["shot_number"] = f"{shot['shot_number']}-slot{k}"
        sub["visual"] = {
            "type": slot.get("type") or "REAL_IMAGE",
            "specificity": slot.get("specificity") or "low",
            "desc": slot.get("desc", ""),
            "search_query": slot.get("search_query", ""),
            "search_sources": slot.get("search_sources") or [],
            "fx": [],
        }
        sub.pop("composite", None)           # panels don't nest
        sub.pop("overlay", None)
        yield sub["shot_number"], sub


def cmd_fetch(args: argparse.Namespace) -> None:
    config = _load_config()
    session_dir = Path(args.session)
    config["licensing"] = _session_licensing(session_dir)
    plan_path = session_dir / "plan.json"
    progress_path = session_dir / "plan_progress.jsonl"
    assets_dir = session_dir / "assets"
    assets_progress_path = session_dir / "assets_progress.jsonl"

    assets_dir.mkdir(parents=True, exist_ok=True)

    results: dict[int, dict] = {}

    print(f"[assets] watching {progress_path.name} for shots...", flush=True)

    slot_results: dict[str, dict] = {}

    def _emit(res: dict) -> None:
        with open(assets_progress_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(res) + "\n")
            f.flush()

    for shot in _stream_shots(progress_path, plan_path):
        result = _fetch_shot(shot, assets_dir, config)
        results[shot["shot_number"]] = result
        _emit(result)

        # Composite panels stream the same way, so the frame fills in panel by
        # panel on the live timeline rather than waiting for the whole shot.
        for key, sub in _composite_subshots(shot):
            sres = _fetch_shot(sub, assets_dir, config)
            sres["shot_number"] = key
            slot_results[key] = sres
            _emit(sres)

    fetched = sum(1 for r in results.values() if r.get("ok"))
    failed = len(results) - fetched

    output = {
        "session_id": session_dir.name,
        "shots_total": len(results),
        "shots_fetched": fetched,
        "shots_failed": failed,
        "shots": {**{str(k): v for k, v in sorted(results.items())},
                  **dict(sorted(slot_results.items()))},
        "timestamp": datetime.now().isoformat(),
    }

    output_path = session_dir / "assets.json"
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "output": str(output_path),
        "shots_total": len(results),
        "shots_fetched": fetched,
        "shots_failed": failed,
    }), flush=True)


def cmd_candidates(args: argparse.Namespace) -> None:
    """Collect EVERY plausible candidate for one shot and download them all.

    The picker path. Deliberately does NOT do what `fetch`/`shot` do after the
    search: no stock visual-validation, no verdict-aware ranking, no early exit
    on a "strong match", no auto-pick. Those exist so Claude can choose without
    the user — vision calls that are slow, expensive, and structurally unable to
    judge taste. Here the human chooses, so the machine's job is only to gather.

    YouTube is the exception and keeps its vision moment-finder (see
    `_build_source_fn_map`): a 4-minute movie can't be judged from a grid, so
    locating the moment inside it is real work, not a taste call.

    Writes assets/candidates/shot_<n>.json — the manifest the picker UI reads.
    Nothing is written to assets_progress.jsonl until the user picks.
    """
    config = _load_config()
    session_dir = Path(args.session)
    config["licensing"] = _session_licensing(session_dir)
    assets_dir = session_dir / "assets"
    cand_dir = assets_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)

    plan = json.loads((session_dir / "plan.json").read_text(encoding="utf-8"))
    shot = next((s for s in plan.get("shots", []) if s.get("shot_number") == args.n), None)
    if shot is None:
        raise ValueError(f"shot {args.n} not in plan.json")

    n = shot["shot_number"]
    visual = shot.get("visual", {})
    description = visual.get("desc", "") or visual.get("description", "")
    shot_audio = shot.get("audio", "")
    instance_markers = visual.get("instance_markers") or None
    shot_dur = max((shot.get("end", 0) - shot.get("start", 0)), 2.0)
    if shot_dur <= 2.0:
        shot_dur = max((shot.get("end_est", 0) - shot.get("start_est", 0)), 2.0)
    fx = visual.get("fx", []) or []
    min_video_dur = shot_dur * (2.0 if "slow_motion" in fx else 1.0)

    # Overrides let the picker UI re-run with edited queries/sources without
    # touching plan.json — the user is iterating, not amending the plan.
    if args.queries:
        queries = [q.strip() for q in args.queries.split("|") if q.strip()]
    else:
        queries = None
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    else:
        sources = None

    search_sources = visual.get("search_sources") or []
    if sources is not None:
        base_q = queries or [visual.get("search_query", "")]
        search_sources = [{"source": s, "queries": base_q} for s in sources]
    elif queries is not None:
        search_sources = [{"source": e.get("source", ""), "queries": queries}
                          for e in search_sources]

    yt_cache_dir = assets_dir / ".cache" / "youtube"
    source_fn_map = _build_source_fn_map(
        config, shot_audio=shot_audio, description=description,
        target_dur=min_video_dur, instance_markers=instance_markers,
        yt_cache_dir=yt_cache_dir,
    )
    licensing = config.get("licensing", "fair_use_ok")
    per_source = max(1, args.per_source)

    print(f"[candidates] shot {n:02d} | dur {shot_dur:.2f}s | floor {min_video_dur:.2f}s "
          f"| {per_source}/source", flush=True)

    collected: list[dict] = []
    seen: set[str] = set()
    for entry in search_sources:
        source = entry.get("source", "")
        if licensing == "free_only" and source in _FAIR_USE_ONLY_SOURCES:
            print(f"[candidates]   {source}: skipped (licensing=free_only)", flush=True)
            continue
        fn = source_fn_map.get(source)
        if not fn:
            continue
        for q in entry.get("queries", []):
            # Quota is per source PER QUERY, not per source: the user lists
            # several queries precisely to see different angles, so letting the
            # first one fill the quota would silently discard the rest.
            got = 0
            try:
                results = fn(q)
            except Exception as exc:
                print(f"[candidates]   {source}: failed ({exc})", file=sys.stderr, flush=True)
                continue
            for c in results:
                if got >= per_source:
                    break
                key = f"{c['source']}:{c['id']}"
                if key in seen:
                    continue
                # The duration floor stays: a clip shorter than the slot can't
                # fill it whatever the user thinks of it. Everything else is
                # taste, and taste is the user's.
                if c.get("type") == "video" and c.get("source") != "giphy":
                    if (c.get("duration", 0) or 0) < min_video_dur - _DURATION_FLOOR_EPSILON:
                        continue
                seen.add(key)
                c["_query"] = q
                collected.append(c)
                got += 1
            print(f"[candidates]   {source} [{q!r}]: {len(results)} results, {got} kept", flush=True)

    # Download every survivor — the user can't pick what isn't on disk.
    from tools.assets.processor import _get_duration
    out: list[dict] = []
    for c in collected:
        dest = _source_path(assets_dir, c)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 1024:
            pass  # source_pool hit — shared across shots and re-runs
        elif c["source"] == "youtube":
            if not _download_youtube_full(c["url"], dest):
                dest.unlink(missing_ok=True)
                continue
        elif not _download_file(c["url"], dest):
            dest.unlink(missing_ok=True)
            continue

        if c["type"] == "video" and dest.suffix.lower() in {".mp4", ".mov", ".avi", ".webm"}:
            source_dur = _get_duration(dest)
            if c["source"] == "youtube":
                in_pt = float(c.get("_yt_start", 0.0))
                out_pt = float(c.get("_yt_end", in_pt + shot_dur))
            else:
                in_pt = 0.0
                out_pt = min(source_dur, shot_dur) if source_dur > 0 else shot_dur
            if source_dur > 0:
                out_pt = min(out_pt, source_dur)
            if out_pt <= in_pt:
                out_pt = in_pt + shot_dur
        else:
            source_dur, in_pt, out_pt = 0.0, 0.0, 0.0

        out.append({
            "candidate_id": f"{c['source']}:{c['id']}",
            "source": c["source"], "asset_type": c["type"],
            "query": c.get("_query", ""),
            "url": c["url"], "file": str(dest).replace("\\", "/"),
            "title": c.get("title", ""), "thumb": c.get("thumb", ""),
            "width": c.get("width", 0), "height": c.get("height", 0),
            "source_duration": round(source_dur, 3),
            "in_point": round(in_pt, 3), "out_point": round(out_pt, 3),
        })
        print(f"[candidates]   ✓ {c['source']} → {dest.name}", flush=True)

    manifest = {
        "session_id": session_dir.name,
        "shot_number": n,
        "audio": shot_audio,
        "desc": description,
        "shot_duration": round(shot_dur, 3),
        "queries": [q for e in search_sources for q in e.get("queries", [])],
        "sources": [e.get("source", "") for e in search_sources],
        "candidates": out,
        "generated_at": datetime.now().isoformat(),
    }
    (cand_dir / f"shot_{n}.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"ok": True, "shot": n, "candidates": len(out)}), flush=True)


def cmd_shot(args: argparse.Namespace) -> None:
    """Fetch a single shot by number, optionally overriding source/query.

    Used for narrated, shot-by-shot inspection runs. Reads the shot from
    plan.json, optionally rewrites its search_sources with the override pair,
    fetches, appends to assets_progress.jsonl, and rewrites assets.json with
    the merged shot result.
    """
    # --min-height override: lower the resolution floor for this shot (vintage/SD
    # source). Set both the module global (used by the yt-dlp format string + the
    # post-download probe) and the env var (read by search.py's search filter).
    if getattr(args, "min_height", None):
        global MIN_VIDEO_HEIGHT
        MIN_VIDEO_HEIGHT = args.min_height
        os.environ["ESTA_MIN_VIDEO_HEIGHT"] = str(args.min_height)
        print(f"[assets] min-height override: {args.min_height}p (default {720}p)", flush=True)

    config = _load_config()
    session_dir = Path(args.session)
    config["licensing"] = _session_licensing(session_dir)
    plan_path = session_dir / "plan.json"
    assets_dir = session_dir / "assets"
    assets_progress_path = session_dir / "assets_progress.jsonl"
    assets_json_path = session_dir / "assets.json"

    if not plan_path.exists():
        raise FileNotFoundError(f"{plan_path} not found")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    shot = next((s for s in plan.get("shots", []) if s.get("shot_number") == args.n), None)
    if shot is None:
        raise ValueError(f"shot {args.n} not in plan.json")

    if args.source and args.query:
        shot = json.loads(json.dumps(shot))  # deep copy
        shot.setdefault("visual", {})["search_sources"] = [
            {"source": args.source, "queries": [args.query]}
        ]
        shot["visual"]["search_query"] = args.query

    assets_dir.mkdir(parents=True, exist_ok=True)
    result = _fetch_shot(shot, assets_dir, config)

    with open(assets_progress_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")

    if assets_json_path.exists():
        existing = json.loads(assets_json_path.read_text(encoding="utf-8"))
    else:
        existing = {
            "session_id": session_dir.name,
            "shots_total": len(plan.get("shots", [])),
            "shots_fetched": 0,
            "shots_failed": 0,
            "shots": {},
        }
    existing["shots"][str(args.n)] = result
    fetched = sum(1 for r in existing["shots"].values() if r.get("ok"))
    existing["shots_fetched"] = fetched
    existing["shots_failed"] = len(existing["shots"]) - fetched
    existing["timestamp"] = datetime.now().isoformat()
    assets_json_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"ok": result.get("ok", False), "shot": args.n, "result": result}), flush=True)


def cmd_sources(args: argparse.Namespace) -> None:
    """Emit the full source bank as JSON — what the picker offers the user.

    The plan prescribes 2-3 sources per shot; that's a starting point, not a
    cap. The bank is enumerated from _build_source_fn_map so it can never drift
    from what's actually searchable, and each entry carries why it might be
    unusable (missing API key, or blocked by a free_only licensing stance).
    """
    config = _load_config()
    licensing = "fair_use_ok"
    if getattr(args, "session", None):
        session_dir = Path(args.session)
        licensing = _session_licensing(session_dir)
    config["licensing"] = licensing

    fn_map = _build_source_fn_map(
        config, shot_audio="", description="", target_dur=0.0,
        instance_markers=None, yt_cache_dir=Path("."),
    )
    apis = config.get("apis", {})

    bank = []
    for name in fn_map:
        key_field = _SOURCE_API_KEY.get(name)
        has_key = bool(apis.get(key_field, "")) if key_field else True
        fair_use_only = name in _FAIR_USE_ONLY_SOURCES
        blocked = licensing == "free_only" and fair_use_only
        reason = ""
        if not has_key:
            reason = f"no {key_field} in config.yaml"
        elif blocked:
            reason = "licensing=free_only"
        bank.append({
            "name": name,
            "kind": _SOURCE_KIND.get(name, "media"),
            "needs_key": key_field or "",
            "available": has_key and not blocked,
            "fair_use_only": fair_use_only,
            "unavailable_reason": reason,
        })

    print(json.dumps({"ok": True, "licensing": licensing, "sources": bank}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA assets tool")
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("fetch", help="Fetch assets for all shots in session")
    p.add_argument("--session", required=True, help="Path to session dir (e.g. sessions/foo-2026-05-11)")

    s = sub.add_parser("shot", help="Fetch a single shot, with optional source/query override")
    s.add_argument("--session", required=True)
    s.add_argument("--n", type=int, required=True, help="Shot number")
    s.add_argument("--source", help="Override source (e.g. youtube, pexels_video)")
    s.add_argument("--query", help="Override query string")
    s.add_argument("--min-height", type=int, dest="min_height",
                   help="Override the 720p video floor for this shot (e.g. 360 for vintage/SD source material)")

    c = sub.add_parser("candidates",
                       help="Download every plausible candidate for one shot (no vision on stock, no auto-pick) — feeds the picker UI")
    c.add_argument("--session", required=True)
    c.add_argument("--n", type=int, required=True, help="Shot number")
    c.add_argument("--per-source", type=int, default=4, dest="per_source",
                   help="Max candidates to keep per source PER QUERY (default 4)")
    c.add_argument("--queries", help="Override queries, '|'-separated — picker sends edits here")
    c.add_argument("--sources", help="Override sources, comma-separated — picker sends edits here")

    b = sub.add_parser("sources",
                       help="Print the full source bank as JSON (name, kind, availability) — feeds the picker's source chips")
    b.add_argument("--session", help="Session dir; only affects the licensing stance applied")

    args = parser.parse_args()

    try:
        if args.mode == "fetch":
            cmd_fetch(args)
        elif args.mode == "shot":
            cmd_shot(args)
        elif args.mode == "candidates":
            cmd_candidates(args)
        elif args.mode == "sources":
            cmd_sources(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
