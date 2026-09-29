"""Auto-pick: choose each shot's asset the way the user would in the picker.

    python tools/match/autopick.py --session sessions/<id> [--shots 3,7,12] [--per-source 2]

1. Gathers candidates per shot (`assets/run.py candidates`, the picker's path).
2. Ranks them locally: SigLIP 2 fit to the shot's desc and spoken line, plus
   DINOv3 closeness to the inspo's keyframes, minus a penalty for reusing a
   file another shot already shows.
3. Sends each shot's top three to Gemma 4 on Kaggle in one batch to pick the
   best and reject unusable ones (watermarks, wrong subject, junk).
4. Writes the pick to assets_progress.jsonl (visual_verdict "auto_picked") and
   assets.json, and clears the shot's queries_stale.

Without Kaggle the local ranking decides, and the report says so.
"""

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match import score as scorer  # noqa: E402
from tools.match import vlm_kaggle  # noqa: E402
from tools.match.common import (  # noqa: E402
    REPO_ROOT, media_frames, read_json, run_esta, save_jpg, utf8_stdout, write_json,
)

JOBS_DIR = REPO_ROOT / "cache" / "vlm_jobs"
FINALISTS = 3

PICK_PROMPT = (
    "You pick stock footage for one shot of a YouTube video, the way its creator would. "
    "The images are candidate clips, numbered 1 to {k} in order.\n"
    "Shot description: {desc}\nSpoken line over it: {audio}\nThe creator's style: {style}\n"
    "Reject a candidate if it has a visible watermark or logo, shows the wrong subject, "
    "is blurry or broken, or is off-tone for the line. Reply with ONLY a JSON object: "
    '{{"best": <number>, "reject": [<numbers>], "why": "<one short reason>"}}'
)


def log(m: str) -> None:
    print(m, flush=True)


def _gather(session: Path, n: int, per_source: int) -> dict:
    r = run_esta(["tools/assets/run.py", "candidates", "--session", str(session), "--n", str(n),
                  "--per-source", str(per_source), "--max-queries", "1"], timeout=2400)
    return read_json(session / "assets" / "candidates" / f"shot_{n}.json", {}) or {"candidates": [], "error": r.stderr[-200:]}


def _style_line(session: Path) -> str:
    s = read_json(session / "style_analysis.json", {}) or {}
    return "; ".join(str(x) for x in (s.get("visual_style"), s.get("dominant_content_type"),
                                      ", ".join(s.get("keywords") or [])) if x)[:400]


def run(session: Path, shots: list[int] | None = None, per_source: int = 2, log=log) -> dict:
    import numpy as np
    from tools.match.common import Embedder
    plan = read_json(session / "plan.json", {}) or {}
    mg = {str(s.get("key")) for s in (read_json(session / "motion_graphics.json", {}) or {}).get("slots", []) if s.get("ok")}
    wanted = [s for s in plan.get("shots", []) if (shots is None or s["shot_number"] in shots)
              and str(s["shot_number"]) not in mg and not s.get("locked_asset")]
    log(f"[autopick] gathering candidates for {len(wanted)} shots")
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifests = dict(zip([s["shot_number"] for s in wanted],
                             pool.map(lambda s: _gather(session, s["shot_number"], per_source), wanted)))

    inspo = scorer.load_inspo(session)
    emb = Embedder()
    feed_rows = scorer._asset_rows(session)
    used = {Path(str(r.get("file", ""))).name for k, r in feed_rows.items()
            if r.get("ok") and not (k.isdigit() and int(k) in manifests)}
    job = JOBS_DIR / ("pick-" + session.name[:30] + "-" + hashlib.sha1(json.dumps(sorted(manifests)).encode()).hexdigest()[:8])
    (job / "images").mkdir(parents=True, exist_ok=True)
    style = _style_line(session)
    ranked, requests = {}, []
    for s in wanted:
        n = s["shot_number"]
        cands = [c for c in manifests[n].get("candidates", []) if Path(REPO_ROOT / c["file"]).exists() or Path(c["file"]).exists()]
        if not cands:
            continue
        rows = []
        for c in cands:
            path = Path(c["file"]) if Path(c["file"]).is_absolute() else REPO_ROOT / c["file"]
            try:
                frames = media_frames(path, c.get("in_point") or 0, c.get("out_point") or 0)
            except Exception:
                frames = []
            if frames:
                rows.append((c, frames))
        if not rows:
            continue
        v = s.get("visual") or {}
        text = emb.siglip_texts([f"{v.get('desc', '')}. {s.get('audio', '')}"[:300]])[0]
        mids = [f[len(f) // 2] for _, f in rows]
        fit = emb.siglip_images(mids) @ text
        look = (emb.dino(mids) @ inspo["dino"].T).max(axis=1) if inspo else np.zeros(len(rows))
        z = lambda x: (x - x.mean()) / (x.std() + 1e-6) if len(x) > 1 else x * 0  # noqa: E731
        reuse = np.array([1.0 if Path(c["file"]).name in used else 0.0 for c, _ in rows])
        total = 0.6 * z(fit) + 0.4 * z(look) - 1.0 * reuse
        order = list(np.argsort(-total))
        ranked[n] = [(rows[i][0], float(total[i]), float(fit[i]), float(look[i])) for i in order]
        finals = order[:FINALISTS]
        if len(finals) > 1:
            names = []
            for j, i in enumerate(finals):
                name = f"s{n}_{j + 1}.jpg"
                save_jpg(mids[i], job / "images" / name, max_side=512)
                names.append(name)
            requests.append({"id": str(n), "images": names, "max_new_tokens": 120,
                             "prompt": PICK_PROMPT.format(k=len(names), desc=v.get("desc", ""), audio=s.get("audio", ""),
                                                          style=style)})

    verdicts, lane = {}, "local ranking"
    if requests:
        write_json(job / "requests.json", {"model": "gemma4-e4b", "requests": requests})
        try:
            vlm_kaggle.run(job, log=log)
            for sid, text in (read_json(job / "results.json", {}) or {}).items():
                try:
                    verdicts[int(sid)] = json.loads(text[text.index("{"): text.rindex("}") + 1])
                except Exception:
                    pass
            lane = "gemma4-e4b on Kaggle"
        except Exception as e:  # noqa: BLE001 - Kaggle down: the local ranking stands
            log(f"[autopick] Kaggle unavailable, using local ranking: {e}")

    feed = session / "assets_progress.jsonl"
    picked, report = 0, {}
    with open(feed, "a", encoding="utf-8") as fh:
        for n, cands in ranked.items():
            choice, why = cands[0], "local rank"
            vd = verdicts.get(n)
            if vd:
                reject = {int(x) for x in vd.get("reject") or [] if str(x).isdigit()}
                best = int(vd.get("best") or 1) if str(vd.get("best", "")).isdigit() else 1
                finals = cands[:FINALISTS]
                if 1 <= best <= len(finals) and best not in reject:
                    choice, why = finals[best - 1], f"gemma: {vd.get('why', '')}"[:200]
                else:
                    keep = [c for j, c in enumerate(finals, 1) if j not in reject]
                    choice, why = (keep[0] if keep else finals[0]), f"gemma rejected its pick; next best ({vd.get('why', '')})"[:200]
            c, total, fit, look = choice
            row = {"shot_number": n, "ok": True, "source": c["source"], "asset_type": c["asset_type"],
                   "url": c.get("url", ""), "file": c["file"], "search_query": c.get("query", ""),
                   "in_point": c.get("in_point", 0), "out_point": c.get("out_point", 0),
                   "visual_verdict": "auto_picked", "visual_confidence": int(max(0, min(100, 50 + 20 * total))),
                   "error": ""}
            fh.write(json.dumps(row) + "\n")
            report[n] = {"file": Path(c["file"]).name, "why": why, "fit": round(fit, 3), "look": round(look, 3),
                         "of": len(cands)}
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
    (session / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    missing = [s["shot_number"] for s in wanted if s["shot_number"] not in ranked]
    out = {"picked": picked, "lane": lane, "no_candidates": missing, "shots": report}
    write_json(session / "autopick.json", {**(read_json(session / "autopick.json", {}) or {}), **{"last": out}})
    return out


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Pick each shot's asset automatically")
    ap.add_argument("--session", required=True)
    ap.add_argument("--shots", default="", help="comma-separated shot numbers (default: every shot)")
    ap.add_argument("--stale", action="store_true", help="only shots marked queries_stale")
    ap.add_argument("--per-source", type=int, default=2)
    a = ap.parse_args()
    session = Path(a.session)
    shots = [int(x) for x in re.split(r"[,\s]+", a.shots) if x.strip()] or None
    if a.stale:
        shots = [s["shot_number"] for s in (read_json(session / "plan.json", {}) or {}).get("shots", [])
                 if (s.get("visual") or {}).get("queries_stale")]
    try:
        out = run(session, shots, a.per_source)
        print(json.dumps({"ok": True, "picked": out["picked"], "lane": out["lane"], "no_candidates": out["no_candidates"]}))
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
