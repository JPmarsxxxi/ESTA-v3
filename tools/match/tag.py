"""Shot tagging through the Kaggle VLM lane, with the bake-off's prompt.

    python tools/match/tag.py validate     # re-tag the answer key; score kind in 4 and 3 classes

`tag_frames` is what inspo.py and score.py call: one keyframe per shot in,
parsed labels out, cached by the frames' content so a shot is tagged once.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match import vlm_kaggle  # noqa: E402
from tools.match.common import KIND_GROUPS, REPO_ROOT, match_config, read_json, write_json  # noqa: E402

JOBS_DIR = REPO_ROOT / "cache" / "vlm_jobs"
TAG_CACHE = REPO_ROOT / "cache" / "tags.json"
KEY_DIR = REPO_ROOT / "tools" / "match" / "bakeoff" / "key"

# Verbatim from the M5.1 bake-off (tools/match/bakeoff/kaggle.py), so the
# validated accuracy carries over.
PROMPT = (
    "Look at this single video shot's keyframe. Reply with ONLY a JSON object, no "
    "other text:\n"
    '{"kind": one of ["footage","still","graphic","ai","talking_head","screen","meme"], '
    '"text_on_screen": true/false (any on-screen text/captions visible), '
    '"panels": 1, 2, or 3 (3 means 3 or more split-screen panels), '
    '"overlay": true/false (a graphic/text overlay floating over footage), '
    '"clips_in_shot": integer, normally 1}\n'
    'kind meanings: footage=real camera footage, still=static image/screenshot with no '
    'motion, graphic=motion graphic or animated content, ai=visibly AI-generated, '
    'talking_head=person speaking to camera, screen=screen recording/game UI, meme=meme '
    'template or reaction clip.'
)


# Not part of the bake-off: the validated `overlay` tag counts speech captions,
# which every ESTA render has as subtitles, so complexity compares this instead.
OVERLAY_PROMPT = (
    "Look at this video frame. Ignore subtitles or captions that transcribe speech. Is there any "
    "OTHER graphic, sticker, label, number card or text overlay floating over the picture? "
    'Reply with ONLY a JSON object: {"overlay_extra": true/false}'
)


def parse_labels(text: str) -> dict | None:
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return {
            "kind": str(obj.get("kind", "")).strip().lower(),
            "text_on_screen": bool(obj.get("text_on_screen", False)),
            "panels": int(obj.get("panels", 1)),
            "overlay": bool(obj.get("overlay", False)),
            "clips_in_shot": int(obj.get("clips_in_shot", 1)),
        }
    except Exception:
        return None


def _digest(p: Path) -> str:
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:16]


def tag_frames(frames: dict[str, Path], job_name: str, log=print) -> dict[str, dict]:
    """{shot_id: keyframe path} -> {shot_id: labels}. Blocks while Kaggle runs."""
    cache = read_json(TAG_CACHE, {}) or {}
    digests = {sid: _digest(p) for sid, p in frames.items()}
    reqs, copied = [], set()
    for sid, p in frames.items():
        d = digests[sid]
        have = cache.get(d) or {}
        for rid, prompt, done in ((d, PROMPT, "kind" in have), (f"{d}-ov", OVERLAY_PROMPT, "overlay_extra" in have)):
            if done:
                continue
            reqs.append({"id": rid, "images": [f"{d}.jpg"], "prompt": prompt, "max_new_tokens": 150})
            copied.add((sid, d))
    if reqs:
        # A job folder is one fixed request set; a different set needs its own.
        job = JOBS_DIR / f"{job_name}-{hashlib.sha1(''.join(sorted(r['id'] for r in reqs)).encode()).hexdigest()[:6]}"
        if job.exists() and not (job / "kernel.json").exists():
            shutil.rmtree(job)
        (job / "images").mkdir(parents=True, exist_ok=True)
        for sid, d in copied:
            shutil.copy(frames[sid], job / "images" / f"{d}.jpg")
        write_json(job / "requests.json", {"model": match_config()["models"]["tags"], "requests": reqs})
        log(f"[tag] {len(reqs)} requests to Kaggle ({job_name})")
        vlm_kaggle.run(job, log=log)
        raw = read_json(job / "results.json", {}) or {}
        cache = read_json(TAG_CACHE, {}) or {}
        for rid, text in raw.items():
            if rid.endswith("-ov"):
                try:
                    val = bool(json.loads(text[text.index("{"): text.rindex("}") + 1]).get("overlay_extra"))
                except Exception:
                    continue
                cache.setdefault(rid[:-3], {})["overlay_extra"] = val
            elif (labels := parse_labels(text)):
                cache[rid] = {**cache.get(rid, {}), **labels}
        write_json(TAG_CACHE, cache)
    return {sid: cache[d] for sid, d in digests.items() if "kind" in cache.get(d, {})}


def validate() -> dict:
    frames, truth = {}, {}
    for vdir in sorted(KEY_DIR.iterdir()):
        if not vdir.is_dir() or vdir.name == "negative_style":
            continue
        for s in read_json(vdir / "shots.json", []):
            p = vdir / "shot_frames" / f"shot_{int(s['shot_id']):03d}.jpg"
            if p.exists():
                sid = f"{vdir.name}|{s['shot_id']}"
                frames[sid], truth[sid] = p, s
    preds = tag_frames(frames, "validate-key", log=lambda m: print(m, flush=True))
    out = {"n": len(preds)}
    for classes in (4, 3):
        g = KIND_GROUPS[classes]
        pairs = [(g.get(preds[k]["kind"], "footage"), g[truth[k]["kind"]]) for k in preds]
        labels = sorted({t for _, t in pairs})
        f1s = {}
        for c in labels:
            tp = sum(1 for p, t in pairs if p == c and t == c)
            fp = sum(1 for p, t in pairs if p == c and t != c)
            fn = sum(1 for p, t in pairs if p != c and t == c)
            pr = tp / (tp + fp) if tp + fp else 0.0
            rc = tp / (tp + fn) if tp + fn else 0.0
            f1s[c] = round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0
        out[f"kind_{classes}"] = {"macro_f1": round(sum(f1s.values()) / len(f1s), 3), "per_class": f1s,
                                  "accuracy": round(sum(1 for p, t in pairs if p == t) / len(pairs), 3)}
    for field in ("text_on_screen", "overlay", "panels", "clips_in_shot"):
        out[field] = round(sum(1 for k in preds if preds[k][field] == truth[k][field]) / len(preds), 3)
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["validate"]:
        print(json.dumps(validate(), indent=2))
    else:
        print(__doc__)
