"""Idea-first mapped plan: ideas before cuts (SPEC.md Part 10, ported from the M13/M14 replan.py in Part 12, F4).

    python tools/plan/ideas.py cut   --session sessions/<id>   # ideas.txt + slots.json -> ideas_skeleton.json
    python tools/plan/ideas.py build --session sessions/<id>   # + visuals.txt -> plan.json, plan_progress.jsonl

ideas.txt holds one visual idea per line, `@<the exact words>|<subject>`, in script order, covering every word.

cut: every idea boundary is a cut; a long idea is split at allowed word boundaries (never inside a word, a name or
a number) into shots near the inspo's local shot length, read from slots.json. A shot's ref is the slot under its
midpoint and its target the overlap-weighted share of the slots it covers: the plan skill's split (half the
target) and merge (sum of targets) rules, generalised.

build: visuals.txt gives each idea one line per shot it got, under `@<idea number>`:
    <type>|<spec>|<R>|<desc>|<field>|...
- type: F (REAL_FOOTAGE), I (REAL_IMAGE), G (MOTION_GRAPHICS), A (AI_VIDEO), or empty to route by the ref's
  material (tools/plan/lanes.py);
- spec: l / m / h specificity; R marks a reaction or meme beat (giphy is allowed only there);
- fields: `<source>:<query>;<query>` search sources, then up to three plain fields: caption, overlay, direction.
Every shot gets `visual.material` (from its ref) and `visual.lane`. A typed line whose lane can't make the ref's
material carries `visual.lane_fallback` with the reason, so the validator and review page show it.
"""

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.slots import boundaries, load_words, voice_end  # noqa: E402
from tools.match.validate_plan import protected_cut  # noqa: E402
from tools.plan import lanes  # noqa: E402

TYPE = {"F": "REAL_FOOTAGE", "I": "REAL_IMAGE", "G": "MOTION_GRAPHICS", "A": "AI_VIDEO"}
FADE = {"black": "fade_black", "white": "fade_white"}
SPEC = {"l": "low", "m": "medium", "h": "high"}
SOURCE = re.compile(r"(youtube|archive|giphy|pinterest|wikimedia|openverse|google_images):")
SHOT_COST = 0.03   # a small price per extra shot, so an idea is not split without reason
MIN_SHOT = 0.5


def tok(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ideas(session: Path) -> list[dict]:
    out = []
    for line in (session / "ideas.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("@"):
            phrase, subject = line[1:].rsplit("|", 1)
            out.append({"phrase": phrase.strip(), "subject": subject.strip()})
    return out


def align(ideas: list[dict], words: list[dict]) -> None:
    """Each idea's first and last word index. Raises at the first phrase that doesn't match the transcript."""
    wi = 0
    for k, idea in enumerate(ideas):
        first = None
        for t in [t for t in map(tok, idea["phrase"].split()) if t]:
            while wi < len(words) and not tok(words[wi]["word"]):
                wi += 1
            if wi >= len(words) or tok(words[wi]["word"]) != t:
                got = " ".join(w["word"] for w in words[max(0, wi - 3): wi + 6])
                raise ValueError(f"idea {k + 1} '{idea['phrase']}': expected '{t}', transcript has ...{got}...")
            first = wi if first is None else first
            wi += 1
        while wi < len(words) and not tok(words[wi]["word"]):  # "%" and the like belong to the word before
            wi += 1
        idea["w0"], idea["w1"] = first, wi - 1
    rest = [w["word"] for w in words[wi:] if tok(w["word"])]
    if rest:
        raise ValueError(f"transcript left after the last idea: {' '.join(rest[:12])}")


def cut(session: Path) -> dict:
    words = load_words(read(session / "timestamps.json"))
    slots = read(session / "slots.json")["slots"]
    end = voice_end(session, words)
    bnd = boundaries(words)  # bnd[i] sits between words i and i+1
    ideas = load_ideas(session)
    align(ideas, words)

    def slot_at(t):
        return next((s for s in slots if s["start"] <= t < s["end"]), slots[-1])

    def target(a, b):
        return sum((min(b, s["end"]) - max(a, s["start"])) / max(1e-6, s["end"] - s["start"]) * s["target_dur"]
                   for s in slots if min(b, s["end"]) > max(a, s["start"]))

    def cost(a, b):
        return math.log(max(b - a, 1e-3) / slot_at((a + b) / 2)["target_dur"]) ** 2 + (0 if b - a >= MIN_SHOT else 9)

    shots, warnings = [], []
    for k, idea in enumerate(ideas):
        a = 0.0 if k == 0 else ideas[k - 1]["end"]
        b = end if k == len(ideas) - 1 else bnd[idea["w1"]]
        idea["start"], idea["end"] = round(a, 3), round(b, 3)
        if k and (why := protected_cut(a, words)):
            warnings.append(f"idea {k + 1} starts at a protected cut: {why}")
        pts = [a] + [bnd[i] for i in range(idea["w0"], idea["w1"]) if not protected_cut(bnd[i], words)] + [b]
        best = {0: (0.0, [0])}
        for j in range(1, len(pts)):
            best[j] = min(((best[i][0] + cost(pts[i], pts[j]) + (SHOT_COST if i else 0), best[i][1] + [j])
                           for i in range(j)), key=lambda x: x[0])
        idx = best[len(pts) - 1][1]
        for step, (i, j) in enumerate(zip(idx, idx[1:]), 1):
            x, y = pts[i], pts[j]
            said = [w["word"] for w in words if x - 0.01 <= (w["start"] + w["end"]) / 2 <= y + 0.01]
            shots.append({"idea": str(k + 1), "step": step, "subject": idea["subject"], "start": round(x, 3),
                          "end": round(y, 3), "words": " ".join(said), "ref_shot": slot_at((x + y) / 2)["ref_shot"],
                          "target": round(target(x, y), 3)})
        idea["shots"] = len(idx) - 1
    (session / "ideas_skeleton.json").write_text(json.dumps(shots, indent=1, ensure_ascii=False), encoding="utf-8")
    durs = sorted(s["end"] - s["start"] for s in shots)
    return {"ideas": len(ideas), "shots": len(shots), "median": round(durs[len(durs) // 2], 2) if durs else 0,
            "split_ideas": [{"idea": k, "shots": i["shots"], "subject": i["subject"]}
                            for k, i in enumerate(ideas, 1) if i["shots"] > 1], "warnings": warnings}


def parse_sources(fields: list[str]) -> list[dict]:
    return [{"source": f.split(":", 1)[0], "queries": [q.strip() for q in f.split(":", 1)[1].split(";") if q.strip()]}
            for f in fields if ":" in f]


def default_sources(vtype: str, desc: str, subject: str, react: bool) -> list[dict]:
    """A query ladder on the type's non-stock sources, so a line without sources still passes the Part 9 rules."""
    words = " ".join(desc.split()[:5])
    if react:
        return [{"source": "giphy", "queries": [f"{subject} reaction", words]}]
    if vtype == "REAL_FOOTAGE":
        return [{"source": "youtube", "queries": [words, f"{subject} b roll"]}, {"source": "archive", "queries": [subject]}]
    if vtype == "REAL_IMAGE":
        return [{"source": "google_images", "queries": [words, subject]}, {"source": "wikimedia", "queries": [subject]}]
    return []


def visual_for(line: str, ref: dict, subject: str, licensing: str) -> tuple[dict, str, str]:
    """(visual, caption, overlay) for one visuals.txt line."""
    t, spec, react, desc, *rest = (line.split("|") + [""] * 8)
    srcs = [f for f in rest if SOURCE.match(f)]
    caption, overlay, direction = ([f for f in rest if f and f not in srcs] + ["", "", ""])[:3]
    routed = lanes.route(ref, licensing)
    react = react.strip().upper() == "R"
    if react and not desc.lower().startswith("reaction"):
        desc = "Reaction: " + desc
    visual = {"material": routed["material"], "lane": routed["lane"], "type": routed["type"]}
    if t.strip() in TYPE:
        visual["type"] = TYPE[t.strip()]
        if visual["type"] not in lanes.LANE_TYPES[visual["lane"]]:
            visual["lane"] = lanes.TYPE_LANE[visual["type"]]
        if why := lanes.lane_problem(visual):
            visual["lane_fallback"] = f"visuals.txt typed it {t.strip()}: {why}"
    if lanes.looks_generated(ref) and visual["type"] == "AI_VIDEO":
        visual["generate"] = {"preset": ref.get("ai_preset", "static")}
    elif visual["lane"] == "genimage":
        visual["generate"] = {"keyframe_only": visual["type"] != "AI_VIDEO", "preset": ref.get("ai_preset", "static")}
    sources = parse_sources(srcs) or default_sources(visual["type"], desc, subject, react)
    visual.update(specificity=SPEC.get(spec.strip(), "medium"), desc=desc, search_sources=sources,
                  search_query=sources[0]["queries"][0] if sources and sources[0]["queries"] else "", fx=[])
    if direction:
        visual["user_directions"] = [direction]
    return visual, caption, overlay


def build(session: Path) -> dict:
    skel = read(session / "ideas_skeleton.json")
    refs = read(session / "slots.json")["refs"]
    req = read(session / "requirements.json") if (session / "requirements.json").exists() else {}
    licensing = req.get("licensing") if req.get("licensing") in ("free_only", "fair_use_ok") else "fair_use_ok"
    vis, cur = {}, None
    for line in (session / "visuals.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("@"):
            cur = line[1:].split("|")[0].strip()
            vis[cur] = []
        elif cur is not None:
            vis[cur].append(line.strip())
    shots, problems = [], []
    for n, sk in enumerate(skel, 1):
        lines = vis.get(sk["idea"], [])
        if len(lines) < sk["step"]:
            problems.append(f"idea {sk['idea']} ({sk['subject']}) needs a visual for step {sk['step']}")
            continue
        r = refs.get(sk["ref_shot"], {})
        visual, caption, overlay = visual_for(lines[sk["step"] - 1], r, sk["subject"], licensing)
        shot = {"shot_number": n, "line_id": str(n), "start": sk["start"], "end": sk["end"],
                "start_est": sk["start"], "end_est": sk["end"], "audio": sk["words"], "visual": visual,
                "idea": {"id": sk["idea"], "step": sk["step"], "subject": sk["subject"]},
                "audio_layer": {"music": "", "sfx": []}, "transition": "cut",
                "ref_shot": sk["ref_shot"], "ref_target_dur": sk["target"]}
        if caption and r.get("text_extra") and visual["type"] != "MOTION_GRAPHICS":
            shot["text"] = {"caption": caption, "style": "bold_white", "pos": "center"}
        if overlay and visual["type"] != "MOTION_GRAPHICS":
            shot["overlay"] = {"desc": f"Card: {overlay}", "caption": overlay, "style": "label"}
        mo = r.get("motion") or {}
        if mo.get("move"):
            shot["camera"] = {"move": mo["move"], "amount": mo.get("amount", 0)}
        shot["transition_in"] = FADE.get(mo.get("fade_in"), "cut")
        shot["transition_out"] = FADE.get(mo.get("fade_out"), "cut")
        shots.append(shot)
    if problems:
        raise ValueError("\n".join(problems[:40]) + f"\n({len(problems)} missing)")
    extra = [f"idea {k} has {len(v)} visuals but only {sum(1 for s in skel if s['idea'] == k)} shots"
             for k, v in vis.items() if len(v) > sum(1 for s in skel if s["idea"] == k)]
    sa = read(session / "style_analysis.json") if (session / "style_analysis.json").exists() else {}
    plan = {"session_id": session.name,
            "video_metadata": {"title": req.get("topic", session.name), "duration_est": shots[-1]["end"] if shots else 0,
                               "style": sa.get("visual_style", ""), "shot_count": len(shots), "chunk_count": 1},
            "editing_notes": {"method": "inspo-mapped", "ideas": "idea-first (ideas.txt, visuals.txt, tools/plan/ideas.py)"},
            "shots": shots, "timing_source": "timestamps", "generated_at": datetime.now(timezone.utc).isoformat()}
    (session / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    (session / "plan_progress.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in shots),
                                                 encoding="utf-8")
    count = lambda key: {v: sum(1 for s in shots if s["visual"][key] == v) for v in {s["visual"][key] for s in shots}}  # noqa: E731
    return {"shots": len(shots), "types": count("type"), "lanes": count("lane"),
            "lane_fallbacks": sum(1 for s in shots if s["visual"].get("lane_fallback")),
            "captions": sum("text" in s for s in shots), "overlays": sum("overlay" in s for s in shots), "notes": extra}


def main() -> None:
    ap = argparse.ArgumentParser(description="Idea-first mapped plan")
    ap.add_argument("step", choices=["cut", "build"])
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    try:
        out = (cut if a.step == "cut" else build)(Path(a.session))
        print(json.dumps({"ok": True, **out}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
