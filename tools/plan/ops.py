"""Structural edits to a plan — split, merge, add overlay — with the timing math.

The plan editor lets you rewrite a shot's fields; this handles the edits that
change the shot LIST and its timing: splitting one shot into two at a spoken
word, merging two, or adding an overlay. The timing is the substantive part —
"split at the word 'had'" means looking that word up in the real word-level
timestamps and cutting there, not guessing.

Shot numbers are stable keys used downstream (assets_progress.jsonl, assets.json,
motion_graphics.json), so an insert/remove renumbers the plan AND migrates those
feeds so existing picks stay aligned. Everything is backed up first (`*.pre-op.bak`).

    from tools.plan.ops import apply_op
    apply_op(Path("sessions/<id>"), {"op": "split", "shot": 4, "at_word": "2000"})
    apply_op(session, {"op": "merge", "shots": [4, 5]})
    apply_op(session, {"op": "overlay", "shot": 4, "caption": "27 BACKTESTS"})
"""

import copy
import json
import shutil
from pathlib import Path


def _norm(s: str) -> str:
    return "".join(c for c in str(s).lower() if c.isalnum())


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _backup(session: Path, names) -> None:
    for n in names:
        p = session / n
        bak = session / f"{n}.pre-op.bak"
        if p.exists() and not bak.exists():
            shutil.copy(p, bak)


def _words_in(timestamps: dict, lo: float, hi: float) -> list:
    out = []
    for seg in timestamps.get("segments", []):
        for w in seg.get("words", []):
            if lo - 0.3 <= float(w.get("start", 0)) <= hi + 0.3:
                out.append(w)
    return out


def _word_split_time(words: list, target: str) -> tuple[float | None, int]:
    """Onset of `target` and its index in `words`. Exact match first, then
    a word that contains it (handles '2000,' vs '2000')."""
    t = _norm(target)
    for i, w in enumerate(words):
        if _norm(w.get("word", "")) == t:
            return float(w.get("start", 0)), i
    for i, w in enumerate(words):
        if t and t in _norm(w.get("word", "")):
            return float(w.get("start", 0)), i
    return None, -1


def _renumber(shots: list) -> dict:
    """Reassign shot_number 1..N in order; return {old: new} for keys that moved.
    Only meaningful right after an insert/remove where the array order is correct."""
    remap = {}
    for i, s in enumerate(shots, start=1):
        old = s.get("shot_number")
        if old != i:
            remap[old] = i
        s["shot_number"] = i
    return remap


def _shift_feeds(session: Path, insert_after: int, delta: int, clone_from: int = None,
                 clone_to: int = None) -> None:
    """Keep downstream shot-number keys aligned after a plan insert/remove.

    delta is +1 (split, one shot became two) or -1 (merge). Keys strictly greater
    than `insert_after` shift by delta. For a split, `clone_from`→`clone_to`
    duplicates the split shot's asset onto the new shot so both halves keep the
    footage (render trims each to its own window)."""
    # assets_progress.jsonl — rewrite integer shot_number keys, keep overlay keys.
    feed = session / "assets_progress.jsonl"
    if feed.exists():
        rows = []
        for line in feed.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            sn = e.get("shot_number")
            if isinstance(sn, int) and sn > insert_after:
                e["shot_number"] = sn + delta
            rows.append(e)
        if clone_from is not None:
            src = [r for r in rows if r.get("shot_number") == clone_from]
            for r in src:
                c = dict(r)
                c["shot_number"] = clone_to
                rows.append(c)
        feed.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    # assets.json — same key shift on the shots map.
    aj = session / "assets.json"
    data = _load(aj)
    if data and isinstance(data.get("shots"), dict):
        newshots = {}
        for k, v in data["shots"].items():
            try:
                ik = int(k)
            except ValueError:
                newshots[k] = v  # overlay-style keys pass through
                continue
            nk = ik + delta if ik > insert_after else ik
            v = dict(v)
            v["shot_number"] = nk
            newshots[str(nk)] = v
        if clone_from is not None and str(clone_from) in newshots:
            c = dict(newshots[str(clone_from)])
            c["shot_number"] = clone_to
            newshots[str(clone_to)] = c
        data["shots"] = newshots
        aj.write_text(json.dumps(data, indent=2), encoding="utf-8")


def split(session: Path, shot_number: int, at_word: str) -> dict:
    plan_p = session / "plan.json"
    plan = _load(plan_p)
    if not plan:
        return {"ok": False, "error": "no plan.json"}
    ts = _load(session / "timestamps.json") or {}
    shots = plan["shots"]
    idx = next((i for i, s in enumerate(shots) if s.get("shot_number") == shot_number), -1)
    if idx < 0:
        return {"ok": False, "error": f"no shot {shot_number}"}
    s = shots[idx]
    start, end = float(s.get("start", 0)), float(s.get("end", 0))

    words = _words_in(ts, start, end)
    t_split, widx = _word_split_time(words, at_word)
    if t_split is None:
        return {"ok": False, "error": f"word '{at_word}' not found in shot {shot_number}"}
    if widx == 0:
        return {"ok": False, "error": f"'{at_word}' is the first word — nothing before it to split off"}

    # Split the spoken line at the word (by transcript order).
    before = " ".join(w.get("word", "") for w in words[:widx]).strip()
    after = " ".join(w.get("word", "") for w in words[widx:]).strip()

    _backup(session, ["plan.json", "assets_progress.jsonl", "assets.json"])

    a = copy.deepcopy(s)
    b = copy.deepcopy(s)
    a["end"] = round(t_split, 3)
    a["audio"] = before or s.get("audio", "")
    b["start"] = round(t_split, 3)
    b["audio"] = after or s.get("audio", "")
    b["transition"] = "cut"
    # start_est/end_est are superseded by real timing; keep them coherent.
    a["end_est"] = a["end"]; b["start_est"] = b["start"]
    # SFX follow their trigger word into whichever half it lands in.
    def _sfx_for(half_lo, half_hi):
        keep = []
        for e in (s.get("audio_layer") or {}).get("sfx", []):
            on = e.get("on") if isinstance(e, dict) else None
            if not on:
                keep.append(e); continue  # untriggered sfx ride with the first half
            wt, _ = _word_split_time(words, on)
            if wt is not None and half_lo <= wt < half_hi:
                keep.append(e)
        return keep
    if s.get("audio_layer"):
        a.setdefault("audio_layer", {})["sfx"] = _sfx_for(start, t_split) + \
            [e for e in (s["audio_layer"].get("sfx") or []) if not (isinstance(e, dict) and e.get("on"))]
        b.setdefault("audio_layer", {})["sfx"] = _sfx_for(t_split, end + 0.3)
        # de-dup the untriggered ones we appended to A
        seen = []
        a["audio_layer"]["sfx"] = [x for x in a["audio_layer"]["sfx"] if not (x in seen or seen.append(x))]

    shots[idx:idx + 1] = [a, b]
    remap = _renumber(shots)
    plan_p.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    # Downstream: shot B is new at (shot_number+1); shift keys and clone A's asset to B.
    new_a = shot_number  # after renumber, A keeps its number (nothing before it moved)
    _shift_feeds(session, insert_after=shot_number, delta=1,
                 clone_from=shot_number, clone_to=shot_number + 1)
    return {"ok": True, "op": "split", "shot": shot_number, "at_word": at_word,
            "at_time": round(t_split, 3), "into": [new_a, new_a + 1],
            "audio": [a["audio"], b["audio"]], "renumbered": len(remap)}


def merge(session: Path, shots_to_merge: list) -> dict:
    plan_p = session / "plan.json"
    plan = _load(plan_p)
    if not plan:
        return {"ok": False, "error": "no plan.json"}
    shots = plan["shots"]
    nums = sorted(int(n) for n in shots_to_merge)
    if len(nums) != 2 or nums[1] != nums[0] + 1:
        return {"ok": False, "error": "merge takes two ADJACENT shot numbers"}
    ia = next((i for i, s in enumerate(shots) if s.get("shot_number") == nums[0]), -1)
    ib = next((i for i, s in enumerate(shots) if s.get("shot_number") == nums[1]), -1)
    if ia < 0 or ib < 0:
        return {"ok": False, "error": "shots not found"}

    _backup(session, ["plan.json", "assets_progress.jsonl", "assets.json"])
    a, b = shots[ia], shots[ib]
    merged = copy.deepcopy(a)
    merged["end"] = b.get("end", a.get("end"))
    merged["end_est"] = merged["end"]
    merged["audio"] = (a.get("audio", "") + " " + b.get("audio", "")).strip()
    # Keep A's visual; union the sfx.
    al = merged.setdefault("audio_layer", {})
    al["sfx"] = ((a.get("audio_layer") or {}).get("sfx") or []) + \
                ((b.get("audio_layer") or {}).get("sfx") or [])

    shots[ia:ib + 1] = [merged]
    remap = _renumber(shots)
    plan_p.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    # b's number vanishes; keys above nums[1] shift down one. A keeps its asset.
    _shift_feeds(session, insert_after=nums[1], delta=-1)
    return {"ok": True, "op": "merge", "merged": nums, "into": nums[0],
            "audio": merged["audio"], "renumbered": len(remap)}


def add_overlay(session: Path, shot_number: int, caption: str, desc: str = "",
                style: str = "kinetic_text") -> dict:
    plan_p = session / "plan.json"
    plan = _load(plan_p)
    if not plan:
        return {"ok": False, "error": "no plan.json"}
    s = next((s for s in plan["shots"] if s.get("shot_number") == shot_number), None)
    if not s:
        return {"ok": False, "error": f"no shot {shot_number}"}
    if (s.get("visual") or {}).get("type") == "MOTION_GRAPHICS":
        return {"ok": False, "error": "shot is already MOTION_GRAPHICS — an overlay on a graphic is redundant"}
    _backup(session, ["plan.json"])
    s["overlay"] = {"caption": caption, "desc": desc or caption, "style": style}
    plan_p.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "op": "overlay", "shot": shot_number, "caption": caption}


def _apply_one(session: Path, op: dict) -> dict:
    kind = op.get("op")
    if kind == "split":
        return split(session, int(op["shot"]), str(op.get("at_word", "")))
    if kind == "merge":
        return merge(session, op.get("shots") or [])
    if kind == "overlay":
        return add_overlay(session, int(op["shot"]), str(op.get("caption", "")),
                           str(op.get("desc", "")), str(op.get("style", "kinetic_text")))
    return {"ok": False, "error": f"unknown op '{kind}'"}


def apply_op(session: Path, op) -> dict:
    """Apply one op, or a list of them in order.

    A list is the normal shape for "split this into four" — one command, three
    splits. They can't be applied independently: each split renumbers everything
    after it, so the second split's target has already moved by the time it runs.
    Rather than trust the caller to have predicted the shifts, a split whose word
    isn't in the shot it names is retried against the following few shots — which
    is exactly where the text went. Ops stop at the first hard failure so a bad
    tail can't leave the plan half-edited without saying so.
    """
    if isinstance(op, dict):
        return _apply_one(session, op)

    results, ok = [], True
    for i, one in enumerate(op):
        res = _apply_one(session, one)
        if not res.get("ok") and one.get("op") == "split" and "not found" in str(res.get("error", "")):
            base = int(one["shot"])
            for bump in (1, 2, 3):
                retry = dict(one, shot=base + bump)
                res = _apply_one(session, retry)
                if res.get("ok"):
                    res["retargeted_from"] = base
                    break
        results.append(res)
        if not res.get("ok"):
            ok = False
            res["stopped_at"] = i
            break
    return {"ok": ok, "applied": sum(1 for r in results if r.get("ok")),
            "of": len(op), "results": results}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Apply a structural plan edit")
    ap.add_argument("--session", required=True)
    ap.add_argument("--op", required=True, help="JSON op, e.g. '{\"op\":\"split\",\"shot\":4,\"at_word\":\"2000\"}'")
    a = ap.parse_args()
    print(json.dumps(apply_op(Path(a.session), json.loads(a.op)), indent=2, ensure_ascii=False))
