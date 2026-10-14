"""Contact sheet of each rendered MG slot at ~80% of its duration: python mgsheet.py <session-id> <out.jpg> [cols]"""
import subprocess
import sys
from pathlib import Path

S = Path("C:/Users/User/ESTA-v3/sessions") / sys.argv[1]
out, cols = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6
files = sorted((S / "assets" / "source_pool").glob("mg_*.mp4"), key=lambda p: int(p.stem.split("_")[1].split("-")[0]))
tmp = Path(out).with_suffix("")
tmp.mkdir(exist_ok=True)
frames = []
for f in files:
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                             capture_output=True, text=True).stdout or 1)
    png = tmp / f"{f.stem}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, (d - 1.0) * 0.85):.2f}", "-i", str(f), "-frames:v", "1",
                    "-vf", "scale=-2:360,drawtext=text='" + f.stem + "':x=8:y=8:fontsize=26:fontcolor=white:box=1:boxcolor=black", str(png)])
    frames.append(png)
args = []
for p in frames:
    args += ["-i", str(p)]
n = len(frames)
w = int(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width", "-of", "csv=p=0", str(frames[0])], capture_output=True, text=True).stdout)
lay = "|".join(f"{(i % cols) * w}_{(i // cols) * 360}" for i in range(n))
subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", "".join(f"[{i}:v]" for i in range(n)) + f"xstack=inputs={n}:layout={lay}:fill=black",
                "-frames:v", "1", out])
print(n, "frames ->", out)
