"""Assemble motion-graphics slots from a shared session kit + thin per-slot configs.

The cost problem (measured: ~482k tokens / 90 min for 6 slots): every slot
re-authored the entire surface — the same terminal CSS, fonts, grid, and GSAP
helpers, retyped by a fresh sub-agent that couldn't see the others. Slots 5 and
17 built byte-identical chrome from scratch.

The fix is to author the surface ONCE and make each slot thin. This builder does
the assembly deterministically (zero tokens): it inlines the session kit
(surface.css + helpers.js) into a complete, standalone, lint-valid index.html for
each slot, so HyperFrames renders an ordinary single composition — no runtime
nesting, no cross-file variable propagation to debug.

    sessions/<id>/assets/mg/
      _kit/surface.css      # all surface chrome — authored ONCE per session
      _kit/helpers.js       # shared GSAP helpers (countUp, reveal, typeOn, ...)
      slots/<key>.json      # {key, flavor, duration, body, timeline} — thin
      slot_<key>/index.html # BUILT output, ready to render

A slot config is small:
    {"key": "5", "flavor": "full_frame", "duration": 2.74,
     "body": "<div class='label'>SHARPE</div><div class='value' id='v'>0.00</div>",
     "timeline": "countUp(tl, '#v', 3.71, 0.3);"}

    conda run -n esta python tools/motiongraphics/build.py --session sessions/<id>
    conda run -n esta python tools/motiongraphics/build.py --session sessions/<id> --key 5

After building, every slot's text is measured in headless Chrome across its timeline, and any text box that
reaches into the caption band (slots.json `caption_band`, else where our captions sit) is flagged under
`band_crossings`: move that text out of the band before rendering (SPEC.md Part 12, F11).
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
HOLD_TAIL = 1.0  # extra second so the cut never clips mid-motion (render trims it)
# Canvas per requirements.orientation, as render's _dimensions_for_orientation.
SIZES = {"horizontal": (1920, 1080), "landscape": (1920, 1080), "square": (1080, 1080)}

TEMPLATE = """<!doctype html>
<html lang="en" data-resolution="{res}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <script src="{gsap}"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {W}px; height: {H}px; overflow: hidden; {bg} }}
{surface_css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" class="clip" data-track-index="1"
         data-start="0" data-duration="{duration}" data-width="{W}" data-height="{H}">
{body}
    </div>
    <script>{helpers_js}</script>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
{timeline}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def canvas(session: Path) -> tuple[int, int]:
    try:
        o = json.loads((session / "requirements.json").read_text(encoding="utf-8")).get("orientation", "")
    except (OSError, ValueError):
        o = ""
    return SIZES.get(str(o).strip().lower(), (1080, 1920))


def build_slot(session: Path, cfg: dict, kit_css: str, kit_js: str) -> Path:
    W, H = canvas(session)
    key = str(cfg["key"])
    flavor = cfg.get("flavor", "full_frame")
    # Full-frame needs an opaque background or the MP4 renders on white; overlay
    # must be transparent so the footage shows through everywhere the card isn't.
    bg = "background: transparent;" if flavor == "overlay" else "background: #000;"
    # The slot's on-screen duration + a hold tail so animation never clips at the cut.
    duration = round(float(cfg["duration"]) + HOLD_TAIL, 3)

    html = TEMPLATE.format(
        W=W, H=H, res="landscape" if W > H else "portrait", gsap=GSAP, bg=bg,
        # A kit that paints #root (a full-frame surface colour) would make every overlay opaque.
        surface_css=kit_css.rstrip() + ("\n      #root { background: transparent !important; }" if flavor == "overlay" else ""),
        body=cfg.get("body", "").rstrip(),
        helpers_js=kit_js.strip(),
        timeline=cfg.get("timeline", "").rstrip(),
        duration=duration,
    )
    out_dir = session / "assets" / "mg" / f"slot_{key}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return out_dir / "index.html"


def caption_band(session: Path) -> tuple[float, float] | None:
    """The caption band as fractions of the frame height: measured from the inspo (slots.json, SPEC.md Part 12
    goal D), else where our own captions sit. None when the video has no captions."""
    try:
        band = json.loads((session / "slots.json").read_text(encoding="utf-8")).get("caption_band")
    except (OSError, ValueError):
        band = None
    if isinstance(band, dict):
        return (float(band["y0"]), float(band["y1"])) if band.get("present", True) else None
    from tools.opencut.from_openreel import caption_band as ours
    return ours(*canvas(session))


def band_crossings(boxes: list[dict], band: tuple[float, float], height: int) -> list[dict]:
    """Text boxes that reach into the caption band, where karaoke captions would sit on top of them."""
    y0, y1 = band[0] * height, band[1] * height
    seen, out = set(), []
    for b in boxes:
        if b["y1"] > y0 and b["y0"] < y1 and b["text"] not in seen:
            seen.add(b["text"])
            out.append({"text": b["text"], "y0": round(b["y0"]), "y1": round(b["y1"])})
    return out


def measure_text(paths: list[Path]) -> dict | None:
    """{index path: text boxes} from headless Chrome, or None when node or Chrome is missing."""
    node = shutil.which("node")
    if not node or not paths:
        return None
    script = Path(__file__).with_name("text_boxes.mjs")
    r = subprocess.run([node, str(script), *map(str, paths)], capture_output=True, text=True, timeout=300)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return out.get("boxes") if out.get("ok") else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Build MG slots from the session kit + configs")
    ap.add_argument("--session", required=True)
    ap.add_argument("--key", help="build one slot only (default: all in _kit/slots)")
    ap.add_argument("--no-band-check", action="store_true", help="skip measuring text against the caption band")
    args = ap.parse_args()

    session = Path(args.session)
    kit = session / "assets" / "mg" / "_kit"
    css_path, js_path = kit / "surface.css", kit / "helpers.js"
    if not css_path.exists():
        print(json.dumps({"ok": False, "error": f"no kit surface.css at {css_path} — author the kit first"}))
        sys.exit(1)
    kit_css = css_path.read_text(encoding="utf-8")
    kit_js = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    slots_dir = kit / "slots"
    if args.key:
        cfgs = [json.loads((slots_dir / f"{args.key}.json").read_text(encoding="utf-8"))]
    else:
        if not slots_dir.exists():
            print(json.dumps({"ok": False, "error": f"no slot configs at {slots_dir}"}))
            sys.exit(1)
        cfgs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(slots_dir.glob("*.json"))]

    built = []
    for cfg in cfgs:
        path = build_slot(session, cfg, kit_css, kit_js)
        built.append({"key": cfg["key"], "flavor": cfg.get("flavor", "full_frame"),
                      "duration": round(float(cfg["duration"]) + HOLD_TAIL, 3),
                      "index": str(path)})
    out = {"ok": True, "built": len(built), "slots": built}
    band = caption_band(session)
    boxes = measure_text([Path(b["index"]) for b in built]) if band and not args.no_band_check else None
    if boxes is not None:
        _, H = canvas(session)
        out["caption_band"] = {"y0": round(band[0] * H), "y1": round(band[1] * H)}
        for b in built:
            hits = band_crossings(boxes.get(b["index"], []), band, H)
            if hits:
                b["crosses_caption_band"] = hits
        out["band_crossings"] = [b["key"] for b in built if b.get("crosses_caption_band")]
    elif band and not args.no_band_check:
        out["band_check"] = "skipped: node or Chrome not found"
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
