"""M13 replan (SPEC.md Part 10): ideas before cuts.

    python sessions/do-alphas-even-exist-2026-09-29/replan.py cut     # ideas.txt -> skeleton_m13.json + shot counts per idea
    python sessions/do-alphas-even-exist-2026-09-29/replan.py build   # + visuals.txt -> plan.json / plan_progress.jsonl

cut: every idea boundary is a cut; a long idea is split at allowed word boundaries (never inside a word, a name
or a number) into shots near the inspo's local shot length, read from slots.json. A shot's ref is the slot under
its midpoint and its target the overlap-weighted share of the slots it covers: the plan skill's split (half the
target) and merge (sum of targets) rules, generalised.
build: visuals.txt gives each idea one visual line per shot it got (type|spec|R|desc|caption|overlay|direction|
sources, or =<old shot> to reuse that shot's visual and sourcing from the pre-M13 plan).
"""
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("C:/Users/User/ESTA-v3")
S = ROOT / "sessions" / sys.argv[2]
sys.path.insert(0, str(ROOT))
from tools.match.slots import boundaries, load_words, voice_end  # noqa: E402
from tools.match.validate_plan import protected_cut  # noqa: E402

TYPE = {"F": "REAL_FOOTAGE", "I": "REAL_IMAGE", "G": "MOTION_GRAPHICS"}
KIND = {"footage": "REAL_FOOTAGE", "still": "REAL_IMAGE", "graphic": "MOTION_GRAPHICS", "ai": "REAL_FOOTAGE"}
FADE = {"black": "fade_black", "white": "fade_white"}
SPEC = {"l": "low", "m": "medium", "h": "high"}
SHOT_COST = float(__import__("os").environ.get("SHOT_COST", "0.03"))


def tok(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def load_ideas() -> list[dict]:
    out = []
    for line in (S / "ideas.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("@"):
            phrase, subject = line[1:].rsplit("|", 1)
            out.append({"phrase": phrase.strip(), "subject": subject.strip()})
    return out


def align(ideas, words):
    """Each idea's first and last word index; stops at the first phrase that doesn't match the transcript."""
    wi = 0
    for k, idea in enumerate(ideas):
        want = [t for t in map(tok, idea["phrase"].split()) if t]
        first = None
        for t in want:
            while wi < len(words) and not tok(words[wi]["word"]):
                wi += 1
            if wi >= len(words) or tok(words[wi]["word"]) != t:
                got = " ".join(w["word"] for w in words[max(0, wi - 3): wi + 6])
                sys.exit(f"idea {k + 1} '{idea['phrase']}': expected '{t}', transcript has ...{got}...")
            first = wi if first is None else first
            wi += 1
        while wi < len(words) and not tok(words[wi]["word"]):  # "%" and the like belong to the word before
            wi += 1
        idea["w0"], idea["w1"] = first, wi - 1
    rest = [w["word"] for w in words[wi:] if tok(w["word"])]
    if rest:
        sys.exit(f"transcript left after the last idea: {' '.join(rest[:12])}")


def cut():
    words = load_words(json.loads((S / "timestamps.json").read_text(encoding="utf-8")))
    slots = json.loads((S / "slots.json").read_text(encoding="utf-8"))["slots"]
    end = voice_end(S, words)
    bnd = boundaries(words)  # bnd[i] sits between words i and i+1
    ideas = load_ideas()
    align(ideas, words)

    def slot_at(t):
        return next((s for s in slots if s["start"] <= t < s["end"]), slots[-1])

    def target(a, b):
        tot = 0.0
        for s in slots:
            ov = min(b, s["end"]) - max(a, s["start"])
            if ov > 0:
                tot += ov / max(1e-6, s["end"] - s["start"]) * s["target_dur"]
        return tot

    def cost(a, b):
        want = target(a, b) / max(1e-6, (b - a)) * (b - a)  # the inspo shots' summed length over this span
        local = slot_at((a + b) / 2)["target_dur"]
        return math.log(max(b - a, 1e-3) / local) ** 2 + (0 if b - a >= 0.5 else 9) + 0 * want

    shots = []
    for k, idea in enumerate(ideas):
        a = 0.0 if k == 0 else ideas[k - 1]["end"]
        b = end if k == len(ideas) - 1 else bnd[idea["w1"]]
        idea["start"], idea["end"] = round(a, 3), round(b, 3)
        if k and (why := protected_cut(a, words)):
            print(f"warning: idea {k + 1} starts at a protected cut: {why}")
        inner = [bnd[i] for i in range(idea["w0"], idea["w1"]) if not protected_cut(bnd[i], words)]
        pts = [a] + inner + [b]
        best = {0: (0.0, [0])}
        for j in range(1, len(pts)):
            best[j] = min(((best[i][0] + cost(pts[i], pts[j]) + (SHOT_COST if i else 0), best[i][1] + [j])
                           for i in range(j)), key=lambda x: x[0])
        idx = best[len(pts) - 1][1]
        for step, (i, j) in enumerate(zip(idx, idx[1:]), 1):
            x, y = pts[i], pts[j]
            ws = [w["word"] for w in words if x - 0.01 <= (w["start"] + w["end"]) / 2 <= y + 0.01]
            sl = slot_at((x + y) / 2)
            shots.append({"idea": f"{k + 1}", "step": step, "subject": idea["subject"], "start": round(x, 3),
                          "end": round(y, 3), "words": " ".join(ws), "ref_shot": sl["ref_shot"],
                          "target": round(target(x, y), 3)})
        idea["shots"] = len(idx) - 1
    (S / "skeleton_m13.json").write_text(json.dumps(shots, indent=1, ensure_ascii=False), encoding="utf-8")
    durs = sorted(s["end"] - s["start"] for s in shots)
    print(f"{len(ideas)} ideas -> {len(shots)} shots; median {durs[len(durs) // 2]:.2f} s, "
          f"min {durs[0]:.2f}, max {durs[-1]:.2f}; ideas with 2+ shots: {sum(i['shots'] > 1 for i in ideas)}")
    for k, i in enumerate(ideas, 1):
        if len(sys.argv) > 3 or i["shots"] > 1:
            print(f"{k}|{i['shots']}|{i['end'] - i['start']:.1f}s|{i['subject']}|{i['phrase'][:70]}")


def old_rows():
    plan = json.loads((S / "backup_m12_claude" / "plan.json").read_text(encoding="utf-8"))["shots"]
    src = {}
    for line in (S / "sourcing.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            n, spec, react, *rest = line.split("|")
            src[int(n)] = (spec, react, [x for x in rest if x])
    return {s["shot_number"]: s for s in plan}, src


def parse_sources(fields):
    return [{"source": f.split(":", 1)[0], "queries": [q.strip() for q in f.split(":", 1)[1].split(";") if q.strip()]}
            for f in fields if ":" in f]


def build():
    skel = json.loads((S / "skeleton_m13.json").read_text(encoding="utf-8"))
    refs = json.loads((S / "slots.json").read_text(encoding="utf-8"))["refs"]
    vis, cur = {}, None
    for line in (S / "visuals.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("@"):
            cur = line[1:].split("|")[0].strip()
            vis[cur] = []
        else:
            vis[cur].append(line.strip())
    shots, problems = [], []
    for n, sk in enumerate(skel, 1):
        lines = vis.get(sk["idea"], [])
        if len(lines) < sk["step"]:
            problems.append(f"idea {sk['idea']} ({sk['subject']}) needs a visual for step {sk['step']}")
            continue
        line, r = lines[sk["step"] - 1], refs[sk["ref_shot"]]
        if True:
            t, spec, react, desc, *rest = (line.split("|") + [""] * 8)
            srcs = [f for f in rest if re.match(r"(youtube|archive|giphy|pinterest|wikimedia|openverse|google_images):", f)]
            caption, overlay, direction = ([f for f in rest if f not in srcs] + ["", "", ""])[:3]
            vtype = TYPE.get(t) or KIND.get(r["kind"], "REAL_FOOTAGE")
            if react == "R" and not desc.lower().startswith("reaction"):
                desc = "Reaction: " + desc
            sources = parse_sources(srcs) or [{"source": "giphy", "queries": [desc[:40]]}]
            visual = {"type": vtype, "specificity": SPEC.get(spec, "medium"), "search_sources": sources, "desc": desc,
                      "search_query": sources[0]["queries"][0], "fx": []}
            if direction:
                visual["user_directions"] = [direction]
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
    extra = [f"idea {k} has {len(v)} visuals but only {sum(1 for s in skel if s['idea'] == k)} shots"
             for k, v in vis.items() if len(v) > sum(1 for s in skel if s["idea"] == k)]
    if problems:
        sys.exit("\n".join(problems[:40]) + f"\n({len(problems)} missing)")
    for e in extra:
        print("note:", e)
    req = json.loads((S / "requirements.json").read_text(encoding="utf-8"))
    sa = json.loads((S / "style_analysis.json").read_text(encoding="utf-8"))
    plan = {"session_id": S.name, "video_metadata": {"title": req["topic"], "duration_est": shots[-1]["end"],
            "style": sa["visual_style"], "shot_count": len(shots), "chunk_count": 1}, "editing_notes": {}}
    plan.update(shots=shots, timing_source="timestamps", generated_at=datetime.now(timezone.utc).isoformat())
    plan.setdefault("editing_notes", {})["method"] = "inspo-mapped"
    plan["editing_notes"]["ideas"] = "idea-first (ideas.txt, visuals.txt, D:/esta-perf/m14t/replan.py)"
    (S / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    (S / "plan_progress.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in shots), encoding="utf-8")
    types = {t: sum(1 for s in shots if s["visual"]["type"] == t) for t in TYPE.values()}
    print(len(shots), "shots", types, "captions", sum("text" in s for s in shots),
          "overlays", sum("overlay" in s for s in shots))


if __name__ == "__main__":
    {"cut": cut, "build": build}[sys.argv[1]]()
