"""Asset search functions — one per source, all return list[dict] candidates.

Each candidate dict matches AssetCandidate schema. Functions never raise —
they return [] on any error so the caller can aggregate freely.
"""

import os
import threading
import time
from pathlib import Path
from typing import Any

# ── E2: per-process source-pool caches ───────────────────────────────────────
# Shots that share a topic (same fixture, speech, launch, …) repeatedly hit the
# same YouTube search, transcript, format probe, and worst-quality download.
# These caches dedupe that work within a bulk fetch run. Keyed by query (search)
# or video id (transcript / height) so a video resurfacing under a *different*
# query still hits the id-keyed caches. The on-disk video cache (see
# _ensure_full_video) additionally survives across separate `shot` invocations.
_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE: dict[str, list] = {}             # query -> flat ytsearch entries
_TRANSCRIPT_CACHE: dict[str, Any] = {}          # video_id -> raw transcript or None
_HEIGHT_CACHE: dict[str, int] = {}              # video_id -> best available height


# ── Pexels ───────────────────────────────────────────────────────────────────

def search_pexels_video(query: str, api_key: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for v in r.json().get("videos", []):
            files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0), reverse=True)
            if not files:
                continue
            f = files[0]
            candidates.append({
                "source": "pexels", "type": "video",
                "url": f.get("link", ""), "thumb": v.get("image", ""),
                "title": f"Pexels {v['id']}", "id": str(v["id"]),
                "width": f.get("width", 0), "height": f.get("height", 0),
                "duration": float(v.get("duration", 0)), "ext": "mp4",
            })
        return candidates
    except Exception:
        return []


def search_pexels_image(query: str, api_key: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for p in r.json().get("photos", []):
            candidates.append({
                "source": "pexels", "type": "image",
                "url": p["src"].get("original", ""), "thumb": p["src"].get("tiny", ""),
                "title": f"Pexels {p['id']}", "id": str(p["id"]),
                "width": p.get("width", 0), "height": p.get("height", 0),
                "duration": 0.0, "ext": "jpg",
            })
        return candidates
    except Exception:
        return []


# ── Pixabay ──────────────────────────────────────────────────────────────────

def search_pixabay_video(query: str, api_key: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": api_key, "q": query, "per_page": 5},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for h in r.json().get("hits", []):
            videos = h.get("videos", {})
            best = videos.get("large") or videos.get("medium") or videos.get("small") or {}
            url = best.get("url", "")
            if not url:
                continue
            candidates.append({
                "source": "pixabay", "type": "video",
                "url": url, "thumb": videos.get("tiny", {}).get("thumbnail", ""),
                "title": f"Pixabay {h['id']}", "id": str(h["id"]),
                "width": best.get("width", 0), "height": best.get("height", 0),
                "duration": float(h.get("duration", 0)), "ext": "mp4",
            })
        return candidates
    except Exception:
        return []


def search_pixabay_image(query: str, api_key: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://pixabay.com/api/",
            params={"key": api_key, "q": query, "per_page": 5,
                    "safesearch": "true", "orientation": "horizontal"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for h in r.json().get("hits", []):
            url = h.get("largeImageURL", "")
            if not url:
                continue
            candidates.append({
                "source": "pixabay", "type": "image",
                "url": url, "thumb": h.get("previewURL", ""),
                "title": f"Pixabay {h['id']}", "id": str(h["id"]),
                "width": h.get("imageWidth", 0), "height": h.get("imageHeight", 0),
                "duration": 0.0, "ext": "jpg",
            })
        return candidates
    except Exception:
        return []


# ── Giphy ────────────────────────────────────────────────────────────────────

def search_giphy(query: str, api_key: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://api.giphy.com/v1/gifs/search",
            params={"api_key": api_key, "q": query, "limit": 5, "rating": "g"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for g in r.json().get("data", []):
            original = g.get("images", {}).get("original", {})
            # Prefer the mp4 variant when Giphy returns one: ~5-10x smaller,
            # 24-bit colour (vs GIF's 256-colour palette), often higher fps, and
            # avoids a GIF->MP4 conversion pass downstream at render.
            mp4 = original.get("mp4", "")
            url = mp4 or original.get("url", "")
            if not url:
                continue
            asset_type = "video" if mp4 else "gif"
            ext = "mp4" if mp4 else "gif"
            candidates.append({
                "source": "giphy", "type": asset_type,
                "url": url, "thumb": g.get("images", {}).get("fixed_width_small", {}).get("url", ""),
                "title": g.get("title", "")[:60], "id": g.get("id", ""),
                "width": int(original.get("width", 0)), "height": int(original.get("height", 0)),
                "duration": 0.0, "ext": ext,
            })
        return candidates
    except Exception:
        return []


# ── Wikimedia Commons ────────────────────────────────────────────────────────

def search_wikimedia(query: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            headers={"User-Agent": "ESTA-Pipeline/1.0 (video generation; contact: esta@example.com)"},
            params={
                "action": "query", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": 3,
                "prop": "imageinfo", "iiprop": "url|size|mime",
                "iiurlwidth": 1200, "format": "json",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for page in r.json().get("query", {}).get("pages", {}).values():
            ii = page.get("imageinfo", [{}])[0]
            if "image" not in ii.get("mime", ""):
                continue
            url = ii.get("url", "")
            if not url:
                continue
            url_clean = url.split("?")[0]
            ext = url_clean.rsplit(".", 1)[-1].lower() if "." in url_clean else "jpg"
            candidates.append({
                "source": "wikimedia", "type": "image",
                "url": url_clean, "thumb": ii.get("thumburl", ""),
                "title": page.get("title", "")[:60], "id": str(page.get("pageid", "")),
                "width": ii.get("width", 0), "height": ii.get("height", 0),
                "duration": 0.0, "ext": ext,
            })
        return candidates
    except Exception:
        return []


# ── Archive.org ──────────────────────────────────────────────────────────────

def search_archive(query: str) -> list:
    try:
        import requests
        r = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"({query}) AND mediatype:movies",
                "fl[]": ["identifier", "title"],
                "rows": 5, "page": 1, "output": "json",
                "sort": "downloads desc",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for doc in r.json().get("response", {}).get("docs", []):
            identifier = doc.get("identifier", "")
            try:
                meta = requests.get(
                    f"https://archive.org/metadata/{identifier}", timeout=8
                ).json()
                vfiles = [
                    f for f in meta.get("files", [])
                    if f.get("name", "").endswith((".mp4", ".avi", ".mov", ".webm"))
                ]
                if not vfiles:
                    continue
                vf = vfiles[0]
                ext = vf["name"].rsplit(".", 1)[-1]
                candidates.append({
                    "source": "archive", "type": "video",
                    "url": f"https://archive.org/download/{identifier}/{vf['name']}",
                    "thumb": f"https://archive.org/services/img/{identifier}",
                    "title": doc.get("title", "")[:60], "id": identifier,
                    "width": 0, "height": 0, "duration": 0.0, "ext": ext,
                })
            except Exception:
                continue
        return candidates
    except Exception:
        return []


# ── OpenVerse (CC-licensed web image search — press photos, news, sports) ────

def search_openverse(query: str) -> list:
    """Search OpenVerse CC image index — aggregates Flickr, Wikimedia, and other
    CC sources. Good for named people, events, press photos. No API key required."""
    try:
        import requests
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 5},
            headers={"User-Agent": "ESTA-Pipeline/1.0 (video generation)"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        candidates = []
        for img in r.json().get("results", []):
            url = img.get("url", "")
            if not url:
                continue
            url_clean = url.split("?")[0]
            raw_ext = url_clean.rsplit(".", 1)[-1].lower()
            ext = raw_ext if raw_ext in {"jpg", "jpeg", "png", "webp"} else "jpg"
            candidates.append({
                "source": "openverse", "type": "image",
                "url": url_clean,
                "thumb": img.get("thumbnail", ""),
                "title": img.get("title", "")[:60],
                "id": img.get("id", ""),
                "width": img.get("width", 0) or 0,
                "height": img.get("height", 0) or 0,
                "duration": 0.0,
                "ext": ext,
            })
        return candidates
    except Exception:
        return []


# ── Google Images (Playwright — best for named people / events) ──────────────

def search_google_images(query: str, max_results: int = 6) -> list:
    """Headless Google Images search with CC+large filter via Playwright.

    Navigates to the CC-licensed large-images results page, downloads the full
    rendered HTML, then regex-extracts source image URLs from Google's embedded
    JSON data.  No LLM needed — pure DOM/HTML parsing.
    """
    try:
        import re
        import urllib.parse
        from playwright.sync_api import sync_playwright

        q = urllib.parse.quote_plus(query)
        # isz:l → large-images filter; hl=en,gl=us → consistent English layout.
        # CC-only filter (il:cl) intentionally dropped — it blocked every
        # named-subject press photo (athletes, public figures), which are
        # editorial-licensed not CC. Caller is responsible for licensing
        # compliance when using these results.
        url = f"https://www.google.com/search?q={q}&tbm=isch&tbs=isz:l&hl=en&gl=us"

        html = ""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1366, "height": 768},
            )
            page = ctx.new_page()

            try:
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
            except Exception:
                browser.close()
                return []

            # Dismiss GDPR / cookie consent pop-up (fired before images load)
            for sel in [
                "button#L2AGLb",
                "button[jsname='higCR']",
                "button[aria-label='Accept all']",
                "form[action*='consent'] button",
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(800)
                        break
                except Exception:
                    pass

            # Brief wait so JS-rendered image data lands in the DOM
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        if not html:
            return []

        # Google Images embeds full-res source URLs in JS data as JSON strings.
        # They appear as: ,"https://domain.com/photo.jpg",width,height,
        # Filter out Google-owned hosts (encrypted-tbn, gstatic, google, youtube).
        _BLOCKED = re.compile(
            r"encrypted-tbn|gstatic\.com|google\.com|youtube\.com|ytimg\.com",
            re.IGNORECASE,
        )
        # Pattern: "<image-url>",<width>,<height>, in Google's embedded JSON.
        # Capturing all three lets us apply a resolution floor and surface dims downstream.
        _URL_RE = re.compile(
            r'"(https?://[^"\\]+?\.(?:jpg|jpeg|png|webp))(?:\?[^"]*)?"\s*,\s*(\d+)\s*,\s*(\d+)',
            re.IGNORECASE,
        )

        MIN_RES = 600  # drop anything below 600×600

        seen: set[str] = set()
        candidates = []
        for m in _URL_RE.finditer(html):
            img_url = m.group(1)
            if img_url in seen or _BLOCKED.search(img_url):
                continue
            try:
                w = int(m.group(2))
                h = int(m.group(3))
            except (TypeError, ValueError):
                w, h = 0, 0
            if w < MIN_RES or h < MIN_RES:
                continue
            seen.add(img_url)
            raw_ext = img_url.rsplit(".", 1)[-1].lower().split("?")[0][:5]
            ext = raw_ext if raw_ext in {"jpg", "jpeg", "png", "webp"} else "jpg"
            candidates.append({
                "source": "google_images", "type": "image",
                "url": img_url, "thumb": img_url,
                "title": f"{query[:40]} (Google Images {len(candidates)+1})",
                "id": str(len(candidates)),
                "width": w, "height": h,
                "duration": 0.0, "ext": ext,
            })
            if len(candidates) >= max_results:
                break

        return candidates
    except Exception:
        return []


# ── Pinterest (Playwright scrape + Google Images fallback) ───────────────────

def search_pinterest(query: str, max_results: int = 8) -> list:
    """Pinterest pin search — best source for aesthetic / mood / vibe imagery.

    Pinterest's official API was deprecated for general search, so this scrapes
    pinterest.com/search/pins/?q=<query> via Playwright (same engine Google
    Images uses here). Pinterest's grid is React-rendered, so a brief wait is
    needed before the i.pinimg.com URLs land in the DOM.

    Order of preference, best-first:

    1. `pinterest_cache` — results harvested from the user's own logged-in
       browser. Preferred because Pinterest redirects ANONYMOUS visitors to the
       homepage, which is why the headless scrape below usually comes back
       empty; a logged-in session is the only thing that reliably sees a search
       grid. See tools/assets/pinterest_cache.py for how it's filled.
    2. The headless Playwright scrape — kept for the cases where it does work.
    3. Google Images with `site:pinterest.com` — last resort, and usually dead:
       Google answers automated traffic with a CAPTCHA. Do NOT build anything
       that tries to solve it.

    Pinterest content is user-uploaded and not CC; treat it as fair-use-ok
    reference imagery rather than royalty-free media.
    """
    from tools.assets.pinterest_cache import lookup as _cache_lookup

    cached = _cache_lookup(query, max_results)
    if len(cached) >= 3:
        return cached

    candidates = cached + _pinterest_playwright(query, max_results - len(cached))
    if len(candidates) >= 3:
        return candidates[:max_results]

    fallback = _pinterest_via_google(query, max_results - len(candidates))
    seen = {c["url"] for c in candidates}
    for c in fallback:
        if c["url"] not in seen:
            seen.add(c["url"])
            candidates.append(c)
    return candidates[:max_results]


def _pinterest_playwright(query: str, max_results: int) -> list:
    try:
        import re
        import urllib.parse
        from playwright.sync_api import sync_playwright

        q = urllib.parse.quote_plus(query)
        url = f"https://www.pinterest.com/search/pins/?q={q}&rs=typed"

        html = ""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1366, "height": 900},
            )
            page = ctx.new_page()

            try:
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
            except Exception:
                browser.close()
                return []

            # Pinterest sometimes shows a login modal over the grid; the grid
            # still renders behind it, so we just give the React app a beat to
            # populate the DOM, then read.
            page.wait_for_timeout(2500)
            try:
                # Scroll once so the lazy-loaded second row also lands in DOM.
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1200)
            except Exception:
                pass
            html = page.content()
            browser.close()

        if not html:
            return []

        # Pinterest CDN serves pins at fixed size buckets — originals/ is full
        # quality; 736x / 564x / 474x are progressively smaller thumbs. Prefer
        # originals; treat the larger thumbs as acceptable fallbacks.
        #
        # Match only jpg/jpeg/webp — photographic pins are always served as one
        # of these. Pinterest's own UI chrome (the gradient app-icon that shows
        # up first in EVERY search page, e.g. d53b…png) is served as PNG; if we
        # let PNGs through it becomes candidate #1 for every query and, on
        # low-specificity shots that skip visual validation, wins selection —
        # so every Pinterest shot collapses onto that one gradient. Dropping png
        # removes it. (heic isn't in the alternation either, so pins whose
        # originals/ is .heic auto-fall back to their 736x jpg.)
        _PINIMG_RE = re.compile(
            r"https://i\.pinimg\.com/(originals|736x|564x|474x)/"
            r"([0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32})"
            r"\.(jpg|jpeg|webp)",
            re.IGNORECASE,
        )
        # Known Pinterest UI/static assets (not pins) — defense-in-depth in case
        # one is ever served as jpg/webp.
        _PINTEREST_UI_ASSETS = {"d53b014d86a6b6761bf649a0ed813c2b"}
        # Approximate dimensions by bucket (Pinterest doesn't embed real dims).
        _BUCKET_DIM = {"originals": 1200, "736x": 736, "564x": 564, "474x": 474}

        # Pick the best resolution per pin (group by the path tail — the hash
        # is unique per pin; pinterest re-serves it at every bucket).
        best: dict[str, tuple[str, str, str]] = {}
        bucket_rank = {"originals": 4, "736x": 3, "564x": 2, "474x": 1}
        for m in _PINIMG_RE.finditer(html):
            bucket, path, ext = m.group(1).lower(), m.group(2), m.group(3).lower()
            if path[-32:] in _PINTEREST_UI_ASSETS:
                continue
            current = best.get(path)
            if current is None or bucket_rank[bucket] > bucket_rank[current[0]]:
                best[path] = (bucket, m.group(0), ext)

        candidates: list[dict] = []
        for path, (bucket, img_url, ext) in best.items():
            dim = _BUCKET_DIM.get(bucket, 600)
            if dim < 474:
                continue
            ext_norm = ext if ext in {"jpg", "jpeg", "webp"} else "jpg"
            candidates.append({
                "source": "pinterest", "type": "image",
                "url": img_url, "thumb": img_url,
                "title": f"Pinterest {path[-12:]}",
                "id": path,
                "width": dim, "height": dim,
                "duration": 0.0, "ext": ext_norm,
            })
            if len(candidates) >= max_results:
                break
        return candidates
    except Exception:
        return []


def _pinterest_via_google(query: str, max_results: int) -> list:
    """Google Images with site:pinterest.com — the fallback path. Google's
    index of Pinterest is staler than Pinterest itself but more reliable when
    the live scrape gets throttled."""
    if max_results <= 0:
        return []
    try:
        raw = search_google_images(f"{query} site:pinterest.com", max_results=max_results)
    except Exception:
        return []
    # Re-tag as pinterest source so downstream scoring/licensing treat it
    # consistently regardless of which path produced the URL.
    out: list[dict] = []
    for c in raw:
        # Skip anything Google indexed that isn't actually on the Pinterest CDN.
        if "pinimg.com" not in c.get("url", ""):
            continue
        c = dict(c)
        c["source"] = "pinterest"
        c["title"] = c.get("title", "").replace("Google Images", "Pinterest (via Google)")
        out.append(c)
    return out


# ── YouTube (LLM-guided: pick → transcript moment → visual validation) ────────

def _process_one_video(
    chosen: dict, query: str, shot_audio: str, shot_desc: str, target_dur: float,
    instance_markers: dict | None = None,
    cache_dir: Path | None = None,
) -> list[dict]:
    """Process one video: transcript/visual-search → validate. Returns candidates list."""
    from tools.assets.llm import find_moment_in_transcript

    vid_id  = chosen.get("id", "")
    vid_url = f"https://www.youtube.com/watch?v={vid_id}"
    vid_dur = float(chosen.get("duration") or 60.0)
    print(f"\n    [youtube] processing: {chosen.get('title','')[:55]}", flush=True)

    segments: list[dict] = []

    # Stage 2a: transcript moment finding (transcript is cached per video id)
    try:
        raw = _get_transcript(vid_id)
        if raw:
            print(f"    [youtube] english transcript: {len(raw)} segments", flush=True)
        else:
            print(f"    [youtube] no english transcript — skipping transcript path", flush=True)

        if raw:
            lines = [f"[{s.start:.1f}s] {s.text}" for s in raw]
            segments = find_moment_in_transcript(lines, query, target_dur)
            if segments:
                print(f"    [youtube] transcript found {len(segments)} segment(s):", flush=True)
                for s in segments:
                    print(f"      {s['start']}s→{s['end']}s conf:{s.get('confidence',0)}% — {s.get('reason','')[:50]}", flush=True)
            else:
                print(f"    [youtube] transcript gave no segments", flush=True)
    except Exception as te:
        print(f"    [youtube] transcript error: {te}", flush=True)

    # Stage 2b: visual guided sampling
    if not segments:
        print(f"    [youtube] no transcript match — running visual binary search...", flush=True)
        seg = _visual_moment_finder(vid_url, vid_dur, query, shot_desc, target_dur, instance_markers, vid_id, cache_dir)
        if seg:
            segments = [seg]
        else:
            print(f"    [youtube] visual search found nothing — skipping video", flush=True)
            return []

    # Expand/cap each segment, then visual-validate
    result = []
    for seg in segments[:2]:
        seg_dur = seg["end"] - seg["start"]
        # Never emit a segment shorter than the caller's target: run.py's duration
        # floor rejects at exactly target_dur, so padding to 0.8x here produced
        # candidates that were guaranteed to be dropped downstream.
        min_dur = max(target_dur, 2.0)
        max_dur = target_dur * 3.0
        if seg_dur < min_dur:
            mid = (seg["start"] + seg["end"]) / 2
            seg["start"] = max(0.0, mid - min_dur / 2)
            seg["end"]   = seg["start"] + min_dur
        elif seg_dur > max_dur:
            seg["end"] = seg["start"] + max_dur

        vis_conf, vis_verdict = 50, "unvalidated"
        vresult = _validate_segment(vid_url, seg, query, shot_desc, shot_audio, instance_markers, vid_id, cache_dir)
        if vresult:
            vis_conf    = vresult.get("confidence", 50)
            vis_verdict = "match" if vresult.get("matches") else "mismatch"
            print(f"    [youtube] visual validation: {vis_verdict} ({vis_conf}%) — {vresult.get('what_i_see','')[:80]}", flush=True)

        result.append({
            "source": "youtube", "type": "video",
            "url": vid_url,
            "thumb": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
            "title": f"{chosen.get('title','')[:50]} [{seg['start']:.0f}s→{seg['end']:.0f}s]",
            "id": f"{vid_id}_{seg['start']:.0f}",
            "width": 1280, "height": 720,
            "duration": seg["end"] - seg["start"],
            "ext": "mp4",
            "_yt_start": seg["start"],
            "_yt_end":   seg["end"],
            "confidence":        seg.get("confidence", 0),
            "visual_confidence": vis_conf,
            "visual_verdict":    vis_verdict,
        })
    return result


def _max_height(video_id: str) -> int:
    """Best available video height for a YouTube id via yt-dlp metadata (no download).

    Returns 0 when it can't be determined — the caller treats 0 as 'unknown,
    keep it' so a transient probe failure never drops a good candidate. The
    post-download ffprobe verify in run.py is the hard floor; this probe is just
    an optimisation to avoid spending transcript/visual work on videos that
    can't reach 720p.
    """
    if not video_id:
        return 0
    with _CACHE_LOCK:
        if video_id in _HEIGHT_CACHE:
            return _HEIGHT_CACHE[video_id]
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        heights = [int(f.get("height") or 0) for f in info.get("formats", [])]
        h = max(heights) if heights else 0
    except Exception:
        h = 0
    with _CACHE_LOCK:
        _HEIGHT_CACHE[video_id] = h
    return h


def _get_transcript(video_id: str) -> Any:
    """Fetch a YouTube transcript, cached per video id. Returns the raw transcript
    object, or None when no English transcript exists. Caches the None result too
    so a transcript-less video isn't re-fetched by later shots."""
    with _CACHE_LOCK:
        if video_id in _TRANSCRIPT_CACHE:
            return _TRANSCRIPT_CACHE[video_id]
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        raw = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US", "en-GB"])
    except Exception:
        raw = None
    with _CACHE_LOCK:
        _TRANSCRIPT_CACHE[video_id] = raw
    return raw


def _ensure_full_video(vid_url: str, vid_id: str, cache_dir: Path | None):
    """Ensure the full worst-quality video is on disk; return (path, tmpdir).

    With cache_dir: path is a persistent cache file (reused across shots and
    across separate `shot` invocations), tmpdir is None. On cache hit, no
    download happens. Without cache_dir: path lives in a fresh tempdir which the
    caller MUST remove (returned as tmpdir). Returns (None, None) on failure.
    """
    import yt_dlp

    tmpdir = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"{vid_id}.mp4"
        if cached.exists() and cached.stat().st_size > 1024:
            print(f"    [youtube] cache hit: {vid_id}.mp4 (no re-download)", flush=True)
            return cached, None
        target = cached
    else:
        import tempfile
        tmpdir = tempfile.mkdtemp()
        target = Path(tmpdir) / f"{vid_id or 'full'}.mp4"

    try:
        with yt_dlp.YoutubeDL({
            "quiet": True, "no_warnings": True,
            "format": "worst[ext=mp4]/worst",
            "outtmpl": str(target),
            "overwrites": True,
        }) as ydl:
            ydl.download([vid_url])
        if target.exists():
            return target, tmpdir
        matches = list(target.parent.glob(f"{target.stem}.*"))
        if matches:
            return matches[0], tmpdir
    except Exception as e:
        print(f"    [youtube] full download failed: {e}", flush=True)

    if tmpdir:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    return None, None


def search_youtube(
    query: str,
    shot_audio: str,
    shot_desc: str = "",
    target_dur: float = 5.0,
    instance_markers: dict | None = None,
    cache_dir: Path | None = None,
) -> list:
    """Search YouTube for this specific moment.

    Three-stage approach mirroring the reference notebook:
    1. LLM picks best 3 videos from 8 results (prefers short dedicated clips).
    2. LLM reads formatted transcript to find exact start/end timestamps.
       If no transcript (or transcript gives no match): visual guided sampling —
       download at worst quality, 3 rounds of 5-frame binary search with Claude Vision.
    3. LLM visual validation: download the found segment → extract 4 frames →
       Claude Vision confirms the specific action is visible (not just match context).

    All 3 videos are processed in parallel.
    """
    try:
        import yt_dlp
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from tools.assets.llm import pick_best_videos

        # E2: cache the ytsearch result by query — repeat queries (same fixture,
        # same event) skip the network round-trip and the flat extraction.
        with _CACHE_LOCK:
            cached_entries = _SEARCH_CACHE.get(query)
        if cached_entries is not None:
            print(f"    [youtube] search cache hit: {query!r}", flush=True)
            all_entries = cached_entries
        else:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
                info = ydl.extract_info(f"ytsearch8:{query}", download=False)
            all_entries = info.get("entries", [])
            with _CACHE_LOCK:
                _SEARCH_CACHE[query] = all_entries

        entries = [e for e in all_entries if (e.get("duration") or 0) <= 600]
        print(f"    [youtube] {len(all_entries)} results, {len(entries)} under 10 min", flush=True)
        if not entries:
            return []

        # Notebook parity: no height-floor pre-filter. YouTube gates 720p+ behind
        # PO tokens for anonymous clients, so probing-and-dropping by max height
        # would discard nearly every result. We pick by relevance (below) and the
        # download takes best-available — real HD where YouTube serves it, lower
        # where it doesn't, but always footage rather than a placeholder.

        # Stage 1: LLM picks best 3 videos
        picked = pick_best_videos(entries, query, n=3)
        top = [entries[i] for i in picked if i < len(entries)]
        print(f"    [youtube] picked {len(top)} videos (processing in parallel):", flush=True)
        for e in top:
            print(f"      - {e.get('title','')[:55]} | {e.get('duration',0)}s", flush=True)

        # Process all 3 videos in parallel
        candidates = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(_process_one_video, chosen, query, shot_audio, shot_desc, target_dur, instance_markers, cache_dir)
                for chosen in top
            ]
            for fut in as_completed(futures):
                try:
                    candidates.extend(fut.result())
                except Exception as e:
                    print(f"    [youtube] video processing error: {e}", flush=True)

        # Best-first: validated matches → unvalidated → mismatches
        def _rank(c: dict) -> tuple:
            verdict_score = {"match": 2, "unvalidated": 1, "mismatch": 0}[c.get("visual_verdict", "unvalidated")]
            return (verdict_score, c.get("visual_confidence", 50), c.get("confidence", 0))

        candidates.sort(key=_rank, reverse=True)
        return candidates

    except Exception:
        return []


def _visual_moment_finder(
    vid_url: str, vid_dur: float, query: str, shot_desc: str, target_dur: float,
    instance_markers: dict | None = None,
    vid_id: str = "", cache_dir: Path | None = None,
) -> dict | None:
    """Pull the worst-quality full video (from the E2 disk cache when available),
    then binary-search it with Claude Vision.

    3 rounds × 5 frames = 15 total frames, 3 Claude calls.
    Each round halves the search window around the best frame.
    Returns {start, end, confidence, reason} or None if nothing found.
    """
    import shutil
    import tempfile

    import cv2
    from tools.assets.llm import find_best_frame_at_timestamps

    video_path, dl_tmpdir = _ensure_full_video(vid_url, vid_id, cache_dir)
    if video_path is None:
        return None

    try:
        cap = cv2.VideoCapture(str(video_path))
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        actual_dur = total_frames / fps if fps > 0 else vid_dur

        window_start = 0.0
        window_end   = actual_dur
        best_ts      = actual_dur / 2
        best_conf    = 0

        with tempfile.TemporaryDirectory() as framedir:
            for round_n in range(3):
                n = 5
                step = (window_end - window_start) / (n - 1)
                timestamps = [window_start + i * step for i in range(n)]

                frame_paths = []
                for i, ts in enumerate(timestamps):
                    frame_num = min(int(ts * fps), int(total_frames) - 1)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    ret, frame = cap.read()
                    if ret:
                        fp = Path(framedir) / f"r{round_n}_f{i}.jpg"
                        cv2.imwrite(str(fp), frame)
                        frame_paths.append(str(fp))

                if not frame_paths:
                    break

                result = find_best_frame_at_timestamps(
                    frame_paths, timestamps[:len(frame_paths)], query, shot_desc, round_n + 1,
                    instance_markers=instance_markers,
                )
                if not result:
                    break

                best_idx  = min(result.get("best_index", 0), len(timestamps) - 1)
                best_conf = result.get("confidence", 0)
                best_ts   = timestamps[best_idx]

                print(
                    f"    [youtube] visual search round {round_n+1}: "
                    f"best at {best_ts:.1f}s (conf:{best_conf}%) — "
                    f"{result.get('reasoning','')[:60]}",
                    flush=True,
                )

                # Narrow: ±one step either side of best frame
                half = (window_end - window_start) / 4
                window_start = max(0.0, best_ts - half)
                window_end   = min(actual_dur, best_ts + half)

                if window_end - window_start < 1.5:
                    break

        cap.release()

        if best_conf < 20:
            print(f"    [youtube] visual search confidence too low ({best_conf}%) — skipping", flush=True)
            return None

        # Centre the window on the best frame, then shift it back inside the video
        # if either edge overhangs — clamping alone would return a short segment
        # that the duration floor rejects.
        start = best_ts - target_dur / 2
        end   = start + target_dur
        if start < 0.0:
            start, end = 0.0, min(actual_dur, target_dur)
        elif end > actual_dur:
            end   = actual_dur
            start = max(0.0, actual_dur - target_dur)
        return {
            "start": start,
            "end":   end,
            "confidence": best_conf,
            "reason": "visual guided sampling",
        }

    except Exception as e:
        print(f"    [youtube] visual moment finder error: {e}", flush=True)
        return None
    finally:
        if dl_tmpdir:
            shutil.rmtree(dl_tmpdir, ignore_errors=True)


def _validate_segment(
    vid_url: str, seg: dict, query: str, shot_desc: str, audio_txt: str,
    instance_markers: dict | None = None,
    vid_id: str = "", cache_dir: Path | None = None,
) -> dict | None:
    """Extract 4 frames spanning the segment from the worst-quality full video
    (reused from the E2 disk cache when available), then send to Claude Vision.

    Seeking the cached full file avoids the per-segment download the old path
    did — and when _visual_moment_finder or an earlier shot already cached this
    video, no download happens at all.
    """
    import shutil

    import cv2
    from tools.assets.llm import validate_frames

    video_path, dl_tmpdir = _ensure_full_video(vid_url, vid_id, cache_dir)
    if video_path is None:
        return None

    try:
        import base64

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        start_f = max(0, int(seg["start"] * fps))
        end_f   = min(int(total_frames) - 1, int(seg["end"] * fps)) if total_frames else int(seg["end"] * fps)
        span    = max(end_f - start_f, 1)

        frames_b64 = []
        for fi in range(4):
            pos = start_f + int(span * (fi + 0.5) / 4)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if ret:
                _, buf = cv2.imencode(".jpg", frame)
                frames_b64.append(base64.b64encode(buf.tobytes()).decode())
        cap.release()

        return validate_frames(frames_b64, query, shot_desc, audio_txt, instance_markers=instance_markers)
    except Exception:
        return None
    finally:
        if dl_tmpdir:
            shutil.rmtree(dl_tmpdir, ignore_errors=True)


# ── Stock-source validation (C1: Pexels / Pixabay) ───────────────────────────

def validate_stock_candidate(
    candidate: dict, query: str, shot_desc: str, audio_txt: str = "",
    instance_markers: dict | None = None,
) -> dict | None:
    """Visually validate one stock candidate against the shot's desc.

    Stock tagging is noisy enough that keyword/dimension scoring alone ships
    obviously-wrong clips (e.g. a generic stadium clip when the shot needed
    team-specific footage). This extends the same Claude Vision check the
    YouTube path already uses to Pexels/Pixabay candidates.

    - Image: validated directly by URL via validate_image_url.
    - Video: downloaded to a temp file, sampled for 4 frames via OpenCV, then
      validated via validate_frames. The winning clip is re-downloaded at fetch
      time (double-download accepted for now; E2's source-pool cache would fix).

    Returns the validator dict ({matches, confidence, ...}) or None on any
    failure, in which case the caller leaves the candidate unvalidated.
    """
    ctype = candidate.get("type", "")
    url = candidate.get("url", "")
    if not url:
        return None

    if ctype == "image":
        from tools.assets.llm import validate_image_url
        return validate_image_url(url, query, shot_desc, audio_txt, instance_markers=instance_markers)

    if ctype == "video":
        try:
            import base64
            import tempfile
            from pathlib import Path

            import cv2
            import requests
            from tools.assets.llm import validate_frames

            headers = {"User-Agent": "ESTA-Pipeline/1.0 (video validation; github.com/esta-v2)"}
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir) / "stock.mp4"
                r = requests.get(url, timeout=20, headers=headers, stream=True)
                if r.status_code != 200:
                    return None
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)

                cap = cv2.VideoCapture(str(tmp_path))
                total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                frames_b64 = []
                for fi in range(4):
                    pos = int(total_frames * (fi + 0.5) / 4)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                    ret, frame = cap.read()
                    if ret:
                        _, buf = cv2.imencode(".jpg", frame)
                        frames_b64.append(base64.b64encode(buf.tobytes()).decode())
                cap.release()

            if not frames_b64:
                return None
            return validate_frames(frames_b64, query, shot_desc, audio_txt, instance_markers=instance_markers)
        except Exception:
            return None

    return None
