"""YouTube HD upgrade via Colab — offload path for the assets skill.

Why this exists: locally, YouTube forces SABR streaming, so anonymous yt-dlp
caps at 360p (see memory/project_youtube_sabr.md for the full investigation).
Google's Colab runtimes are NOT SABR-gated, so the notebook's plain
`bestvideo+bestaudio` download returns real HD there. This module lets the
assets skill route YouTube shots through a connected Colab session (driven by
colab-proxy-mcp) and pull the HD files back in place.

Flow (orchestrated by the assets SKILL.md, because run.py can't call the MCP):

  1. `plan`  — read assets.json, collect unique YouTube video-ids already
               fetched (at local 360p), and emit the Python source for a Colab
               cell that re-downloads them in HD and uploads each to an
               host (filebin.net), printing a JSON {video_id: {url,height}}.
  2. Claude  — opens the Colab connection, runs that cell via the MCP, captures
               the printed JSON, writes it to a results file.
  3. `apply` — download each hosted HD file OVER the existing
               source_pool/yt_<id>.mp4 (same path run.py used), so assets.json /
               render / the editor need no changes. Re-probe and report.

If Colab is unreachable the local 360p files simply stay — render is never
blocked. This is a pure, reversible upgrade-in-place.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Resolution at/above which we consider a YouTube shot already "good enough" and
# skip the Colab upgrade. Mirrors the assets skill's 720p intent.
HD_FLOOR = 720
# Transfer host = filebin.net. It's the one host that survives BOTH legs of this
# offload, tested live: it accepts large (200MB+) anonymous uploads from Colab's
# datacenter IP AND serves a direct (redirect-to-signed-S3) download to the
# user's machine. Rejected alternatives: catbox.moe blocks datacenter IPs
# ("Invalid uploader") + 200MB cap; 0x0.st/transfer.sh/tmpfiles unreachable
# locally; pixeldrain needs an API key; gofile now requires premium for API
# direct links. A filebin bin auto-expires (~6 days) — fine for a one-time pull.
FILEBIN = "https://filebin.net"


# ── video-id parsing ──────────────────────────────────────────────────────────

def video_id_from_url(url: str) -> str:
    """Best-effort YouTube video id from a watch/short/embed URL.

    Mirrors the key used by run.py `_source_path` (`yt_<id>`) so the HD file
    lands on exactly the path the 360p one occupies.
    """
    if not url:
        return ""
    # youtu.be/<id>
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    # watch?v=<id>  (this is the form run.py's _source_path parses)
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    # /embed/<id> or /shorts/<id>
    m = re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{6,})", url)
    if m:
        return m.group(1)
    # run.py fallback: last path/qs segment after v=
    return url.split("v=")[-1].split("&")[0] or ""


def _probe_height(path: Path) -> int:
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout.strip().splitlines()
        if out and out[0].isdigit():
            return int(out[0])
    except Exception:
        pass
    return 0


# ── target collection ─────────────────────────────────────────────────────────

def collect_targets(session_dir: Path) -> list[dict]:
    """Unique YouTube sources in assets.json that are below the HD floor.

    Deduped by video_id (several shots may share one upload). Each target:
      {video_id, url, dest, local_height, shots: [n, ...]}
    """
    assets_path = session_dir / "assets.json"
    if not assets_path.exists():
        return []
    data = json.loads(assets_path.read_text(encoding="utf-8"))
    assets_dir = session_dir / "assets"

    by_id: dict[str, dict] = {}
    for n, shot in (data.get("shots") or {}).items():
        if not shot.get("ok") or shot.get("source") != "youtube":
            continue
        url = shot.get("url", "")
        vid = video_id_from_url(url)
        if not vid:
            continue
        dest = assets_dir / "source_pool" / f"yt_{vid}.mp4"
        local_h = _probe_height(dest) if dest.exists() else 0
        if vid in by_id:
            by_id[vid]["shots"].append(int(n))
            continue
        by_id[vid] = {
            "video_id": vid,
            "url": url,
            "dest": str(dest),
            "local_height": local_h,
            "shots": [int(n)],
        }

    # Only those that need upgrading (below HD floor or file missing).
    return [t for t in by_id.values() if t["local_height"] < HD_FLOOR]


# ── Colab cell source ─────────────────────────────────────────────────────────

def build_colab_cell(targets: list[dict]) -> str:
    """Return Python source to run in the connected Colab notebook.

    The cell: ensures a current yt-dlp, downloads each id in HD with the
    notebook-parity format, uploads to filebin.net, and prints a single JSON line:
        ESTA_YT_RESULT::{"results": {vid: {"url":..., "height":...}}, "errors": {...}}
    The sentinel prefix lets the skill find the payload amid pip/yt-dlp noise.
    """
    ids_urls = [{"video_id": t["video_id"], "url": t["url"]} for t in targets]
    payload = json.dumps(ids_urls)
    fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    return f'''# ESTA — YouTube HD download on Colab (not SABR-gated here), upload for retrieval.
import subprocess, sys, json, os, secrets
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp"], check=False)
import yt_dlp

TARGETS = json.loads({payload!r})
FMT = {fmt!r}
FILEBIN = {FILEBIN!r}
results, errors = {{}}, {{}}

def _height(path):
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
            "-show_entries","stream=height","-of","csv=p=0",path],
            capture_output=True, text=True, timeout=15)
        line = (r.stdout or "").strip().splitlines()
        return int(line[0]) if line and line[0].isdigit() else 0
    except Exception:
        return 0

def _upload(path, vid):
    # filebin.net: PUT bytes to /{{bin}}/{{name}}; the same URL is the direct link
    # (302 -> signed S3). A fresh random bin per file keeps them isolated.
    name = "yt_" + vid + ".mp4"
    bin_id = "esta" + secrets.token_hex(8)
    url = FILEBIN + "/" + bin_id + "/" + name
    out = subprocess.run(
        ["curl","-s","-o","/dev/null","-w","%{{http_code}}",
         "-H","Content-Type: application/octet-stream","--data-binary","@"+path, url],
        capture_output=True, text=True, timeout=1200)
    code = (out.stdout or "").strip()
    if code not in ("200", "201"):
        raise RuntimeError("filebin upload HTTP " + code + " " + (out.stderr or "")[:150])
    return url

for t in TARGETS:
    vid, url = t["video_id"], t["url"]
    dest = "/tmp/yt_" + vid + ".mp4"
    try:
        opts = {{"quiet": True, "no_warnings": True, "format": FMT,
                 "merge_output_format": "mp4", "outtmpl": dest, "overwrites": True}}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        if not os.path.exists(dest):
            raise RuntimeError("no file produced")
        h = _height(dest)
        hosted = _upload(dest, vid)
        results[vid] = {{"url": hosted, "height": h}}
        print("OK", vid, str(h) + "p", hosted, flush=True)
    except Exception as e:
        errors[vid] = str(e)[:200]
        print("ERR", vid, str(e)[:200], flush=True)

print("ESTA_YT_RESULT::" + json.dumps({{"results": results, "errors": errors}}))
'''


# ── apply HD results in place ─────────────────────────────────────────────────

def _download(url: str, dest: Path, timeout: int = 600) -> bool:
    import requests
    # filebin serves the real file to programmatic (curl/wget) User-Agents but an
    # HTML preview page to browser/custom UAs — so we MUST present as curl here.
    headers = {"User-Agent": "curl/8.5.0", "Accept": "*/*"}
    try:
        resp = requests.get(url, stream=True, timeout=timeout, headers=headers)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as exc:
        print(f"[yt-colab] download failed ({url[:60]}): {exc}", file=sys.stderr, flush=True)
        return False


def apply_results(session_dir: Path, results: dict) -> dict:
    """Pull each hosted HD file over its source_pool/yt_<id>.mp4 path.

    `results` is the {video_id: {"url", "height"}} map the Colab cell printed.
    Returns a summary; updates assets.json shot entries with `hd_height` and the
    real (width,height) is left to render's ffprobe — the file path is unchanged.
    """
    assets_dir = session_dir / "assets"
    upgraded, failed = [], []
    for vid, info in (results or {}).items():
        hosted = info.get("url", "")
        dest = assets_dir / "source_pool" / f"yt_{vid}.mp4"
        if not hosted:
            failed.append(vid)
            continue
        if _download(hosted, dest):
            h = _probe_height(dest)
            upgraded.append({"video_id": vid, "height": h, "file": str(dest)})
            print(f"[yt-colab] {vid}: HD in place → {dest.name} ({h}p)", flush=True)
        else:
            failed.append(vid)

    # Annotate assets.json shots with the upgraded height (file path unchanged).
    assets_path = session_dir / "assets.json"
    if assets_path.exists() and upgraded:
        data = json.loads(assets_path.read_text(encoding="utf-8"))
        height_by_id = {u["video_id"]: u["height"] for u in upgraded}
        for shot in (data.get("shots") or {}).values():
            if shot.get("source") == "youtube":
                vid = video_id_from_url(shot.get("url", ""))
                if vid in height_by_id:
                    shot["hd_height"] = height_by_id[vid]
                    shot["hd_source"] = "colab"
        assets_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"upgraded": upgraded, "failed": failed}


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_plan(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    targets = collect_targets(session_dir)
    out = {
        "ok": True,
        "session_id": session_dir.name,
        "targets": targets,
        "count": len(targets),
        "cell": build_colab_cell(targets) if targets else "",
    }
    print(json.dumps(out, ensure_ascii=False))


def cmd_apply(args: argparse.Namespace) -> None:
    session_dir = Path(args.session)
    results_path = Path(args.results)
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    # Accept either the full {"results":...} payload or a bare {vid:{...}} map.
    results = raw.get("results", raw) if isinstance(raw, dict) else {}
    summary = apply_results(session_dir, results)
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA YouTube HD upgrade via Colab")
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("plan", help="List YouTube targets + emit the Colab download cell")
    p.add_argument("--session", required=True)

    a = sub.add_parser("apply", help="Pull hosted HD files over source_pool in place")
    a.add_argument("--session", required=True)
    a.add_argument("--results", required=True, help="Path to the JSON the Colab cell printed")

    args = parser.parse_args()
    try:
        if args.mode == "plan":
            cmd_plan(args)
        elif args.mode == "apply":
            cmd_apply(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
