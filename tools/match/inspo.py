"""Inspo profile: the whole inspo videos measured shot by shot, cached per video.

    python tools/match/inspo.py resolve --session sessions/<id>   # write inspo.json
    python tools/match/inspo.py profile --session sessions/<id>   # build/reuse profiles, describe with Haiku

cache/inspo/<hash>/: video.mp4, profile.json (shots with timing, colour, words, tags, motion),
words.json (the inspo transcript),
embeddings.npz (per-shot DINOv3 and SigLIP 2), keyframes/.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import (  # noqa: E402
    CACHE_DIR, REPO_ROOT, Embedder, colour_features, detect_cuts, frames_at, probe, read_json,
    run_esta, save_jpg, utf8_stdout, write_json,
)

MAX_SECONDS = 600
NEGATIVE_FRAMES = REPO_ROOT / "tools" / "match" / "bakeoff" / "key" / "negative_style" / "frames"
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def resolve(session: Path) -> list[dict]:
    """inspo.json, derived from style-analysis output for sessions that predate it."""
    existing = read_json(session / "inspo.json")
    if existing:
        return existing
    ext = read_json(session / "style_extraction.json", {}) or {}
    source = "auto_search" if ext.get("source") == "auto_search" else "user_provided"
    out = []
    for e in ext.get("extractions", []):
        f = str(e.get("video_file") or "")
        stem = Path(f.replace("\\", "/")).stem
        yt = stem[:-6] if stem.endswith("_start") and YT_ID.match(stem[:-6]) else ""
        if yt:
            out.append({"kind": "youtube", "ref": yt, "source": source})
        elif f:
            p = Path(f) if Path(f).is_absolute() else REPO_ROOT / f
            out.append({"kind": "local", "ref": str(p), "source": source})
    if not out:
        for p in sorted((session / "style_examples").glob("*_start.mp4")):
            out.append({"kind": "youtube", "ref": p.stem[:-6], "source": source})
    write_json(session / "inspo.json", out)
    return out


def _hash(src: dict) -> str:
    return hashlib.sha1(f"{src['kind']}:{src['ref']}".encode()).hexdigest()[:12]


def _fetch_video(src: dict, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1024:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src["kind"] == "local":
        p = Path(src["ref"])
        if not p.exists():
            raise FileNotFoundError(f"local inspo moved or missing: {p}")
        shutil.copy(p, dest)
        return
    url = f"https://www.youtube.com/watch?v={src['ref']}"
    r = run_esta(["-m", "yt_dlp", "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b",
                  "--merge-output-format", "mp4", "-o", str(dest), "--no-playlist", url], timeout=1800)
    if r.returncode != 0 or not dest.exists():
        raise RuntimeError(f"download failed for {url}: {(r.stderr or r.stdout)[-300:]}")


def _windows(duration: float) -> list[tuple[float, float]]:
    """Whole video up to 10 minutes; longer ones as evenly spaced chunks totalling 10."""
    if duration <= MAX_SECONDS:
        return [(0.0, duration)]
    n = 10
    chunk = MAX_SECONDS / n
    step = duration / n
    return [(i * step, i * step + chunk) for i in range(n)]


def _calibration(emb: Embedder, dino_shots, sig_shots, texts: list[str]) -> dict:
    """Map raw similarity to 0-100: inspo-to-itself is 100, a different style is 0."""
    import numpy as np
    neg = sorted(NEGATIVE_FRAMES.glob("*.jpg")) if NEGATIVE_FRAMES.exists() else []
    out = {"dino": {"lo": 0.2, "hi": 0.8}, "siglip_text": {"lo": 0.0, "hi": 0.12}}
    if len(dino_shots) > 2:
        sims = dino_shots @ dino_shots.T
        np.fill_diagonal(sims, -1)
        hi = float(np.median(sims.max(axis=1)))
        lo = hi - 0.4
        if neg:
            from tools.match.common import image_rgb
            nd = emb.dino([image_rgb(p) for p in neg])
            lo = float(np.median((nd @ dino_shots.T).max(axis=1)))
        out["dino"] = {"lo": min(lo, hi - 0.05), "hi": hi}
    if texts and len(sig_shots):
        tv = emb.siglip_texts(texts)
        hi = float(np.median((tv @ sig_shots.T).max(axis=1)))
        lo = hi - 0.1
        if neg:
            from tools.match.common import image_rgb
            ns = emb.siglip_images([image_rgb(p) for p in neg])
            lo = float(np.median((tv @ ns.T).max(axis=1)))
        out["siglip_text"] = {"lo": min(lo, hi - 0.02), "hi": hi}
    return out


def build_profile(src: dict, emb: Embedder, style_texts: list[str], log=print) -> Path:
    import numpy as np
    d = CACHE_DIR / _hash(src)
    prof_path = d / "profile.json"
    prof = read_json(prof_path)
    if prof and (d / "embeddings.npz").exists():
        return d
    video = d / "video.mp4"
    _fetch_video(src, video)
    duration, _ = probe(video)
    log(f"[inspo] {src['ref']}: {duration:.0f}s, detecting cuts")
    bounds = detect_cuts(video)
    wins = _windows(duration)
    shots = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        mid = (a + b) / 2
        if any(lo <= mid < hi for lo, hi in wins):
            shots.append({"id": f"{_hash(src)}-{i + 1:04d}", "start": round(a, 3), "end": round(b, 3),
                          "dur": round(b - a, 3)})
    log(f"[inspo] {len(shots)} shots; colour + embeddings")
    dino_rows, sig_rows = [], []
    for s in shots:
        span = s["end"] - s["start"]
        frames = frames_at(video, [s["start"] + span * f for f in (0.2, 0.5, 0.8)])
        if not frames:
            frames = frames_at(video, [s["start"]])
        s["colour"] = colour_features(frames)
        kf = save_jpg(frames[len(frames) // 2], d / "keyframes" / f"{s['id']}.jpg")
        s["keyframe"] = str(kf.relative_to(d)).replace("\\", "/")
        dino_rows.append(emb.dino(frames).mean(axis=0))
        sig_rows.append(emb.siglip_images([frames[len(frames) // 2]])[0])
    dino = np.stack(dino_rows) if dino_rows else np.zeros((0, 1), "float32")
    sig = np.stack(sig_rows) if sig_rows else np.zeros((0, 1), "float32")
    dino /= np.linalg.norm(dino, axis=1, keepdims=True) + 1e-9
    np.savez_compressed(d / "embeddings.npz", dino=dino, siglip=sig, ids=np.array([s["id"] for s in shots]))
    prof = {"source": src, "hash": _hash(src), "duration": duration, "windows": wins, "shots": shots,
            "calibration": _calibration(emb, dino, sig, style_texts), "tags_status": "pending", "complete": False}
    write_json(prof_path, prof)
    return d


def describe_profile(d: Path, log=print) -> dict:
    """Haiku describes every shot from its keyframe and the words spoken over it (SPEC.md Part 3, M6.1)."""
    from tools.match.describe import describe_shots
    from tools.match.speech import profile_words, words_in
    prof = read_json(d / "profile.json")
    if prof.get("tags_status") == "done" and all("content" in s.get("tags", {}) for s in prof["shots"]):
        return {"profile": d.name, "status": "done", **prof.get("describe", {}), "error": ""}
    try:
        words = profile_words(d, log)
    except Exception as e:  # noqa: BLE001 - no whisper: describe from the images alone
        log(f"[inspo] transcription skipped: {str(e)[:160]}")
        words = []
    for s in prof["shots"]:
        s["words"] = words_in(words, s["start"], s["end"])
    try:
        res = describe_shots([{"id": s["id"], "image": d / s["keyframe"], "words": s["words"]} for s in prof["shots"]], log)
        for s in prof["shots"]:
            a = res["answers"].get(s["id"])
            if a:
                # text_on_screen/overlay mirror the subtitle-blind answers so M5 readers keep working.
                s["tags"] = {**a, "text_on_screen": a["text_extra"], "overlay": a["overlay_extra"],
                             "panels": 1, "clips_in_shot": 1}
        prof["tags_status"] = "done" if all("tags" in s for s in prof["shots"]) else "partial"
        prof["tags_error"] = "; ".join(res["errors"])[:300]
        prof["describe"] = {"cost_usd": res["cost_usd"], "wall_secs": res["wall_secs"],
                            "described": sum("tags" in s for s in prof["shots"])}
    except Exception as e:  # noqa: BLE001 - claude missing or failing: profile stays usable without tags
        prof["tags_status"] = "pending"
        prof["tags_error"] = str(e)[:300]
    prof["complete"] = prof["tags_status"] == "done"
    write_json(d / "profile.json", prof)
    return {"profile": d.name, "status": prof["tags_status"], **prof.get("describe", {}), "error": prof["tags_error"]}


def profile(session: Path, log=print) -> dict:
    sources = resolve(session)
    style = read_json(session / "style_analysis.json", {}) or {}
    texts = [t for t in [style.get("shot_patterns", ""), style.get("visual_style", ""),
                         style.get("dominant_content_type", ""), " ".join(style.get("keywords") or [])] if t]
    emb = Embedder()
    done, failed = [], []
    for src in sources:
        try:
            d = build_profile(src, emb, texts, log)
            describe_profile(d, log)
            from tools.match.motion import motion_profile
            motion_profile(d, log)
            done.append(str(d.relative_to(REPO_ROOT)).replace("\\", "/"))
        except Exception as e:  # noqa: BLE001 - one bad inspo must not sink the rest
            failed.append({"ref": src["ref"], "error": str(e)[:300]})
            log(f"[inspo] {src['ref']}: FAILED {e}")
    out = {"session": session.name, "profiles": done, "failed": failed}
    write_json(session / "inspo_profiles.json", out)
    return out


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Inspo profiles for the M5 match")
    ap.add_argument("mode", choices=["resolve", "profile"])
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    session = Path(a.session)
    try:
        out = resolve(session) if a.mode == "resolve" else profile(session, log=lambda m: print(m, flush=True))
        print(json.dumps({"ok": True, "result": out}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
