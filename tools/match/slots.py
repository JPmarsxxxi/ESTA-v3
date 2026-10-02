"""The proposed cut: our voiceover cut into slots, each the counterpart of one inspo shot (SPEC.md Part 3, M6.2).

    python tools/match/slots.py --session sessions/<id>      # -> slots.json

Our time t maps to inspo time t / voice_end * inspo_total (normalised position); the inspo shot covering it is
the slot's ref and gives its target length in real seconds. Each cut goes to the word boundary nearest
start + target. Slots tile 0 -> voice_end with no gaps. The plan skill writes one shot per slot and
validate_plan.py checks the result.
"""

import argparse
import json
import subprocess
import sys
from bisect import bisect_right
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import REPO_ROOT, read_json, utf8_stdout, write_json  # noqa: E402

ALT_WINDOW = 3
MIN_INSPO_SHOT = 0.1   # under ~2 frames: a flash, merged into its neighbour
LAST_MERGE = 0.4       # a last slot under this share of its target joins the previous one


def load_words(ts: dict) -> list[dict]:
    words = [w for s in ts.get("segments", []) for w in s.get("words", [])] or ts.get("words", [])
    out, last = [], 0.0
    for w in words:
        # Whisper can emit overlapping words; clamp so boundaries never go backwards.
        a = max(float(w.get("start", 0)), last)
        b = max(float(w.get("end", a)), a)
        out.append({"word": str(w.get("word", "")).strip(), "start": a, "end": b})
        last = b
    return out


def boundaries(words: list[dict]) -> list[float]:
    """Cut points between consecutive words: the middle of the gap, or the shared instant."""
    return [round((a["end"] + b["start"]) / 2, 3) for a, b in zip(words, words[1:])]


def voice_end(session: Path, words: list[dict]) -> float:
    audio = session / "audio.wav"
    if audio.exists():
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(audio)], capture_output=True, text=True, timeout=60)
            return round(float(r.stdout.strip()), 3)
        except Exception:  # noqa: BLE001 - no ffprobe: fall back to the metadata
            pass
    meta = read_json(session / "audio_metadata.json", {}) or {}
    if meta.get("duration_seconds"):
        return round(float(meta["duration_seconds"]), 3)
    return round(words[-1]["end"], 3) if words else 0.0


def inspo_shots(session: Path) -> list[dict]:
    """Every inspo shot in inspo.json order, flashes merged into the shot before."""
    idx = read_json(session / "inspo_profiles.json", {}) or {}
    shots: list[dict] = []
    for rel in idx.get("profiles", []):
        for s in (read_json(REPO_ROOT / rel / "profile.json", {}) or {}).get("shots", []):
            row = {"id": s["id"], "dur": float(s["dur"]), "tags": s.get("tags") or {}, "motion": s.get("motion") or {},
                   "keyframe": str(Path(rel) / s["keyframe"]).replace("\\", "/") if s.get("keyframe") else ""}
            if row["dur"] < MIN_INSPO_SHOT and shots:
                shots[-1]["dur"] += row["dur"]
            else:
                shots.append(row)
    return shots


def propose(words: list[dict], end: float, inspo: list[dict]) -> list[dict]:
    if not inspo or end <= 0:
        return []
    starts, acc = [], 0.0
    for s in inspo:
        starts.append(acc)
        acc += s["dur"]
    total = acc
    cuts = boundaries(words)
    slots, t = [], 0.0
    while t < end - 1e-3:
        k = min(bisect_right(starts, t / end * total) - 1, len(inspo) - 1)
        target = inspo[k]["dur"]
        later = [c for c in cuts if c > t + 0.05]
        cut = min(later, key=lambda c: abs(c - (t + target))) if later else end
        if cut >= end - 1e-3 or not later:
            cut = end
        slots.append({"start": round(t, 3), "end": round(cut, 3), "target_dur": round(target, 3), "k": k})
        t = cut
    while len(slots) > 1 and slots[-1]["end"] - slots[-1]["start"] < LAST_MERGE * slots[-1]["target_dur"]:
        last = slots.pop()
        slots[-1]["end"] = last["end"]
    out = []
    for i, s in enumerate(slots, 1):
        k = s["k"]
        alts = [inspo[j]["id"] for j in range(max(0, k - ALT_WINDOW), min(len(inspo), k + ALT_WINDOW + 1)) if j != k]
        said = " ".join(w["word"] for w in words if s["start"] <= (w["start"] + w["end"]) / 2 < s["end"])
        out.append({"slot": i, "start": s["start"], "end": s["end"], "dur": round(s["end"] - s["start"], 3),
                    "target_dur": s["target_dur"], "ref_shot": inspo[k]["id"], "ref_pos": round(starts[k] / total, 4),
                    "alts": alts, "words": said})
    return out


def build(session: Path) -> dict:
    words = load_words(read_json(session / "timestamps.json", {}) or {})
    end = voice_end(session, words)
    inspo = inspo_shots(session)
    if not words:
        raise RuntimeError("no timestamps.json words: slots need real word timing")
    if not inspo:
        raise RuntimeError("no inspo profile: run `python tools/match/inspo.py profile --session ...` first")
    slots = propose(words, end, inspo)
    used = {s["ref_shot"] for s in slots} | {a for s in slots for a in s["alts"]}
    refs = {s["id"]: {"dur": s["dur"], "kind": s["tags"].get("kind", ""), "content": s["tags"].get("content", ""),
                      "description": s["tags"].get("description", ""), "sourcing_hint": s["tags"].get("sourcing_hint", ""),
                      "text_extra": s["tags"].get("text_extra"), "overlay_extra": s["tags"].get("overlay_extra"),
                      "motion": s["motion"], "keyframe": s["keyframe"]}
            for s in inspo if s["id"] in used}
    durs = sorted(s["dur"] for s in slots)
    out = {"session": session.name, "voice_end": end, "inspo_total": round(sum(s["dur"] for s in inspo), 3),
           "inspo_shots": len(inspo), "median_slot": durs[len(durs) // 2] if durs else 0,
           "median_inspo": sorted(s["dur"] for s in inspo)[len(inspo) // 2], "slots": slots, "refs": refs}
    write_json(session / "slots.json", out)
    return out


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Propose the cut for a mapped plan")
    ap.add_argument("--session", required=True)
    try:
        out = build(Path(ap.parse_args().session))
        print(json.dumps({"ok": True, "slots": len(out["slots"]), "voice_end": out["voice_end"],
                          "median_slot": out["median_slot"], "median_inspo": out["median_inspo"]}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
