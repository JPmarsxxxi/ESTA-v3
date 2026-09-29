"""Targeted auto-adjust: nudge only the failing sections, re-score, repeat until pass.

    python tools/match/adjust.py --session sessions/<id> --stage plan|final

Each round fixes the failing sections in structure-first order (e duration,
a asset mix, d complexity, c theme, b colour), then re-scores. A round that
doesn't raise the overall score by `min_gain`, or drops a passing section below
its mark, is reverted and the loop stops; otherwise it runs until pass or
`max_rounds`. Locked (hand-edited) shots are never touched.

Deterministic choices use the inspo's own embeddings; wording (new descs,
queries, overlay captions) is one batched Haiku call per round.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match import score as scorer  # noqa: E402
from tools.match.common import (  # noqa: E402
    COLOUR_FEATURES, REPO_ROOT, kind_group, match_config, read_json, run_esta, utf8_stdout, write_json,
)
from tools.plan import ops  # noqa: E402

KIND_TYPE = {"footage": "REAL_FOOTAGE", "still": "REAL_IMAGE", "graphic": "MOTION_GRAPHICS", "meme": "REAL_FOOTAGE"}
RETYPE_NOTE = {
    "footage": "The desc must describe real camera footage (people, places, reactions, objects), never a terminal, chart, UI or text card.",
    "still": "The desc must describe a real photo or painting, never a terminal, chart, UI or text card.",
    "graphic": "The desc must describe a generated graphic in the inspo's grammar (terminal card, chart, stat card).",
    "meme": "A meme or reaction clip: the desc names the reaction, and giphy leads the sources.",
}
NUMBER = re.compile(r"\d")
GRAPHIC_DESC = re.compile(r"terminal|monospace|amber|shell|command line|text card|stat card|\bchart|dashboard|heatmap|\bui\b", re.I)
BACKED_UP = ["plan.json", "plan_progress.jsonl", "assets_progress.jsonl", "assets.json", "match_grades.json"]

# The planner's requery rules (server/planner.ts REQUERY_SYSTEM), extended to a batch.
WRITER_SYSTEM = (
    "You rewrite shots of a video plan so the edit follows the creator's inspo video. "
    "Output ONLY a JSON object {\"shots\": [{\"n\": <shot number>, \"desc\": \"...\", "
    "\"search_sources\": [{\"source\": \"<name>\", \"queries\": [\"...\"]}], \"caption\": \"...\"}]}, "
    "one entry per task, same n. Include caption only when the task asks for an overlay caption "
    "(2-4 words, ALL CAPS, the number or punchline of the spoken line).\n"
    "desc: what the shot shows, concrete, in the inspo's visual grammar (given below). Never change the spoken line.\n"
    "search_sources rules: specificity=high must lead with youtube or wikimedia; medium mixes youtube/archive "
    "with pexels/pixabay; low leads with pexels/pixabay/giphy. REAL_FOOTAGE high: [youtube, archive]; "
    "REAL_IMAGE high: [google_images, wikimedia]; REAL_FOOTAGE low/medium: [pexels_video, pixabay_video, archive]; "
    "REAL_IMAGE low/medium: [pexels_image, pixabay_image, pinterest, wikimedia]; MOTION_GRAPHICS: [giphy, pixabay_image]. "
    "A meme/reaction shot leads with giphy. 2-3 sources best-first, 1-3 queries each, 3-5 words, concrete nouns."
)


def log(msg: str) -> None:
    print(msg, flush=True)


# ── Snapshots ────────────────────────────────────────────────────────────────

def snapshot(session: Path, tag: str) -> Path:
    d = session / "match_backup" / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for n in BACKED_UP:
        if (session / n).exists():
            shutil.copy(session / n, d / n)
    (d / "present.json").write_text(json.dumps([n for n in BACKED_UP if (session / n).exists()]), encoding="utf-8")
    return d


def restore(session: Path, d: Path) -> None:
    present = set(json.loads((d / "present.json").read_text(encoding="utf-8")))
    for n in BACKED_UP:
        if n in present:
            shutil.copy(d / n, session / n)
        elif (session / n).exists():
            (session / n).unlink()


# ── Plan helpers ─────────────────────────────────────────────────────────────

def load_plan(session: Path) -> dict:
    return json.loads((session / "plan.json").read_text(encoding="utf-8"))


def save_plan(session: Path, plan: dict) -> None:
    (session / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")


def shot_by_n(plan: dict, n: int) -> dict | None:
    return next((s for s in plan["shots"] if s.get("shot_number") == n), None)


def _norm(w: str) -> str:
    return "".join(c for c in str(w).lower() if c.isalnum())


def split_word(session: Path, shot: dict) -> str | None:
    """A word near the middle of the shot that ops.split will resolve to that exact position."""
    ts = read_json(session / "timestamps.json", {}) or {}
    words = ops._words_in(ts, float(shot["start"]), float(shot["end"]))
    if len(words) < 4:
        return None
    mid = (float(shot["start"]) + float(shot["end"])) / 2
    order = sorted(range(1, len(words)), key=lambda i: abs(float(words[i].get("start", 0)) - mid))
    for i in order:
        w = _norm(words[i].get("word", ""))
        if not w or i < 2 or i > len(words) - 2:
            continue
        if all(_norm(words[j].get("word", "")) != w for j in range(i)):
            return words[i].get("word", "").strip(" ,.!?\"'")
    return None


# ── Section fixes ────────────────────────────────────────────────────────────

def fix_duration(session: Path, rep: dict, tasks: dict) -> list[str]:
    e = rep["sections"]["e"]
    target_mean, target_med = e["mean"]["inspo"], e["median"]["inspo"]
    plan = load_plan(session)
    shots = plan["shots"]
    total = sum(float(s["end"]) - float(s["start"]) for s in shots)
    want = total / target_mean
    changes = []
    if e["mean"]["ours"] > target_mean or e["median"]["ours"] > target_med:
        need = max(1, round(0.7 * (want - len(shots))))
        cands = sorted([s for s in shots if not s.get("locked") and float(s["end"]) - float(s["start"]) > 1.6 * target_med],
                       key=lambda s: float(s["start"]) - float(s["end"]))
        # Split from the end backwards so earlier shot numbers stay valid.
        picked = sorted(cands[:need], key=lambda s: -s["shot_number"])
        for s in picked:
            word = split_word(session, s)
            if not word:
                continue
            res = ops.split(session, s["shot_number"], word)
            if res.get("ok"):
                a, b = res["into"]
                # Shots after the split moved up by one, and so do their tasks.
                for k in sorted([k for k in tasks if k > a], reverse=True):
                    tasks[k + 1] = tasks.pop(k)
                half = " The desc must show what this half's own spoken words say; the two halves must not show the same thing."
                tasks[a] = {"task": "requery", "why": "split: first half." + half}
                tasks[b] = {"task": "requery", "why": "split: second half." + half}
                changes.append(f"split shot {s['shot_number']} at '{word}'")
    else:
        need = max(1, round(0.7 * (len(shots) - want)))
        i, merged = len(shots) - 2, 0
        while i >= 0 and merged < need:
            a, b = shots[i], shots[i + 1]
            da, db = float(a["end"]) - float(a["start"]), float(b["end"]) - float(b["start"])
            same = (a.get("visual") or {}).get("type") == (b.get("visual") or {}).get("type")
            if not a.get("locked") and not b.get("locked") and da < target_med and db < target_med and same \
                    and da + db <= 1.5 * target_mean:
                res = ops.merge(session, [a["shot_number"], b["shot_number"]])
                if res.get("ok"):
                    changes.append(f"merged shots {a['shot_number']}+{b['shot_number']}")
                    merged += 1
                    shots = load_plan(session)["shots"]
                    i -= 1
            i -= 1
    return changes


def _inspo_kind_vectors(session: Path, classes: int):
    import numpy as np
    inspo = scorer.load_inspo(session)
    groups: dict = {}
    for i, s in enumerate(inspo["shots"]):
        if "tags" in s:
            groups.setdefault(kind_group(s["tags"]["kind"], classes), []).append(i)
    return {k: inspo["siglip"][idx] for k, idx in groups.items()}, np


def fix_mix(session: Path, rep: dict, tasks: dict, emb) -> list[str]:
    a = rep["sections"]["a"]
    classes = rep["kind_classes"]
    kind_key = "final_kind" if rep["stage"] == "final" else "kind"
    gap = a["gap"]
    under = [k for k, g in sorted(gap.items(), key=lambda x: x[1]) if g < -0.03]
    over = {k for k, g in gap.items() if g > 0.03}
    if not under or not over:
        return []
    vecs, np = _inspo_kind_vectors(session, classes)
    total = sum(s["dur"] for s in rep["shots"])
    # A spoken line that carries numbers is data, and data belongs on a graphic:
    # retyping it to footage leaves stock search hunting for a chart.
    cands = [s for s in rep["shots"] if not s["locked"] and s[kind_key] in over and s["n"] not in tasks
             and s["panels"] == 1 and not (s[kind_key] == "graphic" and NUMBER.search(s["audio"]))]
    if not cands:
        return []
    text = emb.siglip_texts([f"{s['audio']} {s['desc']}" for s in cands])
    changes = []
    used = set()
    plan = load_plan(session)
    for kind in under:
        if kind not in vecs:
            continue
        need = -gap[kind] * total * 0.8
        fit = (text @ vecs[kind].T).max(axis=1)
        cur = np.array([(text[i:i + 1] @ vecs[c[kind_key]].T).max() if c[kind_key] in vecs else 0.0
                        for i, c in enumerate(cands)])
        order = np.argsort(-(fit - cur))
        got = 0.0
        for i in order:
            s = cands[int(i)]
            if s["n"] in used or got >= need:
                continue
            shot = shot_by_n(plan, s["n"])
            shot["visual"]["type"] = KIND_TYPE[kind]
            used.add(s["n"])
            got += s["dur"]
            tasks[s["n"]] = {"task": "retype", "why": f"retyped {s[kind_key]} -> {kind}. " + RETYPE_NOTE[kind]}
            changes.append(f"retyped shot {s['n']} {s[kind_key]} -> {kind}")
    save_plan(session, plan)
    return changes


def fix_complexity(session: Path, rep: dict, tasks: dict) -> list[str]:
    rates = rep["sections"]["d"]["rates"]
    changes = []
    ov = rates.get("overlay")
    if ov and ov["score"] < rep["pass_marks"]["section"]:
        plan = load_plan(session)
        n = len(plan["shots"])
        delta = round((ov["inspo"] - ov["ours"]) * n)
        pool = [s for s in plan["shots"] if not s.get("locked") and (s.get("visual") or {}).get("type") != "MOTION_GRAPHICS"]
        numeric = lambda s: (bool(NUMBER.search(s.get("audio", ""))), float(s["end"]) - float(s["start"]))  # noqa: E731
        if delta > 0:
            for s in sorted([s for s in pool if not s.get("overlay")], key=numeric, reverse=True)[:delta]:
                s["overlay"] = {"caption": "", "desc": "", "style": "kinetic_text"}
                tasks.setdefault(s["shot_number"], {"task": "caption", "why": "overlay added"})["caption"] = True
                changes.append(f"overlay on shot {s['shot_number']}")
        elif delta < 0:
            for s in sorted([s for s in pool if s.get("overlay")], key=numeric)[:-delta]:
                s.pop("overlay", None)
                changes.append(f"removed overlay from shot {s['shot_number']}")
        save_plan(session, plan)
    for k in ("text", "variety"):
        r = rates.get(k)
        if r and r["score"] < rep["pass_marks"]["section"]:
            changes.append(f"note: {k} rate {r['ours']} vs inspo {r['inspo']} has no direct lever"
                           + (" (captions come from subtitles)" if k == "text" else " (moves with the asset mix)"))
    return changes


def fix_theme(session: Path, rep: dict, tasks: dict) -> list[str]:
    worst = [s for s in sorted(rep["shots"], key=lambda s: s.get("theme", 100))
             if not s["locked"] and s["n"] not in tasks and s.get("theme", 100) < rep["pass_marks"]["section"]][:12]
    for s in worst:
        tasks[s["n"]] = {"task": "retheme", "why": f"off the inspo's look (theme {s.get('theme')})"}
    return [f"rethemed shot {s['n']}" for s in worst]


def fix_colour(session: Path, rep: dict) -> list[str]:
    import statistics
    from tools.match.common import media_frames
    from tools.match.grade import fit_grade
    inspo = scorer.load_inspo(session)
    # Grades apply to footage and stills, so their target is the inspo's picture
    # shots: black-field graphics and flash frames would pull everything dark.
    pics = [t for t in inspo["shots"] if t["colour"]["L_mean"] > 8
            and kind_group((t.get("tags") or {}).get("kind", "footage"), rep["kind_classes"]) != "graphic"] or inspo["shots"]
    target = {k: statistics.median(t["colour"][k] for t in pics) for k in COLOUR_FEATURES}
    scale = {k: max(scorer._iqr([t["colour"][k] for t in pics]), scorer.COLOUR_FLOOR[k]) for k in COLOUR_FEATURES}
    grades = read_json(session / "match_grades.json", {}) or {}
    clips = grades.setdefault("clips", {})
    changes = []
    for s in rep["shots"]:
        a = s.get("asset") or {}
        if s["locked"] or not a.get("ok") or s.get("final_kind", s["kind"]) == "graphic" or not s.get("colour"):
            continue
        key = scorer.grade_key(a)
        dist = sum(abs(s["colour"][k] - target[k]) / scale[k] for k in COLOUR_FEATURES) / len(COLOUR_FEATURES)
        if dist < 0.5 or key in clips:
            continue
        path = Path(a["file"]) if Path(a["file"]).is_absolute() else REPO_ROOT / a["file"]
        frames = media_frames(path, a["in"], a["out"] or a["in"] + s["dur"])
        if not frames:
            continue
        grade, expected, before = fit_grade(frames, target, scale)
        clips[key] = {"shot": s["n"], "grade": grade, "expected": expected, "before": before}
        changes.append(f"graded shot {s['n']}")
    write_json(session / "match_grades.json", grades)
    return changes


# ── Wording (one Haiku call per round) ───────────────────────────────────────

def claude_bin() -> str:
    for p in (os.environ.get("CLAUDE_BIN"), os.environ.get("CLAUDE_CODE_EXECPATH"),
              str(Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")):
        if p and Path(p).exists():
            return p
    return "claude"


def write_wording(session: Path, tasks: dict, stage: str) -> tuple[list[str], float]:
    if not tasks:
        return [], 0.0
    plan = load_plan(session)
    style = read_json(session / "style_analysis.json", {}) or {}
    grammar = {k: style.get(k) for k in ("visual_style", "dominant_content_type", "shot_patterns", "keywords")}
    items = []
    for n, t in sorted(tasks.items()):
        s = shot_by_n(plan, n)
        if not s:
            continue
        v = s.get("visual") or {}
        items.append({"n": n, "task": t["task"], "why": t["why"], "spoken": s.get("audio", ""), "type": v.get("type"),
                      "specificity": v.get("specificity", "medium"), "desc": v.get("desc", ""),
                      "queries_pinned": bool(v.get("queries_pinned")), "needs_caption": bool(t.get("caption"))})
    def ask(chunk):
        prompt = (f"INSPO GRAMMAR:\n{json.dumps(grammar, ensure_ascii=False)}\n\nTASKS (requery = new queries for this "
                  f"shot's spoken line; retype = new type, rewrite desc and queries for it; retheme = rewrite desc and "
                  f"queries to sit in the inspo's grammar; when queries_pinned is true keep the queries and only write "
                  f"desc/caption):\n{json.dumps(chunk, ensure_ascii=False)}\n\nReturn ONLY the JSON object.")
        r = subprocess.run([claude_bin(), "-p", prompt, "--system-prompt", WRITER_SYSTEM, "--model",
                            "claude-haiku-4-5-20251001", "--output-format", "json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=REPO_ROOT, timeout=900)
        try:
            env = json.loads(r.stdout)
            raw = re.sub(r"```json\s*|\s*```", "", str(env.get("result", ""))).strip()
            return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])["shots"], float(env.get("total_cost_usd") or 0), ""
        except Exception as e:  # noqa: BLE001 - these shots keep their old wording
            return [], 0.0, f"{e}; {(r.stderr or r.stdout)[-160:]}"

    # Chunks keep each answer well inside Haiku's output limit.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        answers = list(pool.map(ask, [items[i:i + 30] for i in range(0, len(items), 30)]))
    out = [o for a in answers for o in a[0]]
    cost = sum(a[1] for a in answers)
    errors = [a[2] for a in answers if a[2]]
    if not out:
        return [f"note: wording failed ({errors[0] if errors else 'empty answer'})"], cost
    plan = load_plan(session)
    has_asset = set(scorer._asset_rows(session)) if stage == "final" else set()
    changed = []
    for o in out:
        s = shot_by_n(plan, int(o.get("n", -1)))
        if not s or s.get("locked"):
            continue
        v = s.setdefault("visual", {})
        if o.get("desc"):
            v["desc"] = str(o["desc"])
        if isinstance(o.get("search_sources"), list) and o["search_sources"] and not v.get("queries_pinned"):
            v["search_sources"] = o["search_sources"]
            v["search_query"] = (o["search_sources"][0].get("queries") or [""])[0]
            if str(s["shot_number"]) in has_asset:
                v["queries_stale"] = True
        if s.get("overlay") is not None and o.get("caption"):
            s["overlay"]["caption"] = str(o["caption"])
            s["overlay"]["desc"] = s["overlay"]["desc"] or str(o["caption"])
        changed.append(s["shot_number"])
    # The model sometimes keeps a graphic's description through a retype to
    # footage; stock search can't film a terminal card, so undo those retypes.
    for n, t in tasks.items():
        s = shot_by_n(plan, n)
        if t["task"] == "retype" and s and s["visual"].get("type") != "MOTION_GRAPHICS" and GRAPHIC_DESC.search(s["visual"].get("desc", "")):
            s["visual"]["type"] = "MOTION_GRAPHICS"
            changed.append(f"kept shot {n} a graphic (its desc still describes one)")
    # Overlays whose caption never arrived would render empty; drop them.
    for s in plan["shots"]:
        if s.get("overlay") is not None and not s["overlay"].get("caption"):
            s.pop("overlay")
    save_plan(session, plan)
    kept = [c for c in changed if isinstance(c, str)]
    return [f"reworded {len(changed) - len(kept)} shots"] + kept + [f"note: a wording batch failed ({e[:120]})" for e in errors], cost


# ── Final-stage follow-through ───────────────────────────────────────────────

def refresh_final(session: Path) -> list[str]:
    """Refetch stale shots through auto-pick, then re-render."""
    from tools.match import autopick
    stale = [s["shot_number"] for s in load_plan(session)["shots"] if (s.get("visual") or {}).get("queries_stale")]
    notes = []
    if stale:
        res = autopick.run(session, stale, log=log)
        notes.append(f"refetched {res.get('picked', 0)} of {len(stale)} stale shots")
    r = run_esta(["tools/render/run.py", "build", "--session", str(session)], timeout=1800)
    notes.append("re-rendered" if r.returncode == 0 else f"render failed: {(r.stderr or r.stdout)[-200:]}")
    return notes


def sync_progress(session: Path) -> None:
    """The assets fetch reads plan_progress.jsonl before plan.json, so after
    structural edits it must hold the adjusted shots, not the originals."""
    shots = load_plan(session)["shots"]
    (session / "plan_progress.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in shots),
                                                 encoding="utf-8")


# ── Loop ─────────────────────────────────────────────────────────────────────

def run(session: Path, stage: str) -> dict:
    cfg = match_config()
    rep = scorer.score(session, stage, round_no=0, note="before adjust", log=log)
    log(scorer.summary(rep))
    from tools.match.common import Embedder
    emb = Embedder()
    total_cost = 0.0
    rounds = []
    for rnd in range(1, int(cfg["max_rounds"]) + 1):
        if rep["pass"]:
            break
        failing = [k for k in ("e", "a", "d", "c", "b") if rep["sections"][k]["pass"] is False]
        if not failing:
            log("nothing scoreable is failing (pending sections cannot be adjusted)")
            break
        backup = snapshot(session, f"{stage}-round-{rnd}")
        tasks: dict = {}
        changes = []
        for k in failing:
            if k == "e":
                changes += fix_duration(session, rep, tasks)
                # Structure first: splits and merges renumber shots, so the other
                # fixes wait for the next round's fresh report.
                if changes:
                    break
            elif k == "a":
                changes += fix_mix(session, rep, tasks, emb)
            elif k == "d":
                changes += fix_complexity(session, rep, tasks)
            elif k == "c":
                changes += fix_theme(session, rep, tasks)
            elif k == "b" and stage == "final":
                changes += fix_colour(session, rep)
        words, cost = write_wording(session, tasks, stage)
        total_cost += cost
        changes += words
        if stage == "plan":
            sync_progress(session)
        if stage == "final" and any(not c.startswith(("graded", "note")) for c in changes):
            changes += refresh_final(session)
        real = [c for c in changes if not c.startswith("note")]
        if not real:
            log(f"round {rnd}: nothing to change ({'; '.join(changes) or 'all candidate shots locked'})")
            rounds.append({"round": rnd, "changes": changes, "kept": False})
            break
        new = scorer.score(session, stage, round_no=rnd, note="; ".join(real[:20]), force=True, log=log)
        dropped = [k for k in new["sections"] if rep["sections"][k]["pass"] and new["sections"][k]["pass"] is False]
        gained = new["overall"] - rep["overall"]
        log(f"round {rnd}: {len(real)} changes, overall {rep['overall']} -> {new['overall']}")
        if gained < cfg["min_gain"] or dropped:
            why = f"reverted: overall {gained:+.1f}" + (f", {','.join(dropped)} fell below its mark" if dropped else "")
            restore(session, backup)
            if stage == "final":
                refresh_final(session)
            rep = scorer.score(session, stage, round_no=rnd, note=why, force=True, log=log)
            rounds.append({"round": rnd, "changes": real, "kept": False, "why": why})
            log(why)
            break
        rounds.append({"round": rnd, "changes": real, "kept": True, "gain": round(gained, 1)})
        rep = new
    rep = read_json(scorer.report_path(session, stage))
    rep["adjust"] = {"rounds": rounds, "cost_usd": round(total_cost, 4), "passed": rep["pass"]}
    write_json(scorer.report_path(session, stage), rep)
    return rep


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Nudge a session toward its inspo until it passes")
    ap.add_argument("--session", required=True)
    ap.add_argument("--stage", required=True, choices=["plan", "final"])
    a = ap.parse_args()
    try:
        rep = run(Path(a.session), a.stage)
        log(scorer.summary(rep))
        print(json.dumps({"ok": True, "overall": rep["overall"], "pass": rep["pass"], "rounds": len(rep["adjust"]["rounds"])}))
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
