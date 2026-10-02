"""The side-by-side review page: every shot of ours next to the inspo shot it copies (SPEC.md Part 3, M6.5).

    python tools/match/review.py --session sessions/<id> --stage plan|final     # -> match_review.html

score.py writes it after every score. Self-contained: keyframes are inlined as 384 px JPEGs, so the page opens
offline and is served as-is by GET /_match/<id>/review (the Match card's "Open side-by-side").
"""

import argparse
import base64
import html
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import REPO_ROOT, read_json, utf8_stdout  # noqa: E402

SIDE = 384
LOW_THEME = 40
KIND_OF_TYPE = {"REAL_FOOTAGE": "footage", "AI_VIDEO": "footage", "REAL_IMAGE": "still", "MOTION_GRAPHICS": "graphic"}


def _img(path, pool: dict) -> str:
    """A keyframe as a CSS-backed tile. Each file is embedded once: a voiceover longer than its inspo maps
    several shots onto the same inspo shot."""
    if not path or not Path(path).exists():
        return ""
    key = str(Path(path).resolve())
    if key not in pool:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((SIDE, SIDE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=70)
        pool[key] = (f"k{len(pool)}", base64.b64encode(buf.getvalue()).decode())
    return f'<div class="kf {pool[key][0]}" role="img"></div>'


def _inspo(session: Path) -> dict:
    out = {}
    for rel in (read_json(session / "inspo_profiles.json", {}) or {}).get("profiles", []):
        d = REPO_ROOT / rel
        for s in (read_json(d / "profile.json", {}) or {}).get("shots", []):
            out[s["id"]] = {**s, "keyframe_path": d / s["keyframe"] if s.get("keyframe") else None}
    return out


def _failing(session: Path) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for f in (read_json(session / "plan_validation.json", {}) or {}).get("failures", []):
        for p in f.get("problems", []):
            m = re.match(r"shot (\d+): (.*)", p)
            if m:
                out.setdefault(int(m.group(1)), []).append(m.group(2))
    return out


def render(session: Path, stage: str, report: dict) -> str:
    from tools.match.score import _asset_rows
    esc = html.escape
    plan = {s["shot_number"]: s for s in (read_json(session / "plan.json", {}) or {}).get("shots", [])}
    inspo = _inspo(session)
    failing = _failing(session)
    assets = _asset_rows(session)
    pool: dict = {}
    rows = []
    for r in report.get("shots", []):
        n = r["n"]
        ps = plan.get(n, {})
        v = ps.get("visual") or {}
        ref = inspo.get(ps.get("ref_shot") or "")
        tags = (ref or {}).get("tags") or {}
        a = assets.get(str(n)) or {}
        dur, target = r.get("dur", 0.0), ps.get("ref_target_dur")
        flags = [f"validator: {p}" for p in failing.get(n, [])]
        if r.get("theme") is not None and r["theme"] < LOW_THEME:
            flags.append(f"low theme ({r['theme']})")
        if ps.get("ref_swap"):
            flags.append(f"ref swapped: {ps['ref_swap']}")
        if a.get("short_clip"):
            flags.append("short_clip: no candidate long enough")
        if a.get("speed") or (a.get("repeat") or 1) > 1:
            flags.append(f"filled: speed {a.get('speed') or 1}x, repeat {a.get('repeat') or 1}")
        if v.get("queries_stale"):
            flags.append("queries changed, refetch pending")
        if ps.get("locked"):
            flags.append("locked (hand-edited)")
        ours_img = _img(r.get("keyframe"), pool) if stage == "final" else ""
        ours = ours_img or f'<div class="ph">{"no media yet" if stage == "final" else "plan stage: no media yet"}</div>'
        theirs = _img((ref or {}).get("keyframe_path"), pool) or f'<div class="ph">{"no ref_shot (plan not mapped)" if not ref else "no keyframe"}</div>'
        cam = (ps.get("camera") or {}).get("move")
        moves = f'{cam or "none"} (ref: {(ref or {}).get("motion", {}).get("move", "?")})' if ref else (cam or "none")
        anim = tags.get("animation") or {}
        anim_line = f"<br><i>Animates: {esc(anim.get('reveal', ''))}, {esc(anim.get('speed', ''))}</i>" if anim else ""
        gen = ps.get("generate") or v.get("generate") or {}
        off = f" ({(dur - target) / target:+.0%})" if target else ""
        rows.append(f"""<section class="row{' bad' if flags and failing.get(n) else ''}">
  <header><b>Shot {n}</b> <span>{float(ps.get('start', 0) or 0):.2f}-{float(ps.get('end', 0) or 0):.2f} s</span>
    <span>{dur:.2f} s{f' vs target {target:.2f} s{off}' if target else ''}</span></header>
  <p class="said">&ldquo;{esc(ps.get('audio', '') or '')}&rdquo;</p>
  <div class="pair">
    <figure>{ours}<figcaption><b>Ours</b> · {esc(KIND_OF_TYPE.get(v.get('type', ''), r.get('kind', '')))}<br>{esc(v.get('desc', '') or r.get('desc', ''))}</figcaption></figure>
    <figure>{theirs}<figcaption><b>Inspo{f" {esc(ps.get('ref_shot', ''))}" if ref else ''}</b>{f" · {esc(tags.get('kind', ''))} · {esc(tags.get('content', ''))}" if tags else ''}<br>{esc(tags.get('description', ''))}{anim_line}</figcaption></figure>
  </div>
  <p class="meta">Camera: {esc(moves)}{' · generated: ' + esc(gen.get('preset', '')) if gen else ''}{' · ' + esc(a.get('source', '')) if a.get('source') else ''}</p>
  {'<ul class="flags">' + ''.join(f'<li>{esc(f)}</li>' for f in flags) + '</ul>' if flags else ''}
</section>""")
    sections = " · ".join(f"{k} {v['score'] if v.get('score') is not None else 'n/a'}" for k, v in (report.get("sections") or {}).items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Side by side</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#57534e; --card:#fff; --line:#e7e5e4; --bad:#b91c1c; --ph:#f5f5f4; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0c0a09; --fg:#f5f5f4; --muted:#a8a29e; --card:#1c1917; --line:#292524; --bad:#f87171; --ph:#292524; }} }}
:root[data-theme="dark"] {{ --bg:#0c0a09; --fg:#f5f5f4; --muted:#a8a29e; --card:#1c1917; --line:#292524; --bad:#f87171; --ph:#292524; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }}
h1 {{ font-size:18px; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 16px; }}
.row {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; margin:0 auto 12px; max-width:960px; }}
.row.bad {{ border-color:var(--bad); }}
.row header {{ display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; }} .row header span {{ color:var(--muted); }}
.said {{ margin:6px 0 10px; color:var(--muted); }}
.pair {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
@media (max-width:560px) {{ .pair {{ grid-template-columns:1fr; }} }}
figure {{ margin:0; min-width:0; }} .kf, .ph {{ width:100%; aspect-ratio:16/9; background:var(--ph) center/contain no-repeat; border-radius:4px; display:block; }}
.ph {{ display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:12px; }}
figcaption {{ font-size:13px; margin-top:6px; overflow-wrap:anywhere; }}
.meta {{ color:var(--muted); font-size:12px; margin:8px 0 0; }}
.flags {{ margin:8px 0 0; padding-left:18px; color:var(--bad); font-size:12px; }}
{''.join(f'.{c} {{ background-image:url(data:image/jpeg;base64,{d}); }}' for c, d in pool.values())}
</style></head><body>
<h1>{esc(session.name)} · side by side ({esc(stage)})</h1>
<p class="sub">Overall {report.get('overall', 'n/a')} ({'pass' if report.get('pass') else 'fail'}) · {esc(sections)} · {len(rows)} shots</p>
{''.join(rows)}
</body></html>
"""


def write(session: Path, stage: str, report: dict) -> Path:
    out = session / "match_review.html"
    out.write_text(render(session, stage, report), encoding="utf-8")
    return out


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Write the side-by-side review page")
    ap.add_argument("--session", required=True)
    ap.add_argument("--stage", choices=["plan", "final"], default="plan")
    a = ap.parse_args()
    session = Path(a.session)
    report = read_json(session / f"match_{a.stage}.json")
    if not report:
        print(f"no match_{a.stage}.json; score first")
        sys.exit(1)
    print(write(session, a.stage, report))


if __name__ == "__main__":
    main()
