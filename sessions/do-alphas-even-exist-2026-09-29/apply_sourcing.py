"""Apply sourcing.txt to plan.json (SPEC.md Part 9): per-shot specificity, a query ladder per source written in that
source's terms, and Giphy only on reaction beats (their desc gets a "Reaction:" lead). Cuts, refs, captions,
overlays, graphics and user_directions are untouched. Prints the audit the plan skill's rules call for."""
import json
import sys
from collections import Counter
from pathlib import Path

S = Path(__file__).resolve().parent
ROOT = S.parents[1]
sys.path.insert(0, str(ROOT))
from tools.match.adjust import sync_progress  # noqa: E402

rows = {}
for line in (S / "sourcing.txt").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    n, spec, react, *srcs = line.split("|")
    rows[int(n)] = (spec, react == "R", [(s.split(":", 1)[0], [q.strip() for q in s.split(":", 1)[1].split(";") if q.strip()])
                                       for s in srcs if s])

plan = json.loads((S / "plan.json").read_text(encoding="utf-8"))
changed = []
for s in plan["shots"]:
    v = s["visual"]
    if v["type"] == "MOTION_GRAPHICS":
        continue
    spec, react, srcs = rows[s["shot_number"]]
    v["specificity"] = spec
    v["search_sources"] = [{"source": src, "queries": qs} for src, qs in srcs]
    v["search_query"] = srcs[0][1][0]
    if react and not v["desc"].lower().startswith("reaction"):
        v["desc"] = "Reaction: " + v["desc"]
    v["queries_stale"] = True
    changed.append(s["shot_number"])
missing = [s["shot_number"] for s in plan["shots"] if s["visual"]["type"] != "MOTION_GRAPHICS" and s["shot_number"] not in rows]
assert not missing, missing
(S / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
sync_progress(S)

f = [s for s in plan["shots"] if s["visual"]["type"] != "MOTION_GRAPHICS"]
lead = Counter(s["visual"]["search_sources"][0]["source"] for s in f)
print(json.dumps({
    "shots_resourced": len(changed),
    "specificity": dict(Counter(s["visual"]["specificity"] for s in f)),
    "lead_source": dict(lead),
    "lead_ladder_min": min(len(s["visual"]["search_sources"][0]["queries"]) for s in f),
    "one_query_everywhere": sum(1 for s in f if len({q for e in s["visual"]["search_sources"] for q in e["queries"]}) == 1),
    "giphy_shots": sum(1 for s in f if any(e["source"] == "giphy" for e in s["visual"]["search_sources"])),
    "reaction_beats": sum(1 for s in f if s["visual"]["desc"].lower().startswith("reaction")),
}, indent=1))
