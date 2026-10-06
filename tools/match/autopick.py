"""Auto-pick: choose each shot's asset the way the user would in the picker.

    python tools/match/autopick.py --session sessions/<id> [--shots 3,7,12] [--per-source 2]

1. Gathers candidates per shot (`assets/run.py candidates`, the picker's path).
2. Hard filters, in the order of SPEC.md Part 3 decision 11: a video must be at
   least as long as the shot (else the longest one, flagged short_clip), and
   its kind must match the shot's (video for footage, image for a still; giphy
   loops fit either).
   A candidate over 3x its shot's length (not YouTube, whose finder already chose
   a moment) is moved to its best shot-length window, scored frame by frame.
3. Ranks the survivors: SigLIP 2 fit to the shot's desc and spoken line, plus
   DINOv3 closeness to the shot's ref_shot keyframe (the whole inspo when the
   shot has no ref), minus a penalty for reusing a file another shot shows.
4. Haiku judges each shot's top three against the ref keyframe, 10 shots per
   call, and may reject them (watermarks, wrong subject, junk).
5. Fills a pick shorter than its shot: slowed to fit down to 0.6x, else
   repeated back to back (Giphy loops), else both and flagged short_clip.
6. Writes the pick to assets_progress.jsonl (visual_verdict "auto_picked") and
   assets.json, and clears the shot's queries_stale.

Stock (Pexels, Pixabay) is a capped last resort (SPEC.md Part 7). A shot whose
gathers find nothing outside stock gets its query rewritten by Haiku up to
`assets.stock_rewrites` times, searched on every non-stock source of its kind.
Only then may it take stock, while fewer than floor(stock_cap x shots) shots
hold a stock pick; past that it becomes a word-card motion graphic. A non-stock
candidate that survives the filters always beats any stock one.

Without `claude` the local ranking decides, and the report says so.
"""

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match import score as scorer  # noqa: E402
from tools.assets.run import STOCK_SOURCES  # noqa: E402
from tools.match.common import (  # noqa: E402
    REPO_ROOT, frames_at, load_config, match_config, media_frames, read_json, run_esta, save_jpg, utf8_stdout,
    write_json,
)
from tools.match.describe import ask, image_block  # noqa: E402
from tools.motiongraphics import wordcard  # noqa: E402

JOBS_DIR = REPO_ROOT / "cache" / "pick"
FINALISTS = 3
JUDGE_BATCH = 10
WINDOW_OVER = 3.0     # a candidate this many times its shot's length is searched for its best section
WINDOW_STEP = 0.5
WINDOW_MAX_FRAMES = 600
FRAME_SIDE = 640      # judged at 512, embedded at 384
SLOW_FLOOR = 0.6      # slower than this stops reading as natural slow motion
SHOT_KIND = {"REAL_IMAGE": "still", "MOTION_GRAPHICS": "graphic"}
STOCK = {"pexels", "pixabay"}  # the `source` a stock candidate or feed row carries
STOCK_CAP, STOCK_REWRITES = 0.15, 3
# Rewritten queries search the shot's own sources plus every non-stock source of its kind.
KIND_SOURCES = {"footage": ["youtube", "archive", "giphy"], "still": ["google_images", "pinterest", "wikimedia", "openverse"],
                "graphic": ["giphy"]}
STOCK_BY_KIND = {"footage": "pexels_video,pixabay_video", "still": "pexels_image,pixabay_image",
                 "graphic": "pexels_video,pixabay_video,pexels_image,pixabay_image"}
STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "with", "for", "from", "into", "over", "his", "her",
        "their", "its", "that", "this", "shot", "photo", "image", "video", "clip", "footage"}
REWRITE_SYSTEM = "You write search queries for stock and archive footage. Reply with only the requested JSON."
REWRITE_PROMPT = (
    "Each shot above found nothing on the listed sources with the failed queries. For each shot write ONE new "
    "search query, 2-4 words, that a clip or image library would match: plainer, more visual words, the subject "
    "and an action or setting, no names the library can't know. It must differ from every failed query. "
    'Reply with ONLY one JSON object mapping each shot number to its query, e.g. {"12": "crowd cheering stadium"}.'
)
JUDGE_SYSTEM = "You pick stock footage for a video editor. Reply with only the requested JSON."

JUDGE_PROMPT = (
    "Each shot above shows the INSPO frame the shot must feel like (its look, framing and treatment, not its subject), "
    "then candidate clips numbered 1 to 3. Pick the candidate a creator copying that inspo would use for the spoken "
    "line. Reject a candidate if it has a visible watermark or logo, shows the wrong subject, is blurry or broken, or "
    "is off-tone for the line. Reply with ONLY one JSON object mapping each shot id to "
    '{"best": <number>, "reject": [<numbers>], "why": "<one short reason>"}.'
)


def cand_kind(c: dict) -> str:
    if c.get("source") == "giphy":
        return "any"
    return "still" if c.get("asset_type") == "image" else "footage"


def filter_candidates(shot: dict, cands: list[dict]) -> tuple[list[dict], bool]:
    """Hard filters before ranking: kind, then length. Returns (survivors, short_clip)."""
    kind = SHOT_KIND.get((shot.get("visual") or {}).get("type"), "footage")
    # A graphic is generated; stock for it is only the named-shot fallback, so any kind will do.
    same = cands if kind == "graphic" else [c for c in cands if cand_kind(c) in ("any", kind)]
    dur = float(shot.get("end", 0) or 0) - float(shot.get("start", 0) or 0)
    timed = [c for c in same if cand_kind(c) == "footage"]
    long_enough = [c for c in same if cand_kind(c) != "footage"
                   or (c.get("source_duration") or 0) - (c.get("in_point") or 0) >= dur - 0.05]
    if long_enough or not timed:
        return long_enough, False
    # Nothing fills the shot: the longest clip, flagged (render holds its last frame).
    return [max(timed, key=lambda c: (c.get("source_duration") or 0) - (c.get("in_point") or 0))], True


def best_window(scores, step: float, shot_dur: float) -> int:
    """Index of the first sample of the shot-length window with the best mean score."""
    import numpy as np
    w = max(1, min(len(scores), round(shot_dur / step)))
    means = np.convolve(scores, np.ones(w) / w, mode="valid")
    return int(np.argmax(means))


def fill(c: dict, shot_dur: float) -> dict:
    """How a pick shorter than its shot fills it (SPEC.md Part 3, decision 11b): {} when it already does."""
    usable = (c.get("source_duration") or 0) - (c.get("in_point") or 0)
    if c.get("asset_type") == "image" or usable <= 0 or usable >= shot_dur - 0.05:
        return {}
    if usable >= SLOW_FLOOR * shot_dur:
        return {"speed": round(usable / shot_dur, 3)}
    if c.get("source") == "giphy":
        return {"repeat": math.ceil(shot_dur / usable)}
    return {"speed": SLOW_FLOOR, "repeat": math.ceil(shot_dur * SLOW_FLOOR / usable), "short_clip": True}


def judge(items: list[dict], log=print) -> tuple[dict, float, list[str]]:
    """items: [{"n", "ref_image", "ref_desc", "desc", "audio", "finals": [jpg]}] -> ({n: verdict}, cost, errors)."""
    cfg = match_config()["describe"]
    batches = [items[i:i + JUDGE_BATCH] for i in range(0, len(items), JUDGE_BATCH)]

    def one(batch):
        content = []
        for it in batch:
            content.append({"type": "text", "text": f"Shot {it['n']}. Spoken line: \"{it['audio']}\". Planned: {it['desc']}"
                            + (f" INSPO frame ({it['ref_desc']}):" if it.get("ref_image") else " (no inspo frame)")})
            if it.get("ref_image"):
                content.append(image_block(it["ref_image"], cfg["max_side"]))
            for j, f in enumerate(it["finals"], 1):
                content.append({"type": "text", "text": f"Shot {it['n']} candidate {j}:"})
                content.append(image_block(f, cfg["max_side"]))
        content.append({"type": "text", "text": JUDGE_PROMPT})
        return ask(content, JUDGE_SYSTEM, cfg["model"])

    log(f"[autopick] Haiku judges {len(items)} shots in {len(batches)} calls")
    with ThreadPoolExecutor(cfg["workers"]) as pool:
        results = list(pool.map(one, batches))
    verdicts, cost, errors = {}, 0.0, []
    for res in results:
        cost += res.get("cost", 0.0)
        if "error" in res:
            errors.append(res["error"][:200])
            continue
        for k, v in res["answer"].items():
            if str(k).isdigit() and isinstance(v, dict):
                verdicts[int(k)] = v
    return verdicts, cost, errors


def log(m: str) -> None:
    print(m, flush=True)


def is_stock(c: dict) -> bool:
    return c.get("source") in STOCK


def prefer_non_stock(cands: list[dict]) -> list[dict]:
    """A stock candidate is only ever ranked when nothing else survived the filters."""
    other = [c for c in cands if not is_stock(c)]
    return other or cands


def assets_config() -> dict:
    try:
        return load_config().get("assets") or {}
    except OSError:
        return {}


def stock_budget(session: Path, total: int) -> int:
    ui = (read_json(session / "pipeline.json", {}) or {}).get("ui") or {}
    cap = ui.get("stock_cap")
    if cap is None:
        cap = assets_config().get("stock_cap", STOCK_CAP)
    return math.floor(float(cap) * total + 1e-9)


def stock_used(rows: dict, skip: set[int]) -> int:
    """Shots whose current pick is stock; the shots being re-picked don't count."""
    return sum(1 for k, r in rows.items() if k.isdigit() and int(k) not in skip and r.get("ok") and is_stock(r))


def shot_kind(shot: dict) -> str:
    return SHOT_KIND.get((shot.get("visual") or {}).get("type"), "footage")


def has_usable(manifest: dict, shot: dict) -> bool:
    """Something outside stock survives the shot's hard filters."""
    return any(not is_stock(c) for c in filter_candidates(shot, manifest.get("candidates", []))[0])


def chrome_pending(session: Path) -> set[int]:
    q = read_json(session / "assets" / "chrome_queue.json", {}) or {}
    return {int(k) for k, v in (q.get("shots") or {}).items() if str(k).isdigit() and v.get("status") == "pending"}


def _fallback_query(shot: dict, tried: list[str]) -> str:
    """Without Haiku: the last query minus its last word, then the desc's nouns."""
    last = (tried[-1] if tried else "").split()
    if len(last) > 2 and " ".join(last[:-1]) not in tried:
        return " ".join(last[:-1])
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", (shot.get("visual") or {}).get("desc", "")) if w.lower() not in STOP]
    for k in (3, 2, 4):
        q = " ".join(words[:k]).lower()
        if q and q not in tried:
            return q
    return ""


def rewrite(items: list[dict], log=log) -> dict[int, str]:
    """items: [{"n", "shot", "kind", "sources", "tried"}] -> {n: new query}, batched like the judge.
    A shot Haiku can't answer gets the plain fallback; a query already tried comes back empty."""
    cfg = match_config()["describe"]
    out: dict[int, str] = {}

    def one(batch):
        content = [{"type": "text", "text": f"Shot {it['n']} ({it['kind']}). Spoken line: \"{it['shot'].get('audio', '')}\". "
                    f"Planned: {(it['shot'].get('visual') or {}).get('desc', '')}. Sources: {', '.join(it['sources'])}. "
                    f"Failed queries: {json.dumps(it['tried'])}"} for it in batch]
        content.append({"type": "text", "text": REWRITE_PROMPT})
        return ask(content, REWRITE_SYSTEM, cfg["model"])

    batches = [items[i:i + JUDGE_BATCH] for i in range(0, len(items), JUDGE_BATCH)]
    try:
        with ThreadPoolExecutor(cfg["workers"]) as pool:
            results = list(pool.map(one, batches))
    except Exception as e:  # noqa: BLE001 - claude missing: every shot takes the fallback
        log(f"[autopick] rewriter unavailable, using plain fallbacks: {e}")
        results = [{"error": str(e)}] * len(batches)
    for res in results:
        for k, v in (res.get("answer") or {}).items():
            if str(k).isdigit() and isinstance(v, str):
                out[int(k)] = " ".join(v.split()[:5])
    for it in items:
        q = out.get(it["n"], "").strip().lower()
        out[it["n"]] = q if q and q not in it["tried"] else _fallback_query(it["shot"], it["tried"])
    return out


def _search(session: Path, n: int, per_source: int, query: str, sources: list[str]) -> dict:
    """One extra gather for a shot: `query` on `sources`. Overwrites the shot's manifest; the caller merges."""
    args = ["tools/assets/run.py", "candidates", "--session", str(session), "--n", str(n), "--per-source",
            str(per_source), "--queries", query, "--sources", ",".join(sources)]
    try:
        err = run_esta(args, timeout=600).stderr[-200:]
    except subprocess.TimeoutExpired:
        return {"candidates": [], "error": f"gather timed out: {query}"}
    got = read_json(session / "assets" / "candidates" / f"shot_{n}.json", {}) or {}
    return got if got.get("candidates") else {"candidates": [], "error": err}


def _merge(base: dict, extra: dict) -> dict:
    seen = {c.get("candidate_id") or c.get("file") for c in base.get("candidates", [])}
    add = [c for c in extra.get("candidates", []) if (c.get("candidate_id") or c.get("file")) not in seen]
    return {**base, "candidates": base.get("candidates", []) + add}


def widen(session: Path, plan_shots: dict, manifests: dict, per_source: int, skip: set[int], log=log) -> None:
    """Rewrite rounds for every shot with nothing outside stock (decision 3). Mutates and saves `manifests`."""
    rounds = int(assets_config().get("stock_rewrites", STOCK_REWRITES))
    tried = {n: [q for e in (plan_shots[n].get("visual") or {}).get("search_sources") or [] for q in e.get("queries") or []]
             for n in manifests}
    for n, m in manifests.items():
        tried[n] = list(dict.fromkeys(tried[n] + [r["query"] for r in m.get("rewrites", [])]))
    for r in range(1, rounds + 1):
        empty = [n for n, m in manifests.items() if not has_usable(m, plan_shots[n]) and n not in skip
                 and sum(1 for x in m.get("rewrites", [])) < rounds]
        if not empty:
            break
        items = []
        for n in empty:
            s = plan_shots[n]
            own = [e.get("source") for e in (s.get("visual") or {}).get("search_sources") or []
                   if e.get("source") and e.get("source") not in STOCK_SOURCES]
            items.append({"n": n, "shot": s, "kind": shot_kind(s), "tried": [q.lower() for q in tried[n]],
                          "sources": list(dict.fromkeys(own + KIND_SOURCES[shot_kind(s)]))})
        log(f"[autopick] rewrite round {r}: {len(items)} shots found nothing outside stock")
        queries = rewrite(items, log)

        def go(it):
            q = queries.get(it["n"], "")
            got = _search(session, it["n"], per_source, q, it["sources"]) if q else {"candidates": []}
            return it, q, got

        with ThreadPoolExecutor(max_workers=4) as pool:
            for it, q, got in pool.map(go, items):
                n = it["n"]
                manifests[n] = _merge(manifests[n], got)
                manifests[n].setdefault("rewrites", []).append(
                    {"round": r, "query": q, "sources": it["sources"], "found": len(got.get("candidates", []))})
                if q:
                    tried[n].append(q)
    for n, m in manifests.items():
        if m.get("rewrites"):
            m["queries"] = list(dict.fromkeys((m.get("queries") or []) + [x["query"] for x in m["rewrites"] if x["query"]]))
            save_manifest(session, n, m)


def retype(shot: dict, reason: str) -> None:
    v = shot.setdefault("visual", {})
    if v.get("type") != "MOTION_GRAPHICS":
        v["retyped_from"] = v.get("type", "")
    v["type"] = "MOTION_GRAPHICS"
    v["retype_reason"] = reason


def make_graphics(session: Path, shots: list[dict], log=log) -> dict:
    """Word cards for the retyped shots (tests replace this: it renders with HyperFrames)."""
    return wordcard.make(session, shots, log)


def save_manifest(session: Path, n: int, m: dict) -> None:
    path = session / "assets" / "candidates" / f"shot_{n}.json"
    write_json(path, {**(read_json(path, {}) or {}), **m})


def _gather(session: Path, n: int, per_source: int) -> dict:
    # A shot gathered earlier with the same queries is reused (the run may have been cut off).
    have = read_json(session / "assets" / "candidates" / f"shot_{n}.json")
    plan = read_json(session / "plan.json", {}) or {}
    shot = next((s for s in plan.get("shots", []) if s["shot_number"] == n), {})
    queries = [q for e in (shot.get("visual") or {}).get("search_sources") or [] for q in (e.get("queries") or [])[:1]]
    if have and has_usable(have, shot) and set(queries) <= set(have.get("queries", [])):
        return have
    # One query per source keeps downloads bounded; an empty result widens to
    # every query. Nothing here reaches stock: that is widen()'s rewrites, then the budget.
    base = ["tools/assets/run.py", "candidates", "--session", str(session), "--n", str(n), "--per-source", str(per_source)]
    err, got = "", {}
    for extra in (["--max-queries", "1"], []):
        # A hung source (a huge archive.org file) must cost this shot, not the whole run.
        try:
            err = run_esta(base + extra, timeout=600).stderr[-200:]
        except subprocess.TimeoutExpired:
            err = f"gather timed out: {' '.join(extra)}"
            continue
        got = read_json(session / "assets" / "candidates" / f"shot_{n}.json", {}) or {}
        if has_usable(got, shot):
            return got
    return {**got, "error": err} if got.get("candidates") else {"candidates": [], "error": err}


def run(session: Path, shots: list[int] | None = None, per_source: int = 2, log=log,
        repicking: set[int] | None = None) -> dict:
    import numpy as np
    from tools.match.common import Embedder
    plan = read_json(session / "plan.json", {}) or {}
    mg = {str(s.get("key")) for s in (read_json(session / "motion_graphics.json", {}) or {}).get("slots", []) if s.get("ok")}
    # Graphics are generated (motion-graphics skill); stock for them is only a
    # fallback, fetched when a shot is named explicitly.
    wanted = [s for s in plan.get("shots", []) if (s["shot_number"] in shots if shots is not None
              else (s.get("visual") or {}).get("type") != "MOTION_GRAPHICS") and str(s["shot_number"]) not in mg]
    log(f"[autopick] gathering candidates for {len(wanted)} shots")
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifests = dict(zip([s["shot_number"] for s in wanted],
                             pool.map(lambda s: _gather(session, s["shot_number"], per_source), wanted)))
    by_n = {s["shot_number"]: s for s in wanted}
    pending = chrome_pending(session)
    widen(session, by_n, manifests, per_source, pending, log)

    # Stock only after the rewrites, and only while the video-wide budget lasts (decision 5).
    budget = stock_budget(session, len(plan.get("shots", [])))
    # A stock pick that is about to be replaced (this run, or a later chunk of the same re-pick) holds no slot.
    stock_n = stock_used(scorer._asset_rows(session), set(manifests) | (repicking or set()))
    need = [n for n, m in manifests.items() if not has_usable(m, by_n[n]) and n not in pending]
    room = max(0, budget - stock_n)
    to_graphic = {n: "stock_cap" for n in need[room:]}
    for n in need[:room]:
        m = manifests[n]
        if not any(is_stock(c) for c in m.get("candidates", [])):
            q = (by_n[n].get("visual") or {}).get("search_query", "") or (m.get("queries") or [""])[0] \
                or next((x["query"] for x in m.get("rewrites", []) if x["query"]), "")
            got = _search(session, n, per_source, q, STOCK_BY_KIND[shot_kind(by_n[n])].split(","))
            manifests[n] = {**_merge(m, got), "stock_fallback": {"query": q, "found": len(got.get("candidates", []))}}
            save_manifest(session, n, manifests[n])
        if not filter_candidates(by_n[n], manifests[n].get("candidates", []))[0]:
            to_graphic[n] = "no_candidates"
    log(f"[autopick] stock: {stock_n} of {budget} used before this run; {len(need)} shots need it, "
        f"{len(to_graphic)} become graphics, {len(pending)} wait on the Chrome pass")
    for n, m in manifests.items():
        if not m.get("candidates"):
            log(f"[autopick] shot {n}: no candidates: {m.get('error', '')[-160:]}")

    inspo = scorer.load_inspo(session)
    emb = Embedder()
    feed_rows = scorer._asset_rows(session)
    used = {Path(str(r.get("file", ""))).name for k, r in feed_rows.items()
            if r.get("ok") and not (k.isdigit() and int(k) in manifests)}
    job = JOBS_DIR / (session.name[:30] + "-" + hashlib.sha1(json.dumps(sorted(manifests)).encode()).hexdigest()[:8])
    job.mkdir(parents=True, exist_ok=True)
    ref_row, ref_image = {}, {}
    if inspo:
        idx = read_json(session / "inspo_profiles.json", {}) or {}
        kf = {sh["id"]: REPO_ROOT / rel / sh["keyframe"] for rel in idx.get("profiles", [])
              for sh in (read_json(REPO_ROOT / rel / "profile.json", {}) or {}).get("shots", []) if sh.get("keyframe")}
        for i, sh in enumerate(inspo["shots"]):
            ref_row[sh["id"]] = i
            if sh["id"] in kf and kf[sh["id"]].exists():
                ref_image[sh["id"]] = kf[sh["id"]]
    ranked, items, short = {}, [], {}
    for s in wanted:
        n = s["shot_number"]
        # A shot waiting on the Chrome pass is picked from what it has, and re-picked after the pass.
        if n in to_graphic or (n in pending and not has_usable(manifests[n], s)):
            continue
        cands = [c for c in manifests[n].get("candidates", []) if Path(REPO_ROOT / c["file"]).exists() or Path(c["file"]).exists()]
        cands, short[n] = filter_candidates(s, cands)
        cands = prefer_non_stock(cands)
        if not cands:
            continue
        v = s.get("visual") or {}
        text = emb.siglip_texts([f"{v.get('desc', '')}. {s.get('audio', '')}"[:300]])[0]
        ref = ref_row.get(s.get("ref_shot"))
        dur = float(s.get("end", 0) or 0) - float(s.get("start", 0) or 0)

        def likeness(frames):
            d = emb.dino(frames)
            if ref is not None:
                return d @ inspo["dino"][ref]
            return (d @ inspo["dino"].T).max(axis=1) if inspo else np.zeros(len(frames))

        rows = []
        for c in cands:
            path = Path(c["file"]) if Path(c["file"]).is_absolute() else REPO_ROOT / c["file"]
            usable = (c.get("source_duration") or 0) - (c.get("in_point") or 0)
            if c.get("asset_type") == "video" and c.get("source") != "youtube" and usable > WINDOW_OVER * dur > 0:
                step = max(WINDOW_STEP, usable / WINDOW_MAX_FRAMES)
                times = [c.get("in_point", 0) + i * step for i in range(int(usable / step))]
                try:
                    frames = frames_at(path, times, FRAME_SIDE)
                except Exception:
                    frames = []
                if len(frames) == len(times) and frames:
                    z = lambda x: (x - x.mean()) / (x.std() + 1e-6) if len(x) > 1 else x * 0  # noqa: E731
                    i = best_window(0.6 * z(emb.siglip_images(frames) @ text) + 0.4 * z(likeness(frames)), step, dur)
                    c = {**c, "in_point": round(times[i], 3), "out_point": round(times[i] + dur, 3), "windowed": True}
            try:
                frames = media_frames(path, c.get("in_point") or 0, c.get("out_point") or 0, max_side=FRAME_SIDE)
            except Exception:
                frames = []
            if frames:
                rows.append((c, frames))
        if not rows:
            continue
        mids = [f[len(f) // 2] for _, f in rows]
        fit = emb.siglip_images(mids) @ text
        look = likeness(mids)
        z = lambda x: (x - x.mean()) / (x.std() + 1e-6) if len(x) > 1 else x * 0  # noqa: E731
        reuse = np.array([1.0 if Path(c["file"]).name in used else 0.0 for c, _ in rows])
        total = 0.6 * z(fit) + 0.4 * z(look) - 1.0 * reuse
        order = list(np.argsort(-total))
        ranked[n] = [(rows[i][0], float(total[i]), float(fit[i]), float(look[i])) for i in order]
        finals = order[:FINALISTS]
        if len(finals) > 1:
            paths = [save_jpg(mids[i], job / f"s{n}_{j + 1}.jpg", max_side=512) for j, i in enumerate(finals)]
            rs = inspo["shots"][ref] if ref is not None else {}
            items.append({"n": n, "finals": paths, "desc": v.get("desc", ""), "audio": s.get("audio", ""),
                          "ref_image": ref_image.get(s.get("ref_shot")),
                          "ref_desc": (rs.get("tags") or {}).get("description", "")})

    verdicts, lane, judge_cost = {}, "local ranking", 0.0
    if items:
        try:
            verdicts, judge_cost, errors = judge(items, log)
            lane = "haiku judge" + (f" ({len(errors)} failed calls: local ranking there)" if errors else "")
        except Exception as e:  # noqa: BLE001 - claude missing or failing: the local ranking stands
            log(f"[autopick] judge unavailable, using local ranking: {e}")

    feed = session / "assets_progress.jsonl"
    picked, report = 0, {}
    with open(feed, "a", encoding="utf-8") as fh:
        for n, cands in ranked.items():
            if is_stock(cands[0][0]):
                # Only stock is left for this shot (prefer_non_stock): it takes a budget slot or becomes a graphic.
                if stock_n >= budget:
                    to_graphic[n] = "stock_cap"
                    continue
                stock_n += 1
            choice, why = cands[0], "local rank"
            vd = verdicts.get(n)
            if vd:
                reject = {int(x) for x in vd.get("reject") or [] if str(x).isdigit()}
                best = int(vd.get("best") or 1) if str(vd.get("best", "")).isdigit() else 1
                finals = cands[:FINALISTS]
                if 1 <= best <= len(finals) and best not in reject:
                    choice, why = finals[best - 1], f"haiku: {vd.get('why', '')}"[:200]
                else:
                    keep = [c for j, c in enumerate(finals, 1) if j not in reject]
                    spare = cands[FINALISTS] if len(cands) > FINALISTS else finals[0]
                    choice, why = (keep[0] if keep else spare), f"haiku rejected its pick; next best ({vd.get('why', '')})"[:200]
            c, total, fit, look = choice
            shot_dur = float(by_n[n].get("end", 0) or 0) - float(by_n[n].get("start", 0) or 0)
            filled = fill(c, shot_dur)
            if short.get(n):
                filled["short_clip"] = True
            row = {"shot_number": n, "ok": True, "source": c["source"], "asset_type": c["asset_type"],
                   "url": c.get("url", ""), "file": c["file"], "search_query": c.get("query", ""),
                   "in_point": c.get("in_point", 0), "out_point": c.get("out_point", 0),
                   "visual_verdict": "auto_picked", "visual_confidence": int(max(0, min(100, 50 + 20 * total))),
                   "error": "", **filled, **({"audio_missing": True} if c.get("audio_missing") else {})}
            fh.write(json.dumps(row) + "\n")
            report[n] = {"file": Path(c["file"]).name, "why": why, "fit": round(fit, 3), "look": round(look, 3),
                         "of": len(cands), "in_point": c.get("in_point", 0), **filled}
            picked += 1

    rows = scorer._asset_rows(session)
    shots_map = {k: v for k, v in rows.items()}
    ok = sum(1 for v in shots_map.values() if v.get("ok"))
    write_json(session / "assets.json", {"session_id": session.name, "shots_total": len(plan.get("shots", [])),
                                         "shots_fetched": ok, "shots_failed": len(shots_map) - ok, "shots": shots_map,
                                         "timestamp": datetime.now().isoformat(), "picked_by": lane})
    plan = read_json(session / "plan.json", {}) or {}
    for s in plan.get("shots", []):
        if s["shot_number"] in ranked:
            (s.get("visual") or {}).pop("queries_stale", None)
        if s["shot_number"] in to_graphic:
            retype(s, to_graphic[s["shot_number"]])
    (session / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    graphics = {}
    if to_graphic:
        retyped = [s for s in plan.get("shots", []) if s["shot_number"] in to_graphic]
        progress = session / "plan_progress.jsonl"
        if progress.exists():
            lines = []
            for line in progress.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    lines.append(line)
                    continue
                if row.get("shot_number") in to_graphic:
                    retype(row, to_graphic[row["shot_number"]])
                lines.append(json.dumps(row, ensure_ascii=False))
            progress.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
        log(f"[autopick] {len(retyped)} shots become word-card graphics")
        graphics = make_graphics(session, retyped, log)
    missing = [s["shot_number"] for s in wanted if s["shot_number"] not in ranked
               and s["shot_number"] not in to_graphic and s["shot_number"] not in pending]
    rows = scorer._asset_rows(session)
    out = {"picked": picked, "lane": lane, "judge_cost_usd": round(judge_cost, 4), "no_candidates": missing,
           "short_clip": sorted(n for n, r in report.items() if r.get("short_clip")), "shots": report,
           "stock": {"budget": budget, "used": stock_used(rows, set()), "shots": len(plan.get("shots", [])),
                     "to_graphic": {str(n): r for n, r in sorted(to_graphic.items())}, **graphics},
           "chrome_pending": sorted(pending & set(manifests))}
    write_json(session / "autopick.json", {**(read_json(session / "autopick.json", {}) or {}), **{"last": out}})
    return out


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Pick each shot's asset automatically")
    ap.add_argument("--session", required=True)
    ap.add_argument("--shots", default="", help="comma-separated shot numbers (default: every shot)")
    ap.add_argument("--stale", action="store_true", help="only shots marked queries_stale")
    ap.add_argument("--per-source", type=int, default=2)
    ap.add_argument("--repicking", default="", help="shots a later chunk re-picks: their stock picks hold no budget slot")
    a = ap.parse_args()
    session = Path(a.session)
    shots = [int(x) for x in re.split(r"[,\s]+", a.shots) if x.strip()] or None
    if a.stale:
        shots = [s["shot_number"] for s in (read_json(session / "plan.json", {}) or {}).get("shots", [])
                 if (s.get("visual") or {}).get("queries_stale")]
    try:
        out = run(session, shots, a.per_source,
                  repicking={int(x) for x in re.split(r"[,\s]+", a.repicking) if x.strip()})
        print(json.dumps({"ok": True, "picked": out["picked"], "lane": out["lane"], "no_candidates": out["no_candidates"]}))
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
