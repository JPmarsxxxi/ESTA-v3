import sys, glob, os
os.environ["HF_HUB_OFFLINE"] = "1"
from faster_whisper import WhisperModel
m = WhisperModel("medium", device="cpu", compute_type="int8")
for f in sys.argv[2:]:
    p = f"{sys.argv[1]}/voice_build/lines/line_{f}.wav"
    segs, _ = m.transcribe(p, language="en")
    print(f, "|", " ".join(s.text.strip() for s in segs))
