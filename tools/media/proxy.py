"""Generate lightweight proxies for oversized source media.

A source larger than the project frame is pure decode cost in the editor: three
4K clips playing at once is what makes the OpenCut timeline stutter, even though
nothing on screen needs more than the project resolution. This downscales any
such file to the frame, into `assets/proxies/<same-name>`, leaving the original
untouched.

Proxies preserve duration and everything else exactly, so every clip's in/out
point stays valid — this is a decode-cost fix, not a re-cut. The bridge
(`from_openreel.py`) auto-prefers a proxy when one exists, so generating them is
all that's needed; nothing downstream has to be repointed by hand.

Project dimensions are read from the session's rendered `*.openreel.json`
(falling back to 1080x1920 vertical), so this adapts to landscape/square too.

    conda run -n esta python tools/media/proxy.py generate --session sessions/<id>
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_W, DEFAULT_H = 1080, 1920


def _probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.split()
    try:
        return int(out[0]), int(out[1])
    except Exception:
        return 0, 0


def _project_dims(session: Path) -> tuple[int, int]:
    """Frame size from the rendered project, so proxies match the real output."""
    for p in session.glob("*.openreel.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            proj = doc.get("project", doc)
            s = proj.get("timeline", {}).get("settings") or proj.get("settings") or {}
            w = int(s.get("width") or 0)
            h = int(s.get("height") or 0)
            if w and h:
                return w, h
        except Exception:
            pass
    return DEFAULT_W, DEFAULT_H


def _media_files(session: Path) -> list[Path]:
    """Every source file the timeline actually references (from assets.json)."""
    aj = session / "assets.json"
    files: list[Path] = []
    if aj.exists():
        data = json.loads(aj.read_text(encoding="utf-8"))
        for v in data.get("shots", {}).values():
            f = str(v.get("file", "")).replace("\\", "/")
            if f:
                p = Path(f)
                if not p.is_absolute() and not p.exists():
                    p = session.parent.parent / f  # repo-relative stored path
                if p.exists():
                    files.append(p)
    return files


def generate(session: Path, force: bool = False) -> dict:
    w, h = _project_dims(session)
    proxy_dir = session / "assets" / "proxies"
    proxy_dir.mkdir(parents=True, exist_ok=True)

    made, skipped, done = [], 0, []
    for f in _media_files(session):
        if f.suffix.lower() not in {".mp4", ".mov", ".webm", ".avi", ".mkv"}:
            continue
        sw, sh = _probe_dims(f)
        if sw <= w and sh <= h:
            continue  # already within the frame — no proxy needed
        dst = proxy_dir / f.name
        if dst.exists() and not force and dst.stat().st_mtime >= f.stat().st_mtime:
            skipped += 1
            continue
        t0 = time.time()
        # scale down to fit the frame, keep aspect, even dims (yuv420p needs it);
        # -an drops audio (render mutes video tracks anyway); short GOP for scrub.
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(f),
               "-vf", f"scale='min({w},iw)':'min({h},ih)':"
                      "force_original_aspect_ratio=decrease:force_divisible_by=2",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-g", "30", "-an",
               "-movflags", "+faststart", str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            made.append({"file": f.name, "ok": False, "error": r.stderr[-300:]})
            continue
        before = f.stat().st_size
        after = dst.stat().st_size
        made.append({"file": f.name, "ok": True,
                     "from": f"{sw}x{sh}", "to": "x".join(map(str, _probe_dims(dst))),
                     "mb_before": round(before / 1e6, 1), "mb_after": round(after / 1e6, 1),
                     "seconds": round(time.time() - t0, 1)})
        done.append(f.name)

    return {"ok": True, "frame": f"{w}x{h}", "generated": len([m for m in made if m.get('ok')]),
            "skipped": skipped, "details": made}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate editor proxies for oversized media")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="Downscale oversized sources to the project frame")
    g.add_argument("--session", required=True)
    g.add_argument("--force", action="store_true", help="rebuild proxies even if current")
    args = ap.parse_args()

    if args.cmd == "generate":
        res = generate(Path(args.session), force=args.force)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
