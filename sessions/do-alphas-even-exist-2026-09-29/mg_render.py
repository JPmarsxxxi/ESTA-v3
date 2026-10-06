"""Render every built MG slot sequentially (memory is tight), verify with ffprobe, publish verified slots to
assets_progress.jsonl and write motion_graphics.json. Already-published slots are skipped."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

S = Path(__file__).parent
ROOT = S.parents[1]
MG, POOL = S / "assets" / "mg", S / "assets" / "source_pool"
POOL.mkdir(parents=True, exist_ok=True)
feed = S / "assets_progress.jsonl"
done = {str(json.loads(x).get("shot_number")) for x in feed.read_text(encoding="utf-8").splitlines() if x.strip()
        and json.loads(x).get("source") == "hyperframes"} if feed.exists() else set()


def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height:stream_tags=alpha_mode:format=duration",
                        "-of", "json", str(f)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    st = (j.get("streams") or [{}])[0]
    return float(j.get("format", {}).get("duration", 0)), st.get("width"), st.get("height"), (st.get("tags") or {}).get("alpha_mode") or (st.get("tags") or {}).get("ALPHA_MODE")


slots = []
for cfg_path in sorted((MG / "_kit" / "slots").glob("*.json")):
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    key, overlay = cfg["key"], cfg["flavor"] == "overlay"
    out = POOL / f"mg_{key}.{'webm' if overlay else 'mp4'}"
    rel = out.relative_to(ROOT).as_posix()
    if key not in done:
        cmd = ["npx.cmd", "hyperframes", "render", str(MG / f"slot_{key}"), "-o", str(out)] + (["--format", "webm"] if overlay else [])
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            slots.append({"key": key, "flavor": cfg["flavor"], "ok": False, "error": (r.stderr or r.stdout)[-300:]})
            print("FAIL", key, flush=True)
            continue
    dur, w, h, alpha = probe(out)
    errs = []
    if abs(dur - (cfg["duration"] + 1.0)) > 0.15:
        errs.append(f"duration {dur:.2f} vs {cfg['duration'] + 1.0:.2f}")
    if (w, h) != (1920, 1080):
        errs.append(f"size {w}x{h}")
    if overlay and alpha != "1":
        errs.append("no alpha")
    if errs:
        slots.append({"key": key, "flavor": cfg["flavor"], "ok": False, "error": "; ".join(errs)})
        print("BAD", key, errs, flush=True)
        continue
    slots.append({"key": key, "flavor": cfg["flavor"], "ok": True, "file": rel})
    if key not in done:
        n = key if overlay else int(key)
        with open(feed, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"shot_number": n, "ok": True, "source": "hyperframes", "asset_type": "video", "url": "",
                                 "file": rel, "search_query": "", "in_point": 0.0, "out_point": cfg["duration"], "error": "",
                                 "visual_verdict": "match", "visual_confidence": 100}) + "\n")
    print("ok", key, flush=True)

ok = sum(s["ok"] for s in slots)
(S / "motion_graphics.json").write_text(json.dumps({"slots": slots, "generated": ok, "fallbacks": len(slots) - ok,
                                                    "generated_at": datetime.now(timezone.utc).isoformat()}, indent=1), encoding="utf-8")
print(ok, "generated,", len(slots) - ok, "fell back")
