"""Side-by-side page: keyframe, Haiku vs Gemma description + sources, scored on our known-source shots."""
import base64
import collections
import html
import json
from pathlib import Path

OUT = Path(__file__).parent
NORM = {"pexels": "pexels_video", "pixabay": "pixabay_video"}


def parse(text: str) -> dict:
    try:
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return {"description": str(obj.get("description", "")), "likely_sources": list(obj.get("likely_sources") or [])}
    except Exception:  # noqa: BLE001
        return {"description": f"(unparsed) {text[:200]}", "likely_sources": []}


def main() -> None:
    shots = json.loads((OUT / "shots.json").read_text(encoding="utf-8"))
    hz = json.loads((OUT / "haiku_results.json").read_text(encoding="utf-8"))
    gpath = OUT / "gemma_job" / "results.json"
    gem = {k: parse(v) for k, v in json.loads(gpath.read_text(encoding="utf-8")).items()} if gpath.exists() else {}
    models = {"Haiku 4.5": hz["answers"], "Gemma 4 E4B": gem}
    meta = json.loads((OUT / "run_meta.json").read_text(encoding="utf-8")) if (OUT / "run_meta.json").exists() else {}

    ours = [s for s in shots if s["side"] == "ours"]
    stats = []
    for name, ans in models.items():
        t1 = sum(bool(ans.get(s["id"], {}).get("likely_sources")) and ans[s["id"]]["likely_sources"][0] == NORM.get(s["true_source"], s["true_source"]) for s in ours)
        t3 = sum(NORM.get(s["true_source"], s["true_source"]) in ans.get(s["id"], {}).get("likely_sources", []) for s in ours)
        mix = collections.Counter(ans[s["id"]]["likely_sources"][0] for s in shots
                                  if s["side"] == "inspo" and ans.get(s["id"], {}).get("likely_sources"))
        stats.append((name, len(ans), t1, t3, mix.most_common(6), meta.get(name, "")))

    rows = []
    for s in shots:
        img = base64.b64encode((OUT / "frames" / f"{s['id']}.jpg").read_bytes()).decode()
        truth = f"<div class=truth>true: {html.escape(NORM.get(s['true_source'], s['true_source']))}</div>" if s["side"] == "ours" else ""
        cells = []
        for name, ans in models.items():
            a = ans.get(s["id"], {})
            src = a.get("likely_sources", [])
            hit = s["side"] == "ours" and NORM.get(s["true_source"], s["true_source"]) in src
            cells.append(f"<td><p>{html.escape(a.get('description', '-'))}</p><div class='src{' hit' if hit else ''}'>"
                         f"{html.escape(', '.join(src))}</div><div class=src>text {a.get('text_on_screen', '-')} · "
                         f"overlay {a.get('overlay_extra', '-')}</div></td>")
        rows.append(f"<tr class={s['side']}><td class=meta><b>{s['id']}</b><br>{s['start']:.2f}-{s['end']:.2f}s<br>"
                    f"{s['dur']:.2f}s{truth}</td><td><img src='data:image/jpeg;base64,{img}'></td>{''.join(cells)}</tr>")

    summary = "".join(
        f"<div class=card><h3>{n}</h3><p>{k} answers</p><p>our 17 shots, true source: <b>top-1 {a}/{len(ours)}</b>, "
        f"top-3 {b}/{len(ours)}</p><p>inspo top-1 mix: {html.escape(', '.join(f'{x} {c}' for x, c in mix))}</p>"
        f"<p class=muted>{html.escape(m)}</p></div>" for n, k, a, b, mix, m in stats)
    match_html = ""
    for name, key in (("Haiku 4.5", "haiku"), ("Gemma 4 E4B", "gemma")):
        mp = OUT / f"match_{key}.json"
        if not mp.exists():
            match_html += f"<div class=card><h3>Match with {name}</h3><p class=muted>not run yet</p></div>"
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        trs = []
        for k in "abcde":
            p, f = m["plan"]["sections"][k], m["final"]["sections"][k]
            cell = lambda v: "n/a" if v["score"] is None else f"<span class={'ok' if v['pass'] else 'bad'}>{v['score']}</span>"  # noqa: E731
            trs.append(f"<tr><td>{k}. {html.escape(f['name'])}</td><td>{cell(p)}</td><td>{cell(f)}</td></tr>")
        fa, fd, fe, fb = (m["final"]["sections"][k] for k in "adeb")
        mix = lambda d: ", ".join(f"{k} {v:.0%}" for k, v in sorted(d.items(), key=lambda x: -x[1]) if v >= 0.01)  # noqa: E731
        detail = (f"<p><b>a</b> ours: {html.escape(mix(fa.get('ours', {})))}<br>inspo: {html.escape(mix(fa.get('inspo', {})))}</p>"
                  f"<p><b>b</b> {html.escape(', '.join(f'{k} {v['ours_median']} vs {v['inspo_median']}' for k, v in (fb.get('features') or {}).items()))}</p>"
                  f"<p><b>d</b> {html.escape(', '.join(f'{k}: ours {v['ours']} vs inspo {v['inspo']} ({v['score']})' for k, v in (fd.get('rates') or {}).items()))}</p>"
                  f"<p><b>e</b> mean {fe['mean']['ours']}s vs {fe['mean']['inspo']}s, median {fe['median']['ours']}s vs {fe['median']['inspo']}s</p>")
        match_html += (f"<div class=card><h3>Match with {name}</h3><table class=scores><tr><th>section</th><th>plan</th><th>final</th></tr>"
                       f"{''.join(trs)}<tr><td><b>overall</b></td><td><b class={'ok' if m['plan']['pass'] else 'bad'}>{m['plan']['overall']}</b></td>"
                       f"<td><b class={'ok' if m['final']['pass'] else 'bad'}>{m['final']['overall']}</b></td></tr></table>{detail}</div>")
    nudge_html = ""
    np_ = OUT / "nudge_haiku.json"
    if np_.exists():
        nd = json.loads(np_.read_text(encoding="utf-8"))
        orig = json.loads((Path(__file__).resolve().parents[4] / "sessions" / "do-alphas-even-exist-2026-09-29"
                           / "plan.json").read_text(encoding="utf-8"))["shots"]
        frame_of = {int(s["id"][1:]): s["id"] for s in shots if s["side"] == "ours"}
        trs = []
        for k in "abcde":
            b, a = nd["plan_before"]["sections"][k], nd["plan_after"]["sections"][k]
            fmt = lambda v: "n/a" if v["score"] is None else f"<span class={'ok' if v['pass'] else 'bad'}>{v['score']}</span>"  # noqa: E731
            trs.append(f"<tr><td>{k}. {html.escape(a['name'])}</td><td>{fmt(b)}</td><td>{fmt(a)}</td></tr>")
        mix = lambda d: ", ".join(f"{k} {v:.0%}" for k, v in sorted(d.items(), key=lambda x: -x[1]))  # noqa: E731
        rounds = "".join(f"<li><b>Round {r['round']}</b> ({'kept' if r['kept'] else 'not kept'}{', ' + r['why'] if r.get('why') else ''}): "
                         f"{html.escape('; '.join(r['changes']))}</li>" for r in nd["rounds"])
        rows_n = []
        for s in nd["shots_after"]:
            o = next((x for x in orig if float(x["start"]) <= float(s["start"]) + 0.01 < float(x["end"])), None)
            ov = (o or {}).get("visual") or {}
            fid = frame_of.get(o["shot_number"]) if o else None
            img = f"<img src='data:image/jpeg;base64,{base64.b64encode((OUT / 'frames' / f'{fid}.jpg').read_bytes()).decode()}'>" if fid else ""
            changed = o is None or ov.get("desc") != s["desc"] or ov.get("type") != s["type"]
            split = o is not None and (abs(float(o["start"]) - s["start"]) > 0.01 or abs(float(o["end"]) - s["end"]) > 0.01)
            tag = ("split: refetches new clip" if s.get("refetch") else "split: keeps this clip") if split else \
                ("changed" if changed else "unchanged")
            src_o = ", ".join(e.get("source", "") for e in ov.get("search_sources") or [])
            rows_n.append(
                f"<tr class={'chg' if changed or split else ''}><td class=meta><b>{s['n']}</b><br>{s['start']:.2f}-{s['end']:.2f}s<br><i>{tag}</i></td>"
                f"<td><p class=said>\"{html.escape(s['audio'])}\"</p></td>"
                f"<td>{img}<p class=src>{html.escape(ov.get('type', ''))} · {html.escape(src_o)}</p><p>{html.escape(ov.get('desc', ''))}</p></td>"
                f"<td><p class=src>{html.escape(s['type'] or '')} · {html.escape(', '.join(s['sources']))}</p><p>{html.escape(s['desc'])}</p></td></tr>")
        nudge_html = (f"<h2>Nudge (plan stage, first 60s): {nd['plan_before']['overall']} → {nd['plan_after']['overall']}, "
                      f"${nd['nudge_cost_usd']}</h2><div class=cards><div class=card><table class=scores><tr><th>section</th>"
                      f"<th>before</th><th>after</th></tr>{''.join(trs)}</table>"
                      f"<p><b>a</b> before: {mix(nd['plan_before']['sections']['a'].get('ours', {}))}<br>after: "
                      f"{mix(nd['plan_after']['sections']['a'].get('ours', {}))}<br>inspo: {mix(nd['plan_after']['sections']['a'].get('inspo', {}))}</p>"
                      f"</div><div class=card><ul>{rounds}</ul></div></div>"
                      f"<div class=wrap><table><tr><th>shot</th><th>spoken</th><th>before (current edit frame)</th><th>after nudge</th></tr>"
                      f"{''.join(rows_n)}</table></div>")
    page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Shot Describe Bake-off</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--card:#fff;--hit:#15803d;--ours:#f5f5f4}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--line:#44403c;--card:#292524;--hit:#4ade80;--ours:#292524}}}}
:root[data-theme=dark]{{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--line:#44403c;--card:#292524;--hit:#4ade80;--ours:#292524}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 4px}} .muted{{color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:16px 0 24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px}} .card h3{{margin:0 0 8px;font-size:15px}} .card p{{margin:4px 0}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;min-width:760px}}
td,th{{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}} th{{font-size:12px;color:var(--muted);font-weight:600}}
td.meta{{white-space:nowrap;font-size:12px;width:90px}} img{{width:200px;border-radius:4px;display:block}}
td p{{margin:0 0 6px}} .src{{font-size:12px;color:var(--muted);font-family:ui-monospace,monospace}} .src.hit{{color:var(--hit);font-weight:600}}
h2{{font-size:16px;margin:20px 0 0}} tr.chg td{{background:var(--ours)}} .said{{font-style:italic}} ul{{margin:0;padding-left:18px}} .ok{{color:var(--hit)}} .bad{{color:#dc2626}}
table.scores{{min-width:0;margin-bottom:8px}} table.scores td,table.scores th{{padding:4px 8px}}
.truth{{margin-top:6px;font-family:ui-monospace,monospace;color:var(--hit)}} tr.ours td{{background:var(--ours)}}
</style></head><body>
<h1>Shot describe bake-off</h1>
<p class=muted>Inspo: videoplayback (2).mp4, all {sum(s['side'] == 'inspo' for s in shots)} TransNetV2 shots. Ours: first 60s of do-alphas-even-exist ({len(ours)} shots, shaded, true source known). Same 384px keyframe and prompt for both models.</p>
{nudge_html}
<h2>Match: first 60s of ours vs the inspo (pass 80 overall, 70 per section)</h2>
<div class=cards>{match_html}</div>
<h2>Describe + sources, per model</h2>
<div class=cards>{summary}</div>
<div class=wrap><table><tr><th>shot</th><th>keyframe</th>{''.join(f'<th>{n}</th>' for n in models)}</tr>
{''.join(r for r in rows if 'class=ours' in r)}{''.join(r for r in rows if 'class=ours' not in r)}</table></div></body></html>"""
    (OUT / "bakeoff.html").write_text(page, encoding="utf-8")
    for n, k, a, b, mix, m in stats:
        print(n, k, f"top1 {a}/{len(ours)} top3 {b}/{len(ours)}", mix)


if __name__ == "__main__":
    main()
