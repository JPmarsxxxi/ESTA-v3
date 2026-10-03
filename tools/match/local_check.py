"""Local timing check for the M5.1 bake-off's cuts/theme winners (tags always run
on Kaggle per the spec, so only cuts and theme ever need a local number).

Times the actual algorithm on the user's own GPU (or CPU fallback) against a real
video, and appends the result straight into bakeoff/results.md — this is what
satisfies M5.1's "the winner must also run in the esta env on the user's 4GB GPU
or CPU" acceptance criterion.

Run in the esta conda env:
  conda run -n esta python tools/match/local_check.py --job cuts --model pyscenedetect --video <path>
  conda run -n esta python tools/match/local_check.py --job theme --model siglip2 --video <path>
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.bakeoff import report  # noqa: E402


def _device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _video_duration_min(video: Path) -> float:
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return (frames / fps) / 60 if fps else 0.0


def _time_transnetv2(video: Path) -> None:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out_csv = str(Path(tmp) / "out.csv")
        r = subprocess.run(["transnetv2_pytorch", str(video), "--output", out_csv, "--quiet"],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError("transnetv2_pytorch failed: " + (r.stderr or r.stdout)[-300:])


CUTS_MODELS = {
    "pyscenedetect": lambda video: __import__("scenedetect").detect(
        str(video), __import__("scenedetect").AdaptiveDetector()),
    "transnetv2": _time_transnetv2,
}


def _time_cuts(model: str, video: Path) -> float:
    if model not in CUTS_MODELS:
        raise ValueError(f"local timing not implemented for cuts model {model!r} "
                         f"(only algorithms with a clean local package are supported here — "
                         f"see results.md for why AutoShot was Kaggle-only)")
    t0 = time.time()
    CUTS_MODELS[model](video)
    return time.time() - t0


def _time_theme(model: str, video: Path) -> float:
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frames / fps if fps else 0
    sample_times = [duration * k / 10 for k in range(1, 10)]  # 9 sample frames is enough for a timing estimate
    images = []
    for t in sample_times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(t * fps))
        ok, frame = cap.read()
        if ok:
            from PIL import Image
            images.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    cap.release()
    if not images:
        raise RuntimeError(f"could not sample frames from {video}")

    import torch
    device = _device()
    t0 = time.time()
    if model == "siglip2":
        from transformers import AutoModel, AutoProcessor
        model_id = "google/siglip2-base-patch16-224"
        processor = AutoProcessor.from_pretrained(model_id)
        net = AutoModel.from_pretrained(model_id).to(device).eval()
        inputs = processor(images=images, return_tensors="pt").to(device)
        with torch.no_grad():
            net.get_image_features(**inputs)
    elif model == "clip-vit-b32":
        from transformers import CLIPModel, CLIPProcessor
        model_id = "openai/clip-vit-base-patch32"
        processor = CLIPProcessor.from_pretrained(model_id)
        net = CLIPModel.from_pretrained(model_id).to(device).eval()
        inputs = processor(images=images, return_tensors="pt").to(device)
        with torch.no_grad():
            net.get_image_features(**inputs)
    elif model == "dinov3-small":
        from transformers import AutoImageProcessor, AutoModel
        model_id = "facebook/dinov3-convnext-small-pretrain-lvd1689m"
        processor = AutoImageProcessor.from_pretrained(model_id)
        net = AutoModel.from_pretrained(model_id).to(device).eval()
        for img in images:
            inputs = processor(images=img, return_tensors="pt").to(device)
            with torch.no_grad():
                net(**inputs)
    else:
        raise ValueError(f"unknown theme model {model!r}")
    elapsed = time.time() - t0
    # Scale the 9-sample timing to a per-minute-of-video rate.
    return elapsed / (len(images) / max(duration / 60, 1e-6))


def main() -> None:
    parser = argparse.ArgumentParser(description="Local timing check for M5.1 bake-off winners")
    parser.add_argument("--job", required=True, choices=["cuts", "theme"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--video", required=True)
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(json.dumps({"ok": False, "error": f"video not found: {video}"}))
        sys.exit(1)

    device = _device()
    try:
        if args.job == "cuts":
            elapsed = _time_cuts(args.model, video)
            dur_min = _video_duration_min(video)
            sec_per_min = elapsed / dur_min if dur_min else 0.0
        else:
            sec_per_min = _time_theme(args.model, video)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)

    report.append_local_timing(args.job, args.model, sec_per_min, device)
    print(json.dumps({"ok": True, "job": args.job, "model": args.model,
                      "sec_per_min": sec_per_min, "device": device}, ensure_ascii=False))


if __name__ == "__main__":
    main()
