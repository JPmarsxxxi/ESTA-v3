"""The describe lane: Claude Haiku says what each inspo shot looks like (SPEC.md Part 3, M6.1).

    python tools/match/describe.py inspo --session sessions/<id>

`describe_shots` is what inspo.py calls: keyframes plus the words spoken over each shot in, one parsed
answer per shot out. Ten keyframes go in one `claude -p` call (inline images, one model turn), four calls
run at once, and answers are cached by keyframe content and prompt version, so an inspo is described once.
"""

import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import (  # noqa: E402
    LEAN_CLAUDE, REPO_ROOT, claude_bin, match_config, read_json, utf8_stdout, write_json,
)

CACHE = REPO_ROOT / "cache" / "describe.json"
PROMPT_VERSION = 1
KINDS = {"footage", "still", "graphic"}
CONTENTS = {"single_focus", "multi_subject", "background", "text_card", "ui_chart"}
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
STILL_SOURCES = {"pexels_image", "pixabay_image", "pinterest", "wikimedia", "google_images"}

SYSTEM = "You describe video keyframes for an editor. Reply with only the requested JSON."
PROMPT = (
    "Each image above is one keyframe of one shot from a YouTube video, labelled with its shot id and the words "
    "spoken over it. For every shot answer:\n"
    '{"description": "one or two plain sentences: what is on screen, the setting, the camera feel, and any text '
    'or graphics overlaid (ignore subtitles that transcribe speech)", '
    '"kind": "footage" (real moving camera footage, including talking heads and reaction clips) | "still" (a static '
    'photo, screenshot or artwork) | "graphic" (motion graphic, text card, chart, UI built by the editor), '
    '"content": "single_focus" (one subject the frame is built around) | "multi_subject" (a group of people or '
    'objects) | "background" (landscape, crowd, general b-roll with no focus) | "text_card" (the frame is mostly '
    'text) | "ui_chart" (a chart, terminal, dashboard or app UI), '
    '"sourcing_hint": "a 3 to 6 word search phrase that would find an equivalent shot", '
    '"likely_sources": ["1 to 3 sources from the list below, most likely first"], '
    '"text_extra": true/false (any text on screen OTHER than subtitles that transcribe the speech), '
    '"overlay_extra": true/false (any graphic, sticker, label, number card or text floating over the picture, '
    "again ignoring speech subtitles)}\n"
    "The spoken words are the voiceover the editor was illustrating: use them to judge what the shot is meant to "
    "show. Stock sites hold generic clean clips; youtube is for specific real people, events, shows and "
    "recognisable footage.\nSources:\n" + "\n".join(f"- {k}: {v}" for k, v in SOURCES.items())
)


def _key(image: Path) -> str:
    return f"{hashlib.sha1(Path(image).read_bytes()).hexdigest()[:16]}|v{PROMPT_VERSION}"


def _jpeg_b64(image: Path, max_side: int) -> str:
    from PIL import Image
    im = Image.open(image).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def normalise(ans: dict) -> dict:
    """Fill or repair fields so downstream code can index them without guards."""
    sources = [str(s) for s in ans.get("likely_sources") or [] if str(s) in SOURCES][:3]
    kind = str(ans.get("kind", "")).lower()
    if kind not in KINDS:
        lead = sources[0] if sources else ""
        kind = "graphic" if lead == "hyperframes" else "still" if lead in STILL_SOURCES else "footage"
    content = str(ans.get("content", "")).lower()
    return {
        "description": str(ans.get("description", "")).strip(),
        "kind": kind,
        "content": content if content in CONTENTS else "background",
        "sourcing_hint": str(ans.get("sourcing_hint", "")).strip(),
        "likely_sources": sources,
        "text_extra": bool(ans.get("text_extra")),
        "overlay_extra": bool(ans.get("overlay_extra")),
    }


def _call(argv: list[str], message: str) -> str:
    """One `claude -p` turn; returns stdout. Tests replace this."""
    r = subprocess.run(argv, input=message + "\n", capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=REPO_ROOT, timeout=900)
    return r.stdout or r.stderr


def ask(content: list[dict], system: str, model: str) -> dict:
    """One `claude -p` turn over inline text and images, answer parsed as a JSON object; retried once.
    Returns {"answer", "cost", "secs", "attempts"} or {"error", "secs"}. The auto-pick judge uses it too."""
    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    argv = [claude_bin(), "-p", "--model", model, "--input-format", "stream-json", "--output-format",
            "stream-json", "--verbose", "--system-prompt", system, *LEAN_CLAUDE]
    t0 = time.time()
    err = ""
    for attempt in (1, 2):
        out = _call(argv, msg)
        try:
            env = next(e for e in (json.loads(line) for line in out.splitlines() if line.startswith("{"))
                       if e.get("type") == "result")
            text = env.get("result", "")
            return {"answer": json.loads(text[text.index("{"): text.rindex("}") + 1]),
                    "cost": float(env.get("total_cost_usd") or 0), "secs": time.time() - t0, "attempts": attempt}
        except Exception as e:  # noqa: BLE001 - one retry, then the caller keeps its fallback
            err = f"{e}: {out[-300:]}"
    return {"error": err, "secs": time.time() - t0}


def image_block(image: Path, max_side: int) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(image, max_side)}}


def run_batch(batch: list[dict], cfg: dict) -> dict:
    content = []
    for it in batch:
        said = it.get("words", "")
        content.append({"type": "text", "text": f"Shot {it['id']}" + (f' (spoken over it: "{said}")' if said else "") + ":"})
        content.append(image_block(it["image"], cfg["max_side"]))
    content.append({"type": "text", "text": PROMPT + f"\n\nThere are {len(batch)} shots. Reply with ONLY one JSON "
                    'object mapping each shot id to its answer, e.g. {"' + batch[0]["id"] + '": {"description": ...}}.'})
    res = ask(content, SYSTEM, cfg["model"])
    if "error" in res:
        return {"answers": {}, "error": res["error"], "ids": [it["id"] for it in batch], "secs": res["secs"]}
    return {"answers": {k: normalise(v) for k, v in res["answer"].items() if isinstance(v, dict)},
            "cost": res["cost"], "secs": res["secs"], "attempts": res["attempts"]}


def describe_shots(items: list[dict], log=print) -> dict:
    """items: [{"id", "image": Path, "words": str}] -> {"answers": {id: answer}, "cost_usd", "wall_secs", "errors"}."""
    cfg = match_config()["describe"]
    cache = read_json(CACHE, {}) or {}
    keys = {it["id"]: _key(it["image"]) for it in items}
    todo = [it for it in items if keys[it["id"]] not in cache]
    t0, cost, errors = time.time(), 0.0, []
    if todo:
        batches = [todo[i:i + cfg["batch"]] for i in range(0, len(todo), cfg["batch"])]
        log(f"[describe] {len(todo)} shots in {len(batches)} calls ({cfg['model']})")
        with ThreadPoolExecutor(cfg["workers"]) as pool:
            results = list(pool.map(lambda b: run_batch(b, cfg), batches))
        cache = read_json(CACHE, {}) or {}
        for b, res in zip(batches, results):
            cost += res.get("cost", 0.0)
            if "error" in res:
                errors.append(res["error"][:300])
            for it in b:
                if it["id"] in res["answers"]:
                    cache[keys[it["id"]]] = res["answers"][it["id"]]
        write_json(CACHE, cache)
    return {"answers": {i: cache[k] for i, k in keys.items() if k in cache}, "cost_usd": round(cost, 4),
            "wall_secs": round(time.time() - t0, 1), "errors": errors}


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Describe a session's inspo shots with Haiku")
    ap.add_argument("mode", choices=["inspo"])
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    from tools.match.inspo import describe_profile
    idx = read_json(Path(a.session) / "inspo_profiles.json", {}) or {}
    if not idx.get("profiles"):
        print(json.dumps({"ok": False, "error": "no inspo profile; run inspo.py profile first"}))
        sys.exit(1)
    out = [describe_profile(REPO_ROOT / rel, log=lambda m: print(m, flush=True)) for rel in idx["profiles"]]
    print(json.dumps({"ok": all(o["status"] == "done" for o in out), "profiles": out}))


if __name__ == "__main__":
    main()
