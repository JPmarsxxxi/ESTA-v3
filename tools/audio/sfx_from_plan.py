"""Fulfil the plan's per-shot SFX suggestions into a real sfx.json.

The plan skill already makes the creative call — each shot may carry
`audio_layer.sfx: ["record scratch", ...]`, a named sound placed on a specific
beat (sound-design §J). Nothing consumed it: render reads sfx.json, and until
now that file was hand-authored. This is the missing bridge — it fetches each
named sound from Freesound, drops it at the shot's start, and writes the
sfx.json cue list that render + mix expect.

It does NOT set final levels: gains here are placeholders. Run
`tools/audio/mix.py --bake` afterwards to measure each file and level it a fixed
LU under the voice (the plan can't know how loud a given Freesound file is).

    conda run -n esta python tools/audio/sfx_from_plan.py --session sessions/<id>
    conda run -n esta python tools/audio/mix.py --session sessions/<id> --bake

Idempotent: a cue whose source file already exists is reused, not re-downloaded.
Re-running regenerates sfx.json from the plan — so hand edits to sfx.json are
overwritten. Tune levels via mix.py (--duck), or edit sfx.json AFTER this runs.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.audio.found_fetch import search_freesound, _download_direct, _load_keys

# A cue never outlives its beat: an SFX that rings for 4s is clutter, not
# punctuation (sound-design §J3). Cap the tail and prefer short source files.
MAX_CUE_SECONDS = 2.5
# Small lead so a shot-start sound hits WITH the cut, not a frame late. Only used
# when there's no trigger word to align to (word-aligned cues need no lead — the
# peak is placed exactly on the word).
LEAD_SECONDS = 0.05
PLACEHOLDER_GAIN = 0.3  # mix.py --bake computes the real level


def _envelope_peak(path: Path) -> float:
    """Seconds into the file where its energy peaks — the moment the ear reads as
    the sound's 'hit'. For a transient this is ~0 (attack at the front); for a
    riser/build it's near the end. Aligning THIS to a word is what makes the SFX
    land on the beat. Cheap: decode to mono 8k, smooth |amplitude|, argmax.
    ~0.04s/file, zero tokens."""
    try:
        import numpy as np
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000",
             "-f", "f32le", "-"], capture_output=True).stdout
        a = np.frombuffer(raw, dtype=np.float32)
        if a.size == 0:
            return 0.0
        env = np.abs(a)
        w = 160  # ~20ms smoothing window
        sm = np.convolve(env, np.ones(w) / w, "same")
        return float(np.argmax(sm)) / 8000
    except Exception:
        return 0.0


def _load_words(session: Path) -> list[dict]:
    """Flat word list with onsets, from timestamps.json."""
    p = session / "timestamps.json"
    if not p.exists():
        return []
    ts = json.loads(p.read_text(encoding="utf-8"))
    return [w for seg in ts.get("segments", []) for w in seg.get("words", [])]


def _norm(s: str) -> str:
    return "".join(c for c in str(s).lower() if c.isalnum())


def _word_onset(words: list[dict], target: str, lo: float, hi: float) -> float | None:
    """Onset of `target` within [lo, hi] (the shot's window). Scoping to the shot
    disambiguates a word — 'but' occurs many times, we want THIS shot's."""
    t = _norm(target)
    if not t:
        return None
    for w in words:
        s = float(w.get("start", 0))
        if lo - 0.25 <= s <= hi + 0.25 and _norm(w.get("word", "")) == t:
            return s
    # Looser: a word that merely contains the target (handles "3.71," etc.)
    for w in words:
        s = float(w.get("start", 0))
        if lo - 0.25 <= s <= hi + 0.25 and t in _norm(w.get("word", "")):
            return s
    return None


def _pick_sound(query: str, key: str, used_ids: set) -> dict | None:
    """Best short, unused Freesound hit for a named sound.

    Tries the exact name, then progressively simpler queries — plan names like
    'casino chip clink' are often too specific to match, but 'casino chip' or
    'chip' will. Asks the API for short sounds (max 6s) so we don't get 90s loops.
    """
    words = str(query).split()
    tries = [query]
    if len(words) >= 3:
        tries.append(" ".join(words[:2]))   # 'casino chip clink' -> 'casino chip'
    if len(words) >= 2:
        tries.append(words[0])              # -> 'casino'
    for q in tries:
        hits = [h for h in search_freesound(q, key, limit=10, max_duration=MAX_CUE_SECONDS + 3.5)
                if h["id"] not in used_ids]
        if hits:
            # search_freesound already returns short-only, relevance-ranked — so
            # the first hit is the best MATCH that's also brief. Don't re-sort by
            # duration or a loosely-relevant blip wins.
            return hits[0]
    return None


def build(session: Path) -> dict:
    plan_path = session / "plan.json"
    if not plan_path.exists():
        return {"ok": False, "error": f"{plan_path} not found"}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    key = _load_keys().get("freesound_key", "")
    if not key:
        return {"ok": False, "error": "no freesound_key in config.yaml"}

    out_dir = session / "assets" / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "_candidates.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    by_file = {m["file"]: m for m in manifest}

    words = _load_words(session)
    cues, missing, aligned = [], [], 0
    used_ids: set = set()
    for shot in plan.get("shots", []):
        al = shot.get("audio_layer") or {}
        names = al.get("sfx") or []
        if not names:
            continue
        start = float(shot.get("start", shot.get("start_est", 0)) or 0)
        end = float(shot.get("end", start))
        shot_len = end - start
        for entry in names:
            # An sfx entry is either a bare name ("record scratch") or an object
            # with a trigger word: {"sound": "record scratch", "on": "but"}. The
            # trigger is what buys word-level comedic timing.
            if isinstance(entry, dict):
                name, on_word = entry.get("sound", ""), entry.get("on")
            else:
                name, on_word = str(entry), None
            hit = _pick_sound(str(name), key, used_ids)
            if not hit:
                missing.append({"shot": shot.get("shot_number"), "sfx": name})
                continue
            used_ids.add(hit["id"])
            dest = out_dir / f"plan_{hit['id']}.mp3"
            f = str(dest).replace("\\", "/")
            if not (dest.exists() or _download_direct(hit["download_url"], dest)):
                missing.append({"shot": shot.get("shot_number"), "sfx": name, "err": "download failed"})
                continue
            by_file[f] = {"label": name, "query": str(name), "file": f,
                          "duration": hit["duration"], "title": hit["title"],
                          "attribution": hit["attribution"], "license": hit["license"],
                          "page": hit["page_url"]}
            out_pt = round(min(hit["duration"], MAX_CUE_SECONDS), 3)

            # Placement. If the plan named a trigger word and we can find it in
            # this shot's window, land the sound's PEAK on that word's onset:
            #   at = word_onset - peak_offset
            # so a transient hits on the word and a riser climaxes on it. No
            # trigger (or word not found) → shot-start with a small lead, as before.
            target = _word_onset(words, on_word, start, end) if on_word else None
            if target is not None:
                peak = min(_envelope_peak(dest), out_pt)
                at = round(max(target - peak, 0.0), 3)
                aligned += 1
                label = f"{name} — shot {shot.get('shot_number')} on '{on_word}'"
            else:
                at = round(max(start - LEAD_SECONDS, 0.0), 3)
                label = f"{name} — shot {shot.get('shot_number')}"
            cues.append({
                "at": at,
                "file": f,
                "gain": PLACEHOLDER_GAIN,
                "label": label,
                "in": 0.0,
                "out": out_pt,
                "fade_out": round(min(0.08, out_pt * 0.3), 3),  # smooth the cut tail
                "_source": f,
                "_credit": f"{hit['title']} by {hit['attribution']} ({hit['license']})",
            })

    manifest_path.write_text(json.dumps(list(by_file.values()), indent=2), encoding="utf-8")
    cues.sort(key=lambda c: c["at"])
    (session / "sfx.json").write_text(
        json.dumps({"cues": cues,
                    "note": "Generated from plan.audio_layer.sfx. Gains are placeholders — "
                            "run tools/audio/mix.py --bake to set levels. Ambience lane.",
                    "from_plan": True},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "cues": len(cues), "word_aligned": aligned, "missing": missing,
            "placed": [c["label"] for c in cues]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build sfx.json from the plan's per-shot SFX")
    ap.add_argument("--session", required=True)
    args = ap.parse_args()
    print(json.dumps(build(Path(args.session)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
