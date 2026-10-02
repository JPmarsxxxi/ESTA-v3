"""Full match on the first minute of do-alphas-even-exist vs videoplayback (2).mp4, with the kind tag replaced
by describe + likely_sources. Everything else is score.py unchanged.

    python harness.py haiku|gemma
"""
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from tools.match import inspo, score  # noqa: E402
from tools.match.common import Embedder, read_json, write_json  # noqa: E402

OUT = Path(__file__).parent
SESSION = REPO / "sessions" / "do-alphas-even-exist-2026-09-29"
SRC = {"kind": "local", "ref": str(OUT / "inspo" / "videoplayback-2.mp4"), "source": "user_provided"}
FIRST = 60.0
STILL_SOURCES = {"pexels_image", "pixabay_image", "pinterest", "wikimedia", "google_images"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def kind_from_source(src: str) -> str:
    return "graphic" if src == "hyperframes" else "still" if src in STILL_SOURCES else "footage"


def our_source(shot: dict, asset: dict | None) -> str:
    """Final: where the placed file came from. Plan: the plan's lead search source."""
    if asset is not None:
        src = asset.get("source", "")
        if src in ("pexels", "pixabay"):
            return f"{src}_image" if Path(asset.get("file", "")).suffix.lower() in IMAGE_EXT else f"{src}_video"
        return src or "unknown"
    v = shot.get("visual") or {}
    if v.get("type") == "MOTION_GRAPHICS":
        return "hyperframes"
    if v.get("type") == "AI_VIDEO" or shot.get("generate"):
        return "ai_video"
    lead = ((v.get("search_sources") or [{}])[0] or {}).get("source", "")
    still = v.get("type") in ("STILL", "STILL_IMAGE", "IMAGE")
    if lead in ("pexels", "pixabay"):
        return f"{lead}_image" if still else f"{lead}_video"
    return lead or "unknown"


def answers(model: str) -> dict:
    if model == "haiku":
        return read_json(OUT / "haiku_results.json")["answers"]
    out = {}
    for k, text in (read_json(OUT / "gemma_job2" / "results.json") or {}).items():
        try:
            out[k] = json.loads(text[text.index("{"): text.rindex("}") + 1])
        except Exception:  # noqa: BLE001
            pass
    return out


def main() -> None:
    model = sys.argv[1]
    emb = Embedder()
    style = read_json(SESSION / "style_analysis.json", {}) or {}
    texts = [t for t in [style.get("shot_patterns", ""), style.get("visual_style", ""),
                         style.get("dominant_content_type", ""), " ".join(style.get("keywords") or [])] if t]
    base = inspo.build_profile(SRC, emb, texts)

    # Per-model profile copy: the shared cache keeps its geometry, each copy gets its own answers.
    prof_dir = OUT / f"profile_{model}"
    if prof_dir.exists():
        shutil.rmtree(prof_dir)
    shutil.copytree(base, prof_dir)
    prof = read_json(prof_dir / "profile.json")
    ans = answers(model)
    shots_meta = read_json(OUT / "shots.json")
    by_window = {round(s["start"], 3): s["id"] for s in shots_meta if s["side"] == "inspo"}
    tagged = 0
    for s in prof["shots"]:
        a = ans.get(by_window.get(round(s["start"], 3), ""))
        if not a or not a.get("likely_sources"):
            continue
        src = str(a["likely_sources"][0])
        s["tags"] = {"kind": kind_from_source(src), "source": src, "sources": a["likely_sources"],
                     "description": a.get("description", ""), "text_on_screen": bool(a.get("text_on_screen")),
                     "overlay_extra": bool(a.get("overlay_extra")), "overlay": bool(a.get("overlay_extra")),
                     "panels": 1, "clips_in_shot": 1}
        tagged += 1
    prof["tags_status"] = "done" if tagged == len(prof["shots"]) else "partial"
    write_json(prof_dir / "profile.json", prof)

    # Scratch session: our first minute only, same files otherwise.
    sess = OUT / f"session_{model}"
    if sess.exists():
        shutil.rmtree(sess)
    sess.mkdir()
    for n in ("assets.json", "assets_progress.jsonl", "timestamps.json", "match_grades.json", "style_analysis.json"):
        if (SESSION / n).exists():
            shutil.copy(SESSION / n, sess / n)
    plan = read_json(SESSION / "plan.json")
    plan["shots"] = [s for s in plan["shots"] if float(s.get("start", 0) or 0) < FIRST]
    write_json(sess / "plan.json", plan)
    write_json(sess / "inspo_profiles.json", {"profiles": [str(prof_dir)], "failed": []})

    patch()
    result = {"model": model, "inspo_shots": len(prof["shots"]), "tagged": tagged,
              "our_shots": len(plan["shots"])}
    if len(sys.argv) > 2 and sys.argv[2] == "nudge":
        from tools.match import adjust
        before = score.score(sess, "plan", force=True)
        rep = adjust.run(sess, "plan")
        result["plan_before"] = brief(before)
        result["plan_after"] = brief(rep)
        result["rounds"] = rep["adjust"]["rounds"]
        result["nudge_cost_usd"] = rep["adjust"]["cost_usd"]
        result["shots_after"] = [{"n": s["shot_number"], "start": s["start"], "end": s["end"], "audio": s.get("audio", ""),
                                  "type": (s.get("visual") or {}).get("type"), "desc": (s.get("visual") or {}).get("desc", ""),
                                  "sources": [e.get("source") for e in (s.get("visual") or {}).get("search_sources") or []],
                                  "refetch": bool((s.get("visual") or {}).get("queries_stale"))}
                                 for s in read_json(sess / "plan.json")["shots"]]
        print(score.summary(rep))
        write_json(OUT / f"nudge_{model}.json", result)
        return
    for stage in ("plan", "final"):
        rep = score.score(sess, stage, force=True)
        result[stage] = brief(rep)
        print(score.summary(rep))
    write_json(OUT / f"match_{model}.json", result)


def brief(rep: dict) -> dict:
    return {"overall": rep["overall"], "pass": rep["pass"],
            "sections": {k: {kk: vv for kk, vv in v.items() if kk != "least_on_theme"} for k, v in rep["sections"].items()}}


SOURCE_TYPE = {"hyperframes": "MOTION_GRAPHICS", **{s: "REAL_IMAGE" for s in STILL_SOURCES}}


PLAN_KIND = {"MOTION_GRAPHICS": "graphic", "REAL_IMAGE": "still"}
GUIDE_K = 5
EMB: dict = {}


def patch() -> None:
    """Scoring and adjust are score.py / adjust.py as-is (kind from the inspo's top source guess).
    The one addition: shots adjust rewrites take their lead search source from the nearest inspo shots."""
    from tools.match import adjust

    orig_fix_duration = adjust.fix_duration

    def fix_duration(session, rep, tasks):
        """After the splits: the half whose words fit the existing clip keeps it; the other refetches."""
        from tools.match.common import media_frames
        changes = orig_fix_duration(session, rep, tasks)
        firsts = [n for n, t in tasks.items() if t.get("why", "").startswith("split: first half")]
        if not firsts:
            return changes
        emb = EMB.setdefault("e", Embedder())
        assets = score._asset_rows(session)
        plan = adjust.load_plan(session)
        drop_rows = set()
        for a in firsts:
            b = a + 1
            sa, sb, asset = adjust.shot_by_n(plan, a), adjust.shot_by_n(plan, b), assets.get(str(a)) or {}
            f = Path(asset.get("file", ""))
            f = f if f.is_absolute() else REPO / f
            frames = media_frames(f, float(asset.get("in_point") or 0), float(asset.get("out_point") or 0), n=1) \
                if asset.get("ok") and f.exists() else []
            if not (sa and sb and frames):
                continue
            img = emb.siglip_images(frames)[0]
            sims = emb.siglip_texts([sa.get("audio", ""), sb.get("audio", "")]) @ img
            keep, drop = (sa, sb) if sims[0] >= sims[1] else (sb, sa)
            tasks.pop(keep["shot_number"], None)
            tasks[drop["shot_number"]] = {"task": "requery", "why": (
                "split: this half gets NEW footage for its own spoken words. The other half keeps the existing clip, "
                f"which shows: {keep['visual'].get('desc', '')}. Do not show that again.")}
            drop["visual"]["queries_stale"] = True
            drop_rows.add(drop["shot_number"])
            changes.append(f"shot {keep['shot_number']} keeps the clip (fit {max(sims):.3f} vs {min(sims):.3f}); "
                           f"shot {drop['shot_number']} refetches")
        adjust.save_plan(session, plan)
        if drop_rows:
            aj = read_json(session / "assets.json")
            for n in drop_rows:
                aj["shots"].pop(str(n), None)
            write_json(session / "assets.json", aj)
            feed = session / "assets_progress.jsonl"
            if feed.exists():
                keep_lines = [ln for ln in feed.read_text(encoding="utf-8").splitlines()
                              if ln.strip() and json.loads(ln).get("shot_number") not in drop_rows]
                feed.write_text("\n".join(keep_lines) + "\n", encoding="utf-8")
        return changes
    adjust.fix_duration = fix_duration

    orig_wording = adjust.write_wording

    def write_wording(session, tasks, stage):
        out, cost = orig_wording(session, tasks, stage)
        if not tasks:
            return out, cost
        insp = score.load_inspo(session)
        emb = EMB.setdefault("e", Embedder())
        plan = adjust.load_plan(session)
        guided = []
        for n in tasks:
            s = adjust.shot_by_n(plan, n)
            if not s or s.get("locked") or (s.get("visual") or {}).get("queries_pinned"):
                continue
            v = s["visual"]
            kind = PLAN_KIND.get(v.get("type"), "footage")
            idx = [i for i, t in enumerate(insp["shots"]) if (t.get("tags") or {}).get("kind") == kind]
            if not idx or kind == "graphic":  # graphics are generated, not searched
                continue
            vec = emb.siglip_texts([f"{s.get('audio', '')} {v.get('desc', '')}"])[0]
            sims = insp["siglip"][idx] @ vec
            near = [insp["shots"][idx[int(i)]]["tags"]["sources"] for i in sims.argsort()[::-1][:GUIDE_K]]
            votes: dict = {}
            for srcs in near:
                for rank, src in enumerate(srcs):
                    if kind_from_source(src) == kind:
                        votes[src] = votes.get(src, 0) + 1 / (rank + 1)
            if not votes:
                continue
            want = max(votes, key=votes.get)
            ss = v.get("search_sources") or []
            lead = next((e for e in ss if e.get("source") == want), None)
            if lead is None:
                lead = {"source": want, "queries": list((ss[0] if ss else {}).get("queries") or [v.get("desc", "")[:40]])}
            if ss and ss[0] is lead:
                continue
            v["search_sources"] = [lead] + [e for e in ss if e is not lead]
            v["search_query"] = (lead.get("queries") or [""])[0]
            guided.append(f"shot {n} leads with {want}")
        adjust.save_plan(session, plan)
        return out + ([f"guided: {'; '.join(guided)}"] if guided else []), cost
    adjust.write_wording = write_wording

    orig_run = adjust.subprocess.run

    def run(cmd, *a, **kw):
        # Same lean flags as the describe lane: no MCP tools or skills in each call.
        if isinstance(cmd, list) and cmd and "claude" in Path(str(cmd[0])).name.lower():
            cmd = [*cmd, "--strict-mcp-config", "--setting-sources", "", "--tools", ""]
        return orig_run(cmd, *a, **kw)
    adjust.subprocess.run = run


if __name__ == "__main__":
    main()
