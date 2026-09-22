"""Reconcile plan.json shot timing with real word-level timestamps.

Called by the timestamps skill after timestamps.json is written.
Updates plan.json in-place: replaces start/end with real segment timing,
sets timing_source to "timestamps". Leaves start_est/end_est untouched.

Matching strategy: sequential word-overlap. Shots and segments both follow
script order, so we scan forward through segments for each shot rather than
doing a global search (which would be slow and risk out-of-order matches).
"""

import json
from pathlib import Path


def reconcile(session_dir: Path, force: bool = False) -> dict:
    plan_path = session_dir / "plan.json"
    timestamps_path = session_dir / "timestamps.json"

    if not plan_path.exists():
        return {"ok": True, "skipped": True, "reason": "plan.json not found — nothing to reconcile"}

    if not timestamps_path.exists():
        return {"ok": False, "error": "timestamps.json not found"}

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    timestamps = json.loads(timestamps_path.read_text(encoding="utf-8"))

    # `force` exists for re-timing after the audio itself changed (see
    # tools/audio/tighten.py) — the plan is already marked reconciled, but
    # against timestamps that no longer describe the file.
    if plan.get("timing_source") == "timestamps" and not force:
        return {"ok": True, "skipped": True, "reason": "already reconciled"}

    segments = timestamps.get("segments", [])
    shots = plan.get("shots", [])

    if not segments:
        return {"ok": False, "error": "timestamps.json has no segments"}
    if not shots:
        return {"ok": False, "error": "plan.json has no shots"}

    words = [w for seg in segments for w in seg.get("words", [])]
    if words:
        updated_shots, updated_count = _match_words(shots, words)
    else:
        updated_shots, updated_count = _match(shots, segments)

    plan["shots"] = updated_shots
    plan["timing_source"] = "timestamps"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "ok": True,
        "skipped": False,
        "shots_updated": updated_count,
        "total_shots": len(updated_shots),
    }


def _match_words(shots: list[dict], words: list[dict]) -> tuple[list[dict], int]:
    """Sequentially align shots to the word stream.

    Shots' audio text and the transcript describe the same speech in the same
    order, so each shot consumes its own token count from the stream; the
    shot's real timing is the first/last consumed word. A small resync window
    around the expected end word absorbs tokenization drift (contractions,
    multi-word slots).
    """
    import re

    def norm(token: str) -> str:
        return re.sub(r"[^\w']", "", token.lower())

    stream = []
    for w in words:
        for piece in str(w.get("word", "")).split():
            if norm(piece):
                stream.append((norm(piece), w))

    cursor = 0
    updated = []
    updated_count = 0

    for shot in shots:
        stoks = [norm(t) for t in shot.get("audio", "").split() if norm(t)]
        if not stoks or cursor >= len(stream):
            updated.append(shot)
            continue

        end_i = min(cursor + len(stoks), len(stream)) - 1
        # Resync: snap to the nearest occurrence of the shot's last token.
        last = stoks[-1]
        for offset in (0, 1, -1, 2, -2, 3, -3):
            k = end_i + offset
            if cursor <= k < len(stream) and stream[k][0] == last:
                end_i = k
                break

        new_start = stream[cursor][1]["start"]
        new_end = stream[end_i][1]["end"]
        if new_start != shot.get("start_est") or new_end != shot.get("end_est"):
            updated_count += 1
        updated.append({**shot, "start": new_start, "end": new_end})
        cursor = end_i + 1

    return updated, updated_count


def _match(shots: list[dict], segments: list[dict]) -> tuple[list[dict], int]:
    """Sequentially match shots to segments by word overlap, maintaining order."""
    seg_cursor = 0
    updated = []
    updated_count = 0

    for shot in shots:
        if seg_cursor >= len(segments):
            # More shots than segments — keep the estimate rather than crash.
            updated.append(shot)
            continue

        shot_words = set(shot.get("audio", "").lower().split())

        best_j = seg_cursor
        best_score = -1.0

        # Look ahead up to 4 segments to handle minor misalignments
        for j in range(seg_cursor, min(seg_cursor + 4, len(segments))):
            seg_words = set(segments[j]["text"].lower().split())
            score = (len(shot_words & seg_words) / len(shot_words)) if shot_words else 0.0
            if score > best_score:
                best_score = score
                best_j = j

        matched = segments[best_j]
        new_start = matched["start"]
        new_end = matched["end"]

        changed = (new_start != shot.get("start_est") or new_end != shot.get("end_est"))
        if changed:
            updated_count += 1

        updated.append({**shot, "start": new_start, "end": new_end})
        seg_cursor = best_j + 1

    return updated, updated_count
