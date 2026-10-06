"""Motion-graphics slot configs for the mapped plan: one crimson word-card kit (the inspo's dominant graphic look),
data shapes where the line is data. Writes assets/mg/_kit/slots/<key>.json."""
import html
import json
from pathlib import Path

S = Path(__file__).parent
OUT = S / "assets" / "mg" / "_kit" / "slots"
plan = {s["shot_number"]: s for s in json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]}


def dur(n):
    return round(plan[n]["end"] - plan[n]["start"], 3)


def times(n, k):
    """k reveal times spread so the last lands by dur - 0.8 s (legibility floor); short slots show at once."""
    last = max(0.0, dur(n) - 0.8)
    return [round(last * i / max(1, k - 1), 2) if k > 1 else 0.05 for i in range(k)] if last > 0.2 else [0.0] * k


def line(n, parts, sep=" ", brk=None):
    ids = [f"w{i}" for i in range(len(parts))]
    spans = []
    for i, p in enumerate(parts):
        cls = "w break" if brk == i else "w"
        spans.append(f"<span class='{cls}' id='{ids[i]}'>{html.escape(p)}</span>")
    body = f"<div class='line'>{sep.join(spans)}</div>"
    tl = f"words(tl, {json.dumps(['#' + i for i in ids])}, {json.dumps(times(n, len(parts)))});"
    return body, tl


def count(n, label, target, dec, prefix="", suffix=""):
    t = times(n, 2)
    body = (f"<div class='line'><span class='w big' id='v'>{prefix}0{suffix}</span><br>"
            f"<span class='w sub' id='l'>{html.escape(label)}</span></div>")
    tl = f"countUp(tl, '#v', {target}, {dec}, 0.05, {max(0.3, t[1] - 0.1)}, '{prefix}', '{suffix}'); land(tl, '#l', {t[1]});"
    return body, tl


def bars(n, label, values):
    top = max(abs(v) for v in values)
    cells = "".join(f"<div class='bar{' neg' if v < 0 else ''}' style='height:{int(360 * abs(v) / top)}px'></div>"
                    for v in values)
    body = f"<div class='label' style='top:200px'><span class='w' id='l'>{html.escape(label)}</span></div><div class='bars'>{cells}</div>"
    tl = f"land(tl, '#l', 0.05); growBars(tl, '.bar', 0.25, {round(max(0.04, (dur(n) - 1.4) / len(values)), 3)});"
    return body, tl


def chart(n, label, d, extra=""):
    body = (f"<div class='label' style='top:200px'><span class='w' id='l'>{html.escape(label)}</span></div>"
            f"<svg class='plot' viewBox='0 0 1920 1080'><path id='p' d='{d}'/></svg>{extra}")
    tl = f"land(tl, '#l', 0.05); drawPath(tl, '#p', 0.3, {round(max(0.5, dur(n) - 1.3), 2)});"
    return body, tl


def overlay(n, text):
    return (f"<div class='ov' id='o'>{html.escape(text)}</div>", "land(tl, '#o', 0.1);")


UP = "M200 760 L360 720 L500 740 L660 650 L820 670 L980 560 L1140 590 L1300 480 L1460 500 L1620 400 L1720 380"
FULL = {
    13: line(13, ["alpha", "—", "an automated", "predictive model"]),
    14: line(14, ["decodes a", "market relation.", "rules."]),
    24: line(24, ["easy", "|", "right?", "|", "psych."], brk=4),
    28: line(28, ["started", "where everyone"]),
    29: line(29, ["starts.", "short-term"]),
    30: line(30, ["reversal.", "↓↑"]),
    50: count(50, "trades a year", 143, 0),
    86: line(86, ["my own ideas", "→", "nowhere."]),
    99: line(99, ["US500", "overnight"]),
    100: line(100, ["overnight drift,", "dead."]),
    114: count(114, "BTC weekly trend, gross", 0.95, 2, "+", "% a week"),
    152: line(152, ["spread,", "swap,", "slippage,", "impact"]),
    163: line(163, ["high-gamma days", "are just", "quiet."]),
    164: line(164, ["GEX", "vs", "boring free realised vol"]),
    204: line(204, ["extremes.", "swap-killed."], brk=1),
    205: line(205, ["the entire effect was", "crude oil", "in a trenchcoat."]),
    220: count(220, "information coefficient", 0.0205, 4, "+"),
    221: count(221, "observations", 2.16, 2, "", " million"),
    234: count(234, "of the turnover netted out", 87, 0, "", "%"),
    297: line(297, ["36-year", "validation", "of #023"]),
    298: line(298, ["three decades", "of a number"]),
    299: line(299, ["the vendor", "made up."], brk=1),
    314: line(314, ["+"]),
    317: chart(317, "ahead in every year", UP),
    318: bars(318, "the baseline", [0.4, 0.6, -0.9, 0.5, 0.3]),
    319: count(319, "baseline in 2022", -6.7, 1),
    320: bars(320, "deflated Sharpe 0.887 vs the bar 0.95", [0.887, 0.95]),
    324: line(324, ["out of"]),
    327: bars(327, "12 of 12 years positive", [0.4, 0.6, 0.5, 0.8, 0.3, 0.7, 0.5, 0.9, 0.6, 0.4, 0.7, 0.5]),
}
OVER = {n: overlay(n, plan[n]["overlay"]["caption"]) for n, s in plan.items() if s.get("overlay")}

OUT.mkdir(parents=True, exist_ok=True)
for n, (body, tl) in FULL.items():
    assert plan[n]["visual"]["type"] == "MOTION_GRAPHICS", n
    (OUT / f"{n}.json").write_text(json.dumps({"key": str(n), "flavor": "full_frame", "duration": dur(n),
                                               "body": body, "timeline": tl}, ensure_ascii=False), encoding="utf-8")
for n, (body, tl) in OVER.items():
    (OUT / f"{n}-overlay.json").write_text(json.dumps({"key": f"{n}-overlay", "flavor": "overlay", "duration": dur(n),
                                                       "body": body, "timeline": tl}, ensure_ascii=False), encoding="utf-8")
missing = [n for n, s in plan.items() if s["visual"]["type"] == "MOTION_GRAPHICS" and n not in FULL]
print(len(FULL), "full-frame,", len(OVER), "overlays; missing:", missing)
