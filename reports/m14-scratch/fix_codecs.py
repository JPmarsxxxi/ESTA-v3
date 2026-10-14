"""Give every picked non-H.264 clip an H.264 cut of just its used window, and point the feed at it.

Headless Chrome stalled exporting the label timeline at its AV1 clips. Unpicked candidates touched by the earlier
whole-pool pass get their .orig restored.   python fix_codecs.py <session-id> ...
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("C:/Users/User/ESTA-v3")


def codec(f: Path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(f)],
                          capture_output=True, text=True).stdout.strip()


for sid in [a for a in sys.argv[1:] if not a.startswith("--")]:
    S = ROOT / "sessions" / sid
    pool = S / "assets" / "source_pool"
    rows = {}
    for line in (S / "assets_progress.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            x = json.loads(line)
            rows[x["shot_number"]] = x
    out = []
    for n, x in rows.items():
        if not x.get("ok") or x.get("asset_type") != "video" or x.get("source") == "hyperframes" or not x.get("file"):
            continue
        f = ROOT / x["file"]
        c = codec(f)
        if c == "h264" and ("--all" not in sys.argv or "_h264_" in f.name):
            continue
        a = max(0.0, float(x.get("in_point") or 0) - 0.5)
        b = float(x.get("out_point") or a + 3) + 0.5
        dst = f.with_name(f"{f.stem}_h264_{n}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(f), "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)], check=True)
        y = dict(x, file=str(dst.relative_to(ROOT)).replace("\\", "/"), in_point=round(float(x.get("in_point") or 0) - a, 3),
                 out_point=round(float(x.get("out_point") or 0) - a, 3))
        out.append(y)
        print(sid, n, c, "->", dst.name)
    with open(S / "assets_progress.jsonl", "a", encoding="utf-8") as fh:
        for y in out:
            fh.write(json.dumps(y) + "\n")
    print(sid, "fixed", len(out))
