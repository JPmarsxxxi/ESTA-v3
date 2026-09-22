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
"""

import argparse
import json
import sys
from pathlib import Path

GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
HOLD_TAIL = 1.0  # extra second so the cut never clips mid-motion (render trims it)
W, H = 1080, 1920

TEMPLATE = """<!doctype html>
<html lang="en" data-resolution="portrait">
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


def build_slot(session: Path, cfg: dict, kit_css: str, kit_js: str) -> Path:
    key = str(cfg["key"])
    flavor = cfg.get("flavor", "full_frame")
    # Full-frame needs an opaque background or the MP4 renders on white; overlay
    # must be transparent so the footage shows through everywhere the card isn't.
    bg = "background: transparent;" if flavor == "overlay" else "background: #000;"
    # The slot's on-screen duration + a hold tail so animation never clips at the cut.
    duration = round(float(cfg["duration"]) + HOLD_TAIL, 3)

    html = TEMPLATE.format(
        W=W, H=H, gsap=GSAP, bg=bg,
        surface_css=kit_css.rstrip(),
        body=cfg.get("body", "").rstrip(),
        helpers_js=kit_js.strip(),
        timeline=cfg.get("timeline", "").rstrip(),
        duration=duration,
    )
    out_dir = session / "assets" / "mg" / f"slot_{key}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return out_dir / "index.html"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build MG slots from the session kit + configs")
    ap.add_argument("--session", required=True)
    ap.add_argument("--key", help="build one slot only (default: all in _kit/slots)")
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
    print(json.dumps({"ok": True, "built": len(built), "slots": built}, indent=2))


if __name__ == "__main__":
    main()
