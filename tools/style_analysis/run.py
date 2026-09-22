"""CLI entry point for the style-analysis skill — extraction phase only.

Called by SKILL.md via:
    conda run -n esta python tools/style_analysis/run.py analyze \
      --session sessions/<id> \
      [--youtube-urls "url1,url2"] \
      [--local-paths "path1,path2"] \
      [--search-query "funny football commentary"]

Phase 1 (this script): extracts frames (JPEG), CLIP classifications, and
Whisper transcripts. Writes sessions/<id>/style_extraction.json.
Phase 2 (Claude in-conversation): reads frames + transcripts, synthesises
style, writes style_analysis.json.

Prints a single JSON summary to stdout on completion.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load_config() -> dict:
    import yaml
    cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_analyze(args: argparse.Namespace) -> None:
    from tools.style_analysis.analyzer import VideoAnalyzer
    from tools.style_analysis.downloader import download_clips, search_youtube

    config = _load_config()
    hf_token = config.get("apis", {}).get("hf_token", "")

    session_dir = Path(args.session)
    clips_dir = session_dir / "style_examples"
    clips_dir.mkdir(parents=True, exist_ok=True)

    video_paths: list[Path] = []
    source = "user_provided"

    # 1. Local paths
    if args.local_paths:
        for raw in args.local_paths.split(","):
            p = Path(raw.strip())
            if p.exists():
                video_paths.append(p)
            else:
                print(f"[run] local path not found, skipping: {p}", file=sys.stderr, flush=True)

    # 2. YouTube URLs
    if args.youtube_urls:
        for url in args.youtube_urls.split(","):
            url = url.strip()
            if not url:
                continue
            print(f"[run] downloading YouTube clips: {url}", flush=True)
            slug = url.split("v=")[-1][:11] if "v=" in url else url[-11:]
            clips = download_clips(url, clips_dir, slug)
            video_paths.extend(clips)

    # 3. Auto-search
    if not video_paths and args.search_query:
        source = "auto_search"
        print(f"[run] auto-searching: '{args.search_query}'", flush=True)
        results = search_youtube(args.search_query, n=5)
        for entry in results[:3]:
            print(f"[run] downloading: {entry['title'][:60]}", flush=True)
            clips = download_clips(entry["url"], clips_dir, entry["id"])
            video_paths.extend(clips)

    if not video_paths:
        print(json.dumps({"ok": False, "error": "No video files to analyse."}), flush=True)
        sys.exit(1)

    analyzer = VideoAnalyzer(hf_token=hf_token)
    extractions = []

    for vp in video_paths[:5]:
        frames_dir = clips_dir / vp.stem
        frames_dir.mkdir(exist_ok=True)
        try:
            result = analyzer.extract(vp, frames_dir)
            extractions.append(result)
        except Exception as exc:
            print(f"[run] extraction failed for {vp.name}: {exc}", file=sys.stderr, flush=True)

    if not extractions:
        print(json.dumps({"ok": False, "error": "All extractions failed."}), flush=True)
        sys.exit(1)

    pacing = _aggregate_pacing(extractions)

    style_extraction = {
        "session_id": session_dir.name,
        "source": source,
        "videos_extracted": len(extractions),
        "pacing_patterns": pacing,
        "extractions": extractions,
        "timestamp": datetime.now().isoformat(),
    }

    output_path = session_dir / "style_extraction.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(style_extraction, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "ok": True,
        "output": str(output_path),
        "videos_extracted": len(extractions),
        "source": source,
        "pacing_patterns": pacing,
    }), flush=True)


def _aggregate_pacing(extractions: list[dict]) -> dict:
    timings = [e["timing"] for e in extractions]
    avg_cpm = sum(t["cuts_per_minute"] for t in timings) / len(timings)
    avg_shot = sum(t["avg_shot_duration"] for t in timings) / len(timings)
    return {
        "cuts_per_minute": round(avg_cpm, 2),
        "avg_shot_duration": round(avg_shot, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA style-analysis tool")
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("analyze", help="Extract style data from reference videos")
    p.add_argument("--session", required=True, help="Path to session dir")
    p.add_argument("--youtube-urls", default="", help="Comma-separated YouTube URLs")
    p.add_argument("--local-paths", default="", help="Comma-separated local video file paths")
    p.add_argument("--search-query", default="", help="Auto-search query if no URLs/paths given")

    args = parser.parse_args()

    try:
        if args.mode == "analyze":
            cmd_analyze(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
