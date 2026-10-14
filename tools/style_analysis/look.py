"""The structured `look` block of style_analysis.json, built from the inspo profiles (SPEC.md Part 12, goal A).

    python tools/style_analysis/look.py --session sessions/<id>

style_analysis.json's prose already said "3d render" and "green serif captions", and nothing downstream could act
on prose. This block is computed, not written:
- `materials`: duration-weighted share of each material (tools/plan/lanes.py MATERIALS);
- `finish`: the finishes on 25% or more of the duration;
- `palette`: the commonest colours;
- `layers`: presenter, logo bug, frame (the strongest across the inspos);
- `captions`: the caption layer, or `{"present": false}`. `null` when no profile could be read for captions
  (no OCR on that machine): render then keeps today's caption style.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.plan.lanes import FINISHES, ref_material  # noqa: E402

FINISH_SHARE = 0.25


def _lab_hex(c: dict) -> str:
    import cv2
    import numpy as np
    lab = np.uint8([[[min(255, max(0, c["L_mean"] * 255 / 100)), min(255, max(0, c["a_mean"] + 128)),
                      min(255, max(0, c["b_mean"] + 128))]]])
    r, g, b = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)[0, 0]
    return "#%02x%02x%02x" % (int(r), int(g), int(b))


def build_look(profiles: list[dict]) -> dict:
    shots = [s for p in profiles for s in p.get("shots", [])]
    total = sum(s.get("dur", 0) for s in shots) or 1.0
    materials: dict = {}
    finish: dict = {}
    for s in shots:
        tags = s.get("tags") or {}
        m = ref_material(tags)
        materials[m] = materials.get(m, 0.0) + s["dur"]
        for f in tags.get("finish") or []:
            if f in FINISHES:
                finish[f] = finish.get(f, 0.0) + s["dur"]
    pal: dict = {}
    for p in profiles:
        dur = sum(s.get("dur", 0) for s in p.get("shots", []))
        for i, c in enumerate(p.get("palette") or []):
            pal[c] = pal.get(c, 0.0) + dur / (i + 1)
    if not pal:
        for s in sorted((s for s in shots if s.get("colour")), key=lambda s: -s["dur"])[:12]:
            c = _lab_hex(s["colour"])
            pal[c] = pal.get(c, 0.0) + s["dur"]
    layers: dict = {}
    for p in profiles:
        for k, v in (p.get("layers") or {}).items():
            if k == "presenter" and v["share"] > layers.get(k, {}).get("share", 0):
                layers[k] = v
            elif k not in ("presenter", "captions"):
                layers.setdefault(k, v)
    return {"materials": {k: round(v / total, 3) for k, v in sorted(materials.items(), key=lambda x: -x[1])},
            "finish": sorted(f for f, v in finish.items() if v / total >= FINISH_SHARE),
            "palette": [c for c, _ in sorted(pal.items(), key=lambda x: -x[1])[:5]],
            "layers": layers, "captions": captions(profiles)}


def captions(profiles: list[dict]) -> dict | None:
    """The caption layer of the inspos that were read for it: present when inspos covering most of that duration
    show one (the best-sampled one's style is used), absent otherwise. None when none was read."""
    read = [p for p in profiles if isinstance(p.get("captions"), dict)]
    if not read:
        return None
    dur = lambda p: sum(s.get("dur", 0) for s in p.get("shots", []))  # noqa: E731
    shown = [p for p in read if p["captions"].get("present")]
    if sum(map(dur, shown)) * 2 <= sum(map(dur, read)):
        return {"present": False, "reason": "; ".join(p["captions"].get("reason", "") for p in read if not p["captions"].get("present"))}
    return max(shown, key=lambda p: p["captions"].get("samples", 0))["captions"]


def write_look(session: Path, profiles: list[dict]) -> dict | None:
    """Set `look` on the session's style_analysis.json (the plan, motion graphics and render read it there)."""
    path = session / "style_analysis.json"
    if not path.exists():
        return None
    style = json.loads(path.read_text(encoding="utf-8"))
    style["look"] = build_look(profiles)
    path.write_text(json.dumps(style, indent=2, ensure_ascii=False), encoding="utf-8")
    return style["look"]


def main() -> None:
    from tools.match.common import REPO_ROOT, read_json
    ap = argparse.ArgumentParser(description="Build style_analysis.json's look block from the inspo profiles")
    ap.add_argument("--session", required=True)
    session = Path(ap.parse_args().session)
    idx = read_json(session / "inspo_profiles.json", {}) or {}
    profiles = [read_json(REPO_ROOT / rel / "profile.json", {}) or {} for rel in idx.get("profiles", [])]
    look = write_look(session, profiles)
    print(json.dumps({"ok": look is not None, "look": look}, ensure_ascii=False))


if __name__ == "__main__":
    main()
