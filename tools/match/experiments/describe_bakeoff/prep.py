"""Bake-off prep: inspo shots (TransNetV2) + our first-minute shots -> 384px keyframes, a shared prompt, a Gemma job."""
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from tools.match.common import detect_cuts, frames_at, media_frames, save_jpg  # noqa: E402

OUT = Path(__file__).parent
INSPO = Path(__file__).parent / "inspo" / "videoplayback-2.mp4"
SESSION = REPO / "sessions" / "do-alphas-even-exist-2026-09-29"
SIDE = 384

SOURCES = {
    "pexels_video": "free stock video clip (clean, generic, well lit)",
    "pixabay_video": "free stock video clip (often lower budget than Pexels)",
    "youtube": "a clip lifted from another YouTube video, podcast, news or film",
    "archive": "Archive.org: old, historical, public-domain or vintage footage",
    "pexels_image": "free stock photo",
    "pixabay_image": "free stock photo or illustration",
    "pinterest": "aesthetic or moody image, meme-ish picture, artwork, screenshot",
    "wikimedia": "documentary photo of a real person, place or historical item",
    "google_images": "a specific real-world image: logo, headline, screenshot, product, chart",
    "giphy": "GIF, reaction clip or meme loop",
    "hyperframes": "motion graphic made in-house: animated text, numbers, charts, UI cards",
    "ai_video": "AI-generated video (smooth surreal motion, synthetic look)",
}

PROMPT = (
    "This is one keyframe of one shot from a YouTube video. Reply with ONLY a JSON object:\n"
    '{"description": "one or two plain sentences: what is on screen, the setting, the camera feel, and any '
    'text or graphics overlaid (ignore subtitles that transcribe speech)", '
    '"likely_sources": ["1 to 3 sources from the list below, most likely first, judged by the look and feel"], '
    # The two complexity fields keep tag.py's wording so section d measures the same thing.
    '"text_on_screen": true/false (any on-screen text/captions visible), '
    '"overlay_extra": true/false (ignoring subtitles or captions that transcribe speech, is there any OTHER graphic, '
    'sticker, label, number card or text overlay floating over the picture)}\n'
    "Sources:\n" + "\n".join(f"- {k}: {v}" for k, v in SOURCES.items())
)


def main() -> None:
    if (OUT / "shots.json").exists():
        # Frames are already cut; only rewrite the prompt and the Gemma job.
        write_prompt_and_job(json.loads((OUT / "shots.json").read_text(encoding="utf-8")), OUT / sys.argv[1])
        return
    shots = []
    bounds = detect_cuts(INSPO)
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        fr = frames_at(INSPO, [(a + b) / 2])
        if not fr:
            continue
        sid = f"i{i + 1:03d}"
        save_jpg(fr[0], OUT / "frames" / f"{sid}.jpg", SIDE)
        shots.append({"id": sid, "side": "inspo", "start": a, "end": b, "dur": round(b - a, 3)})

    plan = json.loads((SESSION / "plan.json").read_text(encoding="utf-8"))["shots"]
    assets = json.loads((SESSION / "assets.json").read_text(encoding="utf-8"))["shots"]
    for s in plan:
        if float(s["start"]) >= 60:
            continue
        a = assets.get(str(s["shot_number"])) or {}
        f = REPO / a.get("file", "") if a.get("file") else None
        if not (f and f.exists()):
            continue
        fr = media_frames(f, a.get("in_point") or 0, a.get("out_point") or 0, n=1)
        if not fr:
            continue
        sid = f"o{s['shot_number']:03d}"
        save_jpg(fr[0], OUT / "frames" / f"{sid}.jpg", SIDE)
        shots.append({"id": sid, "side": "ours", "start": s["start"], "end": s["end"],
                      "dur": round(s["end"] - s["start"], 3), "true_source": a.get("source"),
                      "plan_desc": s["visual"].get("desc", "")})

    (OUT / "shots.json").write_text(json.dumps(shots, indent=1), encoding="utf-8")
    write_prompt_and_job(shots, OUT / "gemma_job")


def write_prompt_and_job(shots: list[dict], job: Path) -> None:
    (OUT / "prompt.txt").write_text(PROMPT, encoding="utf-8")
    (job / "images").mkdir(parents=True, exist_ok=True)
    for s in shots:
        shutil.copy(OUT / "frames" / f"{s['id']}.jpg", job / "images" / f"{s['id']}.jpg")
    reqs = [{"id": s["id"], "images": [f"{s['id']}.jpg"], "prompt": PROMPT, "max_new_tokens": 240} for s in shots]
    (job / "requests.json").write_text(json.dumps({"model": "gemma4-e4b", "requests": reqs}), encoding="utf-8")
    print(f"inspo shots {sum(s['side'] == 'inspo' for s in shots)}, ours {sum(s['side'] == 'ours' for s in shots)}")


if __name__ == "__main__":
    main()
