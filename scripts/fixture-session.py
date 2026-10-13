"""Build a small, self-contained test session from a real one, for cloud sessions
that can't reach the real media (it lives on the user's D: drive).

Keeps the first --seconds of the source session's render output, plan and
subtitles, and writes an ffmpeg test pattern in place of every media file the
kept clips reference, so the editor can build and play the project.

  python scripts/fixture-session.py --from do-alphas-even-exist-2026-09-29 --id fixture-m14-2026-10-13
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--seconds", type=float, default=15)
    a = ap.parse_args()
    src, dst = ROOT / "sessions" / a.src, ROOT / "sessions" / a.id
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    end = a.seconds

    for name in ["requirements.json", "pipeline.json", "style_analysis.json", "script.md", "timestamps.json"]:
        if (src / name).exists():
            shutil.copy(src / name, dst / name)

    plan = json.loads((src / "plan.json").read_text())
    plan["shots"] = [s for s in plan["shots"] if s.get("start_time", s.get("start", 0)) < end]
    (dst / "plan.json").write_text(json.dumps(plan, indent=2))
    kept_shots = {s["shot_number"] for s in plan["shots"]}

    doc = json.loads((src / f"{a.src}.openreel.json").read_text())
    p = doc["project"]
    p["id"] = f"esta-{a.id}"
    p["name"] = f"Fixture: {p['name']}"
    used = set()
    for t in p["timeline"]["tracks"]:
        t["clips"] = [c for c in t["clips"] if c["startTime"] < end]
        for c in t["clips"]:
            if c["id"] == "clip-voiceover":
                c["duration"] = c["outPoint"] = end
            used.add(c["mediaId"])
    p["timeline"]["subtitles"] = [s for s in p["timeline"]["subtitles"] if s["startTime"] < end]
    p["timeline"]["duration"] = end
    items = [m for m in p["mediaLibrary"]["items"] if m["id"] in used]
    p["mediaLibrary"]["items"] = items

    prefix = f"/api/sessions/{a.src}/"
    for m in items:
        for k in ("thumbnailUrl", "originalUrl"):
            if isinstance(m.get(k), str):
                m[k] = m[k].replace(prefix, f"/api/sessions/{a.id}/")
        rel = (m.get("originalUrl") or "").split(f"/api/sessions/{a.id}/", 1)[-1]
        if not rel:
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        w, h = m["metadata"].get("width") or 1280, m["metadata"].get("height") or 720
        w, h = min(w, 1280) // 2 * 2, min(h, 720) // 2 * 2
        if m["type"] == "audio":
            ffmpeg("-f", "lavfi", "-i", f"sine=frequency=220:duration={end}", "-ac", "2", "-ar", "48000", str(out))
        elif m["type"] == "image":
            ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}", "-frames:v", "1", str(out))
        else:
            dur = max(1.0, min(m["metadata"].get("duration") or 4, 8))
            ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={dur}", "-pix_fmt", "yuv420p", str(out))
        m["metadata"]["fileSize"] = out.stat().st_size
    (dst / f"{a.id}.openreel.json").write_text(json.dumps(doc))

    for name in ["assets.json"]:
        if (src / name).exists():
            assets = json.loads((src / name).read_text())
            if isinstance(assets.get("shots"), dict):
                assets["shots"] = {k: v for k, v in assets["shots"].items() if k.split("-")[0].isdigit() and int(k.split("-")[0]) in kept_shots}
            (dst / name).write_text(json.dumps(assets, indent=2))
    print(f"sessions/{a.id}: {len(kept_shots)} plan shots, {len(items)} media, {end}s")


if __name__ == "__main__":
    main()
