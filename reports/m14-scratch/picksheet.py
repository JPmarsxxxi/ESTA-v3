"""Contact sheet of a session's non-MG picks, one frame per shot at its in-point (+0.4 s): picksheet.py <session-id> <out.jpg> [cols]"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("C:/Users/User/ESTA-v3")
S = ROOT / "sessions" / sys.argv[1]
out, cols = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5
rows = {}
for line in (S / "assets_progress.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        x = json.loads(line)
        rows[x["shot_number"]] = x
tmp = Path(out).with_suffix("")
tmp.mkdir(exist_ok=True)
frames = []
for n in sorted((k for k in rows if isinstance(k, int)), key=int):
    x = rows[n]
    if not x.get("ok") or x.get("source") == "hyperframes" or not x.get("file"):
        continue
    png = tmp / f"s{n}.png"
    vf = f"scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2,drawtext=text='{n} {x.get('source')}':x=6:y=6:fontsize=22:fontcolor=white:box=1:boxcolor=black"
    seek = ["-ss", f"{float(x.get('in_point') or 0) + 0.4:.2f}"] if x.get("asset_type") == "video" else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", *seek, "-i", str(ROOT / x["file"]), "-frames:v", "1", "-vf", vf, str(png)])
    if png.exists():
        frames.append(png)
args = []
for p in frames:
    args += ["-i", str(p)]
lay = "|".join(f"{(i % cols) * 480}_{(i // cols) * 270}" for i in range(len(frames)))
subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", "".join(f"[{i}:v]" for i in range(len(frames))) +
                f"xstack=inputs={len(frames)}:layout={lay}:fill=black", "-frames:v", "1", out])
print(len(frames), "->", out)
