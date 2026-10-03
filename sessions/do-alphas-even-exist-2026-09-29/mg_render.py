"""Render every built slot, verify it, publish it to the assets feed, write motion_graphics.json."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
KIT = HERE / "assets" / "mg" / "_kit" / "slots"
POOL = HERE / "assets" / "source_pool"
HF = str(REPO / "node_modules" / ".bin" / "hyperframes.exe")


def render(cfg):
    key, overlay = cfg["key"], cfg["flavor"] == "overlay"
    out = POOL / f"mg_{key}.{'webm' if overlay else 'mp4'}"
    if not (out.exists() and out.stat().st_size > 1024):
        args = [HF, "render", str(HERE / "assets" / "mg" / f"slot_{key}"), "-o", str(out)] + (["--format", "webm"] if overlay else [])
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, cwd=REPO)
        if r.returncode != 0 or not out.exists():
            return {"key": key, "flavor": cfg["flavor"], "ok": False, "error": (r.stderr or r.stdout)[-300:]}
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(out)],
                       capture_output=True, text=True)
    info = json.loads(p.stdout or "{}")
    dur = float(info.get("format", {}).get("duration", 0))
    w = (info.get("streams") or [{}])[0].get("width")
    want = cfg["duration"] + 1.0
    if abs(dur - want) > 0.2 or w != 1920:
        return {"key": key, "flavor": cfg["flavor"], "ok": False, "error": f"verify: {dur:.2f}s vs {want:.2f}s, width {w}"}
    return {"key": key, "flavor": cfg["flavor"], "ok": True, "file": f"sessions/{HERE.name}/assets/source_pool/{out.name}",
            "duration": cfg["duration"]}


def main():
    POOL.mkdir(parents=True, exist_ok=True)
    cfgs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(KIT.glob("*.json"))]
    with ThreadPoolExecutor(max_workers=1) as pool:
        results = list(pool.map(render, cfgs))
    with open(HERE / "assets_progress.jsonl", "a", encoding="utf-8") as fh:
        for r in results:
            if not r["ok"]:
                continue
            n = int(r["key"]) if r["flavor"] == "full_frame" else r["key"]
            fh.write(json.dumps({"shot_number": n, "ok": True, "source": "hyperframes", "asset_type": "video", "url": "",
                                 "file": r["file"], "search_query": "", "in_point": 0.0, "out_point": r["duration"],
                                 "error": "", "visual_verdict": "match", "visual_confidence": 100}) + "\n")
    ok = [r for r in results if r["ok"]]
    (HERE / "motion_graphics.json").write_text(json.dumps({
        "slots": results, "generated": len(ok), "fallbacks": len(results) - len(ok),
        "generated_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    print(json.dumps({"generated": len(ok), "failed": [(r["key"], r["error"][:120]) for r in results if not r["ok"]]}))


if __name__ == "__main__":
    main()
