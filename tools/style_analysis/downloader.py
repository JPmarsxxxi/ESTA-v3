"""YouTube search and video clip downloading for style-analysis.

Downloads two clips per video: 60s from the start and 60s from the middle.
Low quality (worst available) to keep file sizes small.
"""

from pathlib import Path


def search_youtube(query: str, n: int = 5) -> list[dict]:
    """Search YouTube and return basic metadata for top n results (no download)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)

    entries = info.get("entries", [])
    return [
        {
            "id": e.get("id", ""),
            "title": e.get("title", "")[:80],
            "url": f"https://www.youtube.com/watch?v={e.get('id', '')}",
            "duration": e.get("duration", 0),
            "channel": e.get("channel", ""),
            "view_count": e.get("view_count", 0) or 0,
        }
        for e in entries
        if e.get("id")
    ]


def download_clips(url: str, output_dir: Path, slug: str) -> list[Path]:
    """Download start and middle 60s clips from a YouTube video at lowest quality.

    Returns list of paths to downloaded clip files (may be fewer than 2 if
    the video is short or download fails).
    """
    import yt_dlp

    output_dir.mkdir(parents=True, exist_ok=True)

    # Get video duration first
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        meta = ydl.extract_info(url, download=False)

    duration = meta.get("duration", 0) or 0
    middle = max(60, duration // 2)

    clips = []
    for clip_name, start in [("start", 0), ("middle", middle)]:
        out_path = output_dir / f"{slug}_{clip_name}.mp4"
        opts = {
            "format": "worst[ext=mp4]/worst",
            "outtmpl": str(out_path),
            "quiet": True,
            "no_warnings": True,
            "postprocessor_args": ["-ss", str(start), "-t", "60"],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if out_path.exists():
                clips.append(out_path)
        except Exception as exc:
            print(f"[downloader] clip {clip_name} failed: {exc}")

    return clips
