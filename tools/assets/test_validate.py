"""Test full visual validation chain via claude CLI."""
import sys, subprocess, tempfile, base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import cv2
from tools.assets.llm import validate_frames

vid_url = "https://www.youtube.com/watch?v=c_JlCriK3fY"

with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir) / "validate.mp4"
    subprocess.run([
        "yt-dlp", "--quiet", "--no-warnings", "-f", "worst[ext=mp4]/worst",
        "--download-sections", "*0.0-5.0", "--force-keyframes-at-cuts",
        "-o", str(tmp_path), vid_url,
    ], capture_output=True, timeout=60)
    actual = tmp_path if tmp_path.exists() else next(iter(Path(tmpdir).glob("*.mp4")), None)

    cap = cv2.VideoCapture(str(actual))
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    frames_b64 = []
    for fi in range(4):
        pos = int(total * (fi + 0.5) / 4)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        if ret:
            _, buf = cv2.imencode(".jpg", frame)
            frames_b64.append(base64.b64encode(buf.tobytes()).decode())
    cap.release()
    print(f"extracted {len(frames_b64)} frames")

result = validate_frames(
    frames_b64,
    query="Cristiano Ronaldo bicycle kick goal Juventus",
    shot_desc="Ronaldo's iconic overhead kick for Real Madrid vs Juventus",
    audio_txt="one of the greatest goals ever scored",
)
print("result:", result)
