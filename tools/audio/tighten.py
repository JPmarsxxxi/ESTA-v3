"""Tighten a voiceover by shrinking the dead air between words.

Why this exists: XTTS (and human takes) leave 1s+ holes at sentence boundaries.
On a fast-cut edit that reads as drag. This removes the excess *inside* gaps
while leaving a deliberate breather where comprehension needs one — a longer
allowance after sentence-ending punctuation than mid-sentence.

The re-timing is analytic, not a re-transcription: we know exactly how much was
removed and where, so every word/segment time shifts by the removed total before
it. That keeps the words identical to what was actually spoken (a whisper re-run
could disagree with itself) and costs no GPU time.

Downstream: plan.json is re-reconciled against the new timestamps, then render
rebuilds. The original audio is preserved as audio.original.wav.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SENTENCE_END = (".", "!", "?", "…")


def _words(timestamps: dict) -> list[dict]:
    return [w for seg in timestamps.get("segments", []) for w in seg.get("words", [])]


def plan_cuts(timestamps: dict, max_gap: float, sentence_gap: float,
              lead: float) -> tuple[list[tuple[float, float]], float]:
    """-> ([(cut_start, cut_end), ...], seconds_removed).

    A cut always sits strictly between two words, so no speech is ever clipped.
    """
    words = _words(timestamps)
    if not words:
        return [], 0.0

    cuts: list[tuple[float, float]] = []

    # Dead air before the first word — keep a short run-up, drop the rest.
    first = float(words[0]["start"])
    if first > lead:
        cuts.append((0.0, first - lead))

    for a, b in zip(words, words[1:]):
        end_a, start_b = float(a["end"]), float(b["start"])
        gap = start_b - end_a
        # A breather is earned by punctuation: end of a sentence gets more room
        # than a mid-sentence stumble.
        allowed = sentence_gap if str(a.get("word", "")).strip().endswith(SENTENCE_END) else max_gap
        if gap > allowed:
            # Trim from the middle of the gap so both words keep their natural
            # release and onset rather than butting straight together.
            excess = gap - allowed
            mid = end_a + gap / 2
            cuts.append((mid - excess / 2, mid + excess / 2))

    removed = sum(e - s for s, e in cuts)
    return cuts, removed


def keep_intervals(cuts: list[tuple[float, float]], total: float) -> list[tuple[float, float]]:
    keeps, pos = [], 0.0
    for s, e in cuts:
        if s > pos:
            keeps.append((pos, s))
        pos = max(pos, e)
    if pos < total:
        keeps.append((pos, total))
    return keeps


def shift_for(t: float, cuts: list[tuple[float, float]]) -> float:
    """New timeline position of an old time, after the cuts are applied."""
    removed = 0.0
    for s, e in cuts:
        if e <= t:
            removed += e - s
        elif s < t < e:
            removed += t - s  # inside a cut (only silence lives here)
    return round(t - removed, 3)


def retime(timestamps: dict, cuts: list[tuple[float, float]], new_total: float) -> dict:
    out = dict(timestamps)
    segs = []
    for seg in timestamps.get("segments", []):
        s = dict(seg)
        s["start"] = shift_for(float(seg.get("start", 0)), cuts)
        s["end"] = shift_for(float(seg.get("end", 0)), cuts)
        s["duration"] = round(s["end"] - s["start"], 3)
        ws = []
        for w in seg.get("words", []):
            nw = dict(w)
            nw["start"] = shift_for(float(w.get("start", 0)), cuts)
            nw["end"] = shift_for(float(w.get("end", 0)), cuts)
            nw["duration"] = round(nw["end"] - nw["start"], 3)
            ws.append(nw)
        s["words"] = ws
        segs.append(s)
    out["segments"] = segs
    out["total_duration"] = round(new_total, 3)

    # Recompute the silence map against the tightened timeline.
    words = [w for s in segs for w in s.get("words", [])]
    pts = []
    for a, b in zip(words, words[1:]):
        gap = round(float(b["start"]) - float(a["end"]), 3)
        if gap >= 0.2:
            pts.append({"start": float(a["end"]), "end": float(b["start"]),
                        "duration": gap, "type": "intra_segment"})
    out["silence_points"] = pts
    out["tightened"] = {"cuts": len(cuts),
                        "removed_s": round(sum(e - s for s, e in cuts), 3)}
    return out


def cut_audio(src: Path, dst: Path, keeps: list[tuple[float, float]]) -> None:
    parts = []
    for i, (s, e) in enumerate(keeps):
        parts.append(f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS[a{i}]")
    concat = "".join(f"[a{i}]" for i in range(len(keeps))) + f"concat=n={len(keeps)}:v=0:a=1[out]"
    fc = ";".join(parts + [concat])
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
           "-filter_complex", fc, "-map", "[out]", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-600:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Shrink dead air in the session voiceover")
    ap.add_argument("--session", required=True)
    ap.add_argument("--max-gap", type=float, default=0.35, dest="max_gap",
                    help="longest gap kept mid-sentence (default 0.35s)")
    ap.add_argument("--sentence-gap", type=float, default=0.5, dest="sentence_gap",
                    help="longest gap kept after . ! ? — the comprehension breather (default 0.5s)")
    ap.add_argument("--lead", type=float, default=0.2,
                    help="silence kept before the first word (default 0.2s)")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    args = ap.parse_args()

    session = Path(args.session)
    ts_path = session / "timestamps.json"
    wav = session / "audio.wav"
    for p in (ts_path, wav):
        if not p.exists():
            print(json.dumps({"ok": False, "error": f"{p} not found"}))
            sys.exit(1)

    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    total = float(ts.get("total_duration") or 0)
    cuts, removed = plan_cuts(ts, args.max_gap, args.sentence_gap, args.lead)
    new_total = total - removed

    if args.dry_run or not cuts:
        print(json.dumps({"ok": True, "dry_run": True, "cuts": len(cuts),
                          "removed_s": round(removed, 3),
                          "old_duration": round(total, 3),
                          "new_duration": round(new_total, 3)}, indent=2))
        return

    # Keep the untouched take — tightening is a judgement call and re-running it
    # from an already-tightened file would compound the trims.
    original = session / "audio.original.wav"
    if not original.exists():
        shutil.copy(wav, original)

    keeps = keep_intervals(cuts, total)
    tmp = session / "audio.tight.tmp.wav"
    cut_audio(original, tmp, keeps)
    tmp.replace(wav)

    ts_path.write_text(json.dumps(retime(ts, cuts, new_total), indent=2, ensure_ascii=False),
                       encoding="utf-8")

    meta_path = session / "audio_metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # render reads `duration_seconds` (see _build_audio) — updating only a
        # `duration` key leaves the voiceover clip at its pre-cut length and the
        # whole timeline stretches past the audio.
        meta["tightened_from"] = meta.get("duration_seconds", round(total, 3))
        meta["duration_seconds"] = round(new_total, 3)
        meta["duration_minutes"] = round(new_total / 60, 2)
        meta["duration"] = round(new_total, 3)
        wav_size = wav.stat().st_size if wav.exists() else 0
        if wav_size:
            meta["file_size_mb"] = round(wav_size / (1024 * 1024), 2)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "cuts": len(cuts), "removed_s": round(removed, 3),
                      "old_duration": round(total, 3), "new_duration": round(new_total, 3),
                      "original_kept": str(original)}, indent=2))


if __name__ == "__main__":
    main()
