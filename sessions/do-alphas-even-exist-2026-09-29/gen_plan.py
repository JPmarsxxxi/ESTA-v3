"""plan.json from skeleton.json (the mapped cut) and plan_content.txt (per-shot content written as the plan skill),
following the plan skill's mapped-mode rules: type from the ref unless overridden, captions only where the ref has
text_extra, overlays only where it has overlay_extra and the shot is not a graphic, camera and fades from the ref."""
import json
from datetime import datetime, timezone
from pathlib import Path

S = Path(__file__).parent
TYPE = {"F": "REAL_FOOTAGE", "I": "REAL_IMAGE", "G": "MOTION_GRAPHICS"}
KIND = {"footage": "REAL_FOOTAGE", "still": "REAL_IMAGE", "graphic": "MOTION_GRAPHICS", "ai": "REAL_FOOTAGE"}
FADE = {"black": "fade_black", "white": "fade_white"}
MEME = ("meme", "reaction")


def sources(vtype: str, spec: str, query: str, desc: str) -> list[dict]:
    if vtype == "MOTION_GRAPHICS":
        names = ["giphy", "pixabay_image"]
    elif vtype == "REAL_IMAGE":
        names = ["google_images", "wikimedia"] if spec == "high" else ["pexels_image", "pixabay_image", "pinterest"]
    else:
        names = (["youtube", "archive"] if spec == "high" else
                 ["pexels_video", "youtube", "archive"] if spec == "medium" else
                 ["pexels_video", "pixabay_video"])
    if any(m in desc.lower() for m in MEME):
        names = ["giphy"] + [n for n in names if n != "giphy"]
    return [{"source": n, "queries": [query]} for n in names]


skeleton = json.loads((S / "skeleton.json").read_text(encoding="utf-8"))
refs = json.loads((S / "slots.json").read_text(encoding="utf-8"))["refs"]
content = {}
for line in (S / "plan_content.txt").read_text(encoding="utf-8").splitlines():
    if not line[:1].isdigit():
        continue
    sid, t, spec, query, desc, caption, overlay, direction = (line.split("|") + [""] * 8)[:8]
    content[sid] = dict(t=t, spec={"l": "low", "m": "medium", "h": "high"}[spec], query=query, desc=desc,
                        caption=caption, overlay=overlay, direction=direction)

shots = []
for n, sk in enumerate(skeleton, 1):
    c, r = content[sk["id"]], refs[sk["ref_shot"]]
    vtype = TYPE.get(c["t"]) or KIND.get(r["kind"], "REAL_FOOTAGE")
    visual = {"type": vtype, "specificity": c["spec"], "search_sources": sources(vtype, c["spec"], c["query"], c["desc"]),
              "desc": c["desc"], "search_query": c["query"], "fx": []}
    if c["direction"]:
        visual["user_directions"] = [c["direction"]]
    shot = {"shot_number": n, "line_id": sk["id"], "start": sk["start"], "end": sk["end"],
            "start_est": sk["start"], "end_est": sk["end"], "audio": sk["words"], "visual": visual,
            "audio_layer": {"music": "", "sfx": []}, "transition": "cut",
            "ref_shot": sk["ref_shot"], "ref_target_dur": sk["target"]}
    if c["caption"] and r.get("text_extra") and vtype != "MOTION_GRAPHICS":
        shot["text"] = {"caption": c["caption"], "style": "bold_white", "pos": "center"}
    if c["overlay"] and r.get("overlay_extra") and vtype != "MOTION_GRAPHICS":
        shot["overlay"] = {"caption": c["overlay"], "desc": c["overlay"], "style": "kinetic_text"}
    mo = r.get("motion") or {}
    if mo.get("move"):
        shot["camera"] = {"move": mo["move"], "amount": mo.get("amount", 0)}
    shot["transition_in"] = FADE.get(mo.get("fade_in"), "cut")
    shot["transition_out"] = FADE.get(mo.get("fade_out"), "cut")
    shots.append(shot)

old = json.loads((S / "match_backup" / "pre-m9" / "plan.json").read_text(encoding="utf-8"))
plan = {"session_id": old.get("session_id", S.name), "timing_source": "timestamps",
        "video_metadata": old.get("video_metadata", {}), "shots": shots,
        "editing_notes": {"method": "inspo-mapped", "inspos": ["videoplayback-2", "trading-strategies-27"]},
        "generated_at": datetime.now(timezone.utc).isoformat()}
(S / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
(S / "plan_progress.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in shots), encoding="utf-8")
types = {t: sum(1 for s in shots if s["visual"]["type"] == t) for t in TYPE.values()}
print(len(shots), "shots", types, "captions", sum("text" in s for s in shots), "overlays", sum("overlay" in s for s in shots),
      "directions", sum("user_directions" in s["visual"] for s in shots))
