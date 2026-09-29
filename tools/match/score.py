"""Similarity of a session's plan or final edit to its inspo, in five sections.

    python tools/match/score.py --session sessions/<id> --stage plan|final [--round N] [--note "..."]

Writes match_plan.json / match_final.json: per-section score, pass and the
measured numbers behind it, the overall score, per-shot detail for adjust,
and a history of every score. Formulas are SPEC.md Part 2, "Scoring formulas".
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import (  # noqa: E402
    COLOUR_FEATURES, REPO_ROOT, colour_features, kind_group, match_config, media_frames, plan_kind,
    read_json, save_jpg, utf8_stdout, write_json,
)

COLOUR_FLOOR = {"L_mean": 5.0, "L_std": 3.0, "chroma": 3.0, "a_mean": 2.0, "b_mean": 2.0, "colourfulness": 5.0}
RATE_FLOOR = {"overlay": 0.05, "text": 0.05, "panels": 1.0, "clips": 1.0, "variety": 0.5}
SECTIONS = ["a", "b", "c", "d", "e"]
NAMES = {"a": "Asset distribution", "b": "Colour and grading", "c": "Thematic adherence",
         "d": "Complexity", "e": "Shot duration"}


def report_path(session: Path, stage: str) -> Path:
    return session / f"match_{stage}.json"


def grade_key(asset: dict) -> str:
    """Grades follow the clip (file and in point), so they survive renumbering."""
    return f"{Path(str(asset.get('file', '')).replace(chr(92), '/')).name}|{float(asset.get('in') or 0):.2f}"


# ── Inspo target ─────────────────────────────────────────────────────────────

def load_inspo(session: Path):
    import numpy as np
    idx = read_json(session / "inspo_profiles.json", {}) or {}
    shots, dino, sig, calib, notes = [], [], [], [], []
    for rel in idx.get("profiles", []):
        d = REPO_ROOT / rel
        prof = read_json(d / "profile.json")
        if not prof:
            continue
        emb = np.load(d / "embeddings.npz")
        shots += prof["shots"]
        dino.append(emb["dino"])
        sig.append(emb["siglip"])
        calib.append(prof["calibration"])
        if prof.get("tags_status") != "done":
            notes.append(f"{prof['source']['ref']}: tags {prof.get('tags_status')} {prof.get('tags_error', '')}".strip())
        if prof["duration"] < 30:
            notes.append(f"{prof['source']['ref']}: under 30 s, thin profile")
    for f in idx.get("failed", []):
        notes.append(f"{f['ref']}: could not be profiled ({f['error'][:120]})")
    if not shots:
        return None
    avg = lambda key, sub: sum(c[key][sub] for c in calib) / len(calib)  # noqa: E731
    return {
        "shots": shots,
        "dino": np.concatenate(dino), "siglip": np.concatenate(sig),
        "calib": {"dino": {"lo": avg("dino", "lo"), "hi": avg("dino", "hi")},
                  "siglip_text": {"lo": avg("siglip_text", "lo"), "hi": avg("siglip_text", "hi")}},
        "tagged": all("tags" in s for s in shots),
        "notes": notes,
    }


# ── Our shots ────────────────────────────────────────────────────────────────

def _asset_rows(session: Path) -> dict:
    rows = {str(k): v for k, v in ((read_json(session / "assets.json", {}) or {}).get("shots") or {}).items()}
    feed = session / "assets_progress.jsonl"
    if feed.exists():
        for line in feed.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("shot_number") is not None:
                rows[str(r["shot_number"])] = r
    return rows


def our_shots(session: Path, stage: str, classes: int) -> list[dict]:
    plan = read_json(session / "plan.json", {}) or {}
    subs = (session / "timestamps.json").exists()
    assets = _asset_rows(session) if stage == "final" else {}
    out = []
    for s in plan.get("shots", []):
        start = float(s.get("start", s.get("start_est", 0)) or 0)
        end = float(s.get("end", s.get("end_est", start)) or start)
        v = s.get("visual") or {}
        comp = (s.get("composite") or {}).get("slots") or []
        row = {
            "n": s.get("shot_number"), "id": s.get("line_id") or str(s.get("shot_number")),
            "locked": bool(s.get("locked")), "dur": max(end - start, 0.0), "start": start,
            "type": v.get("type", ""), "kind": plan_kind(s, classes),
            "overlay": bool(s.get("overlay")),
            "text": bool((s.get("text") or {}).get("caption")) or subs or v.get("type") == "MOTION_GRAPHICS",
            "panels": min(len(comp), 3) if comp else 1, "clips": 1,
            "desc": v.get("desc", ""), "queries": [q for e in v.get("search_sources") or [] for q in e.get("queries") or []],
            "audio": s.get("audio", ""),
        }
        if stage == "final":
            a = assets.get(str(row["n"])) or {}
            row["asset"] = {"file": a.get("file", ""), "in": float(a.get("in_point") or 0),
                            "out": float(a.get("out_point") or 0), "ok": bool(a.get("ok")), "source": a.get("source", "")}
        out.append(row)
    return out


def _asset_features(session: Path, shots: list[dict], emb) -> None:
    """Colour, embeddings and a keyframe per final shot, cached by (file, in, out)."""
    import numpy as np
    cache_dir = session / "assets" / "match_features"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for s in shots:
        a = s["asset"]
        path = REPO_ROOT / a["file"] if a["file"] and not Path(a["file"]).is_absolute() else Path(a["file"] or "")
        if not a["ok"] or not a["file"] or not path.exists():
            s["features"] = None
            continue
        key = hashlib.sha1(f"{a['file']}|{a['in']:.2f}|{a['out']:.2f}".encode()).hexdigest()[:16]
        npz, meta = cache_dir / f"{key}.npz", cache_dir / f"{key}.json"
        if not npz.exists():
            frames = media_frames(path, a["in"], a["out"] or a["in"] + s["dur"])
            if not frames:
                s["features"] = None
                continue
            save_jpg(frames[len(frames) // 2], cache_dir / f"{key}.jpg")
            np.savez_compressed(npz, dino=emb.dino(frames).mean(axis=0), siglip=emb.siglip_images([frames[len(frames) // 2]])[0])
            write_json(meta, {"colour": colour_features(frames)})
        e = np.load(npz)
        s["features"] = {"key": key, "keyframe": str(cache_dir / f"{key}.jpg"), "colour": read_json(meta)["colour"],
                         "dino": e["dino"], "siglip": e["siglip"]}


# ── Sections ─────────────────────────────────────────────────────────────────

def _shares(items: list[tuple[str, float]]) -> dict:
    total = sum(w for _, w in items) or 1.0
    out: dict = {}
    for k, w in items:
        out[k] = out.get(k, 0.0) + w / total
    return {k: round(v, 4) for k, v in out.items()}


def section_a(ours, inspo, classes, stage):
    if not inspo["tagged"]:
        return None, "pending: Kaggle tags for the inspo"
    mine = _shares([(s["final_kind"] if stage == "final" else s["kind"], s["dur"]) for s in ours])
    theirs = _shares([(kind_group(t["tags"]["kind"], classes), t["dur"]) for t in inspo["shots"] if "tags" in t])
    tvd = 0.5 * sum(abs(mine.get(k, 0) - theirs.get(k, 0)) for k in set(mine) | set(theirs))
    return {"score": round(100 * (1 - tvd), 1), "ours": mine, "inspo": theirs,
            "gap": {k: round(mine.get(k, 0) - theirs.get(k, 0), 4) for k in set(mine) | set(theirs)}}, ""


def _wasserstein(u, uw, v, vw):
    from scipy.stats import wasserstein_distance
    return float(wasserstein_distance(u, v, uw, vw))


def _iqr(vals):
    q = statistics.quantiles(vals, n=4) if len(vals) > 1 else [vals[0]] * 3
    return q[2] - q[0]


def section_b(ours, inspo):
    rows = [s for s in ours if s.get("features")]
    if not rows:
        return None, "no downloaded media to measure"
    per, detail = [], {}
    for f in COLOUR_FEATURES:
        u = [s["features"]["colour"][f] for s in rows]
        v = [t["colour"][f] for t in inspo["shots"]]
        dist = _wasserstein(u, [s["dur"] or 0.01 for s in rows], v, [t["dur"] or 0.01 for t in inspo["shots"]])
        norm = dist / max(_iqr(v), COLOUR_FLOOR[f])
        per.append(norm)
        detail[f] = {"ours_median": round(statistics.median(u), 2), "inspo_median": round(statistics.median(v), 2),
                     "distance": round(norm, 3)}
    return {"score": round(100 * math.exp(-sum(per) / len(per)), 1), "features": detail}, ""


def _calibrate(x, c):
    return max(0.0, min(100.0, 100 * (x - c["lo"]) / max(c["hi"] - c["lo"], 1e-6)))


def section_c(ours, inspo, stage, emb):
    import numpy as np
    if stage == "plan":
        texts = [f"{s['desc']}. {' '.join(s['queries'][:3])}".strip(". ") or s["audio"] for s in ours]
        vec = emb.siglip_texts(texts)
        sims = (vec @ inspo["siglip"].T).max(axis=1)
        calib = inspo["calib"]["siglip_text"]
    else:
        rows = [s for s in ours if s.get("features")]
        if not rows:
            return None, "no downloaded media to measure"
        vec = np.stack([s["features"]["dino"] for s in ours if s.get("features")])
        sims = (vec @ inspo["dino"].T).max(axis=1)
        calib = inspo["calib"]["dino"]
    measured = [s for s in ours if stage == "plan" or s.get("features")]
    for s, x in zip(measured, sims):
        s["theme"] = round(_calibrate(float(x), calib), 1)
    total = sum(s["dur"] for s in measured) or 1.0
    score = sum(s["theme"] * s["dur"] for s in measured) / total
    return {"score": round(score, 1), "estimate": stage == "plan",
            "least_on_theme": [s["n"] for s in sorted(measured, key=lambda s: s["theme"])[:10]]}, ""


def _variety(rows, key):
    """Distinct kinds per minute, averaged over one-minute windows."""
    if not rows:
        return 0.0
    t, buckets = 0.0, {}
    for r in rows:
        buckets.setdefault(int(t // 60), set()).add(r[key])
        t += r["dur"]
    return statistics.mean(len(b) for b in buckets.values())


def section_d(ours, inspo, stage, classes, dropped):
    if not inspo["tagged"]:
        return None, "pending: Kaggle tags for the inspo"
    it = [t for t in inspo["shots"] if "tags" in t]
    tot_i = sum(t["dur"] for t in it) or 1.0
    tot_o = sum(s["dur"] for s in ours) or 1.0
    kind_key = "final_kind" if stage == "final" else "kind"
    rates = {
        "overlay": (sum(s["dur"] for s in ours if s["overlay"]) / tot_o,
                    sum(t["dur"] for t in it if t["tags"].get("overlay_extra", t["tags"]["overlay"])) / tot_i),
        "text": (sum(s["dur"] for s in ours if s["text"]) / tot_o,
                 sum(t["dur"] for t in it if t["tags"]["text_on_screen"]) / tot_i),
        "panels": (statistics.mean(s["panels"] for s in ours), statistics.mean(t["tags"]["panels"] for t in it)),
        "clips": (statistics.mean(s["clips"] for s in ours), statistics.mean(t["tags"]["clips_in_shot"] for t in it)),
        "variety": (_variety(ours, kind_key),
                    _variety([{"dur": t["dur"], "k": kind_group(t["tags"]["kind"], classes)} for t in it], "k")),
    }
    skip = {"panels": "panels" in dropped, "clips": "clips_in_shot" in dropped}
    subs, detail = [], {}
    for k, (o, i) in rates.items():
        if skip.get(k):
            continue
        sub = 100 * (1 - min(1.0, abs(o - i) / max(i, RATE_FLOOR[k])))
        subs.append(sub)
        detail[k] = {"ours": round(o, 3), "inspo": round(i, 3), "score": round(sub, 1)}
    return {"score": round(statistics.mean(subs), 1), "rates": detail,
            "excluded": [k for k, v in skip.items() if v]}, ""


def section_e(ours, inspo):
    o = [s["dur"] for s in ours if s["dur"] > 0]
    i = [t["dur"] for t in inspo["shots"]]
    if not o:
        return None, "no shots"
    om, imn = statistics.mean(o), statistics.mean(i)
    omed, imed = statistics.median(o), statistics.median(i)
    sub = lambda a, b: 100 * max(0.0, 1 - abs(a - b) / b)  # noqa: E731
    return {"score": round((sub(om, imn) + sub(omed, imed)) / 2, 1),
            "mean": {"ours": round(om, 2), "inspo": round(imn, 2)},
            "median": {"ours": round(omed, 2), "inspo": round(imed, 2)}}, ""


# ── Report ───────────────────────────────────────────────────────────────────

def _inputs_hash(session: Path, stage: str) -> str:
    h = hashlib.sha1()
    names = ["plan.json", "inspo_profiles.json"] + (["assets.json", "assets_progress.jsonl", "match_grades.json"] if stage == "final" else [])
    for n in names:
        p = session / n
        h.update(p.read_bytes() if p.exists() else b"-")
    h.update(json.dumps(match_config(), sort_keys=True).encode())
    return h.hexdigest()[:16]


def score(session: Path, stage: str, round_no: int | None = None, note: str = "", force: bool = False,
          log=print) -> dict:
    cfg = match_config()
    classes = int(cfg.get("kind_classes", 4))
    dropped = set(cfg.get("dropped_tags") or [])
    prev = read_json(report_path(session, stage), {}) or {}
    ih = _inputs_hash(session, stage)
    if not force and prev.get("inputs_hash") == ih and prev.get("sections"):
        return prev

    inspo = load_inspo(session)
    if inspo is None:
        raise RuntimeError("no inspo profile; run `python tools/match/inspo.py profile --session ...` first")
    ours = our_shots(session, stage, classes)
    from tools.match.common import Embedder
    emb = Embedder()
    if stage == "final":
        _asset_features(session, ours, emb)
        from tools.match.tag import tag_frames
        frames = {str(s["n"]): Path(s["features"]["keyframe"]) for s in ours if s.get("features")}
        tagged = {}
        try:
            tagged = tag_frames(frames, f"final-{session.name}-{ih[:6]}", log=log) if frames else {}
        except Exception as e:  # noqa: BLE001 - Kaggle down: tag-dependent sections go pending
            log(f"[score] tagging failed: {e}")
        grades = read_json(session / "match_grades.json", {}) or {}
        for s in ours:
            t = tagged.get(str(s["n"]))
            s["final_kind"] = kind_group(t["kind"], classes) if t else s["kind"]
            if t:
                s["overlay"] = s["overlay"] or t.get("overlay_extra", False)
                s["text"] = s["text"] or t["text_on_screen"]
            s["tagged"] = bool(t)
            # A grade applied at Build moves the shot's colour toward the target;
            # measure what will be exported, not the raw download.
            g = (grades.get("clips") or {}).get(grade_key(s["asset"]))
            if g and s.get("features"):
                s["features"]["colour"] = {**s["features"]["colour"], **g.get("expected", {})}
        if frames and not tagged:
            inspo["tagged"] = False

    sections, notes = {}, {}
    fns = {
        "a": lambda: section_a(ours, inspo, classes, stage),
        "b": lambda: section_b(ours, inspo) if stage == "final" else (None, "n/a at plan: colour needs real media"),
        "c": lambda: section_c(ours, inspo, stage, emb),
        "d": lambda: section_d(ours, inspo, stage, classes, dropped),
        "e": lambda: section_e(ours, inspo),
    }
    for k in SECTIONS:
        res, why = fns[k]()
        if res is None:
            sections[k] = {"name": NAMES[k], "score": None, "pass": None, "note": why}
        else:
            res["pass"] = res["score"] >= cfg["pass_section"]
            sections[k] = {"name": NAMES[k], **res, "note": why}
    weights = cfg["weights"]
    scored = {k: v for k, v in sections.items() if v["score"] is not None}
    wsum = sum(weights[k] for k in scored) or 1
    overall = round(sum(v["score"] * weights[k] for k, v in scored.items()) / wsum, 1)
    passed = overall >= cfg["pass_overall"] and all(v["pass"] for v in scored.values())

    plan = read_json(session / "plan.json", {}) or {}
    for s in ours:
        if s.get("features"):
            s["colour"] = s["features"]["colour"]
            s["keyframe"] = s["features"]["keyframe"]
            del s["features"]
    locked = [s["n"] for s in ours if s["locked"]]
    history = prev.get("history", [])
    history.append({"at": datetime.now(timezone.utc).isoformat(), "round": round_no, "overall": overall,
                    "sections": {k: v["score"] for k, v in sections.items()}, "note": note})
    report = {
        "session": session.name, "stage": stage, "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs_hash": ih, "overall": overall, "pass": passed,
        "pass_marks": {"overall": cfg["pass_overall"], "section": cfg["pass_section"]}, "weights": weights,
        "kind_classes": classes, "excluded_tags": sorted(dropped),
        "timing": plan.get("timing_source", "estimated"), "sections": sections,
        "notes": inspo["notes"], "locked": locked, "shots": ours, "history": history[-60:],
    }
    write_json(report_path(session, stage), report)
    return report


def summary(report: dict) -> str:
    parts = [f"{k} {v['score'] if v['score'] is not None else 'n/a'}" for k, v in report["sections"].items()]
    return f"{report['stage']}: overall {report['overall']} ({'PASS' if report['pass'] else 'fail'}) | " + ", ".join(parts)


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Score a session against its inspo")
    ap.add_argument("--session", required=True)
    ap.add_argument("--stage", required=True, choices=["plan", "final"])
    ap.add_argument("--round", type=int)
    ap.add_argument("--note", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    try:
        rep = score(Path(a.session), a.stage, a.round, a.note, a.force, log=lambda m: print(m, flush=True))
        print(summary(rep), flush=True)
        print(json.dumps({"ok": True, "overall": rep["overall"], "pass": rep["pass"],
                          "sections": {k: v["score"] for k, v in rep["sections"].items()}}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
