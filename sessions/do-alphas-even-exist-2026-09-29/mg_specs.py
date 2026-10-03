"""Motion-graphics slot configs for this session: one short spec per shot, built
into assets/mg/_kit/slots/<key>.json for tools/motiongraphics/build.py.

Layouts: R rows (dot-leader readouts, optional $ command, # comments, stamp),
C chart (step-line plot), B big stat, H section header, O overlay card.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / "plan.json").read_text(encoding="utf-8"))
DUR = {s["shot_number"]: max(0.5, round(s["end"] - s["start"], 3)) for s in PLAN["shots"]}
SLOTS = HERE / "assets" / "mg" / "_kit" / "slots"


def lead(k, v, w=24):
    return f"&gt; {k} {'.' * max(3, w - len(k))} <b>{v}</b>"


# (shot, layout, spec). Rows: ("key", "value") readouts, "# text" comments, "$ text" dim commands.
SPECS = [
    (8, "R", {"rows": ["$ man alpha", "# an idea about how the market works"]}),
    (9, "R", {"rows": ["$ man alpha", "# an idea about how the market works", "# concretely: a predictive model", ("decodes", "market relations")], "keep": 2}),
    (10, "R", {"rows": [("input", "data"), ("rules", "->")]}),
    (11, "R", {"rows": [("input", "data"), ("rules", "->"), ("output", "positions, trades")], "keep": 2}),
    (12, "R", {"rows": ["# -- Igor Tulchinsky"]}),
    (13, "R", {"rows": ["# -- Igor Tulchinsky", "#    Finding Alphas, WorldQuant/Wiley, 2020"], "keep": 1}),
    (17, "R", {"rows": ["$ find_alphas --since 2m", ("equations_written", "lots")]}),
    (18, "R", {"rows": ["$ find_alphas --since 2m", ("equations_written", "lots"), ("alphas_found", "0?"), "# might not exist"], "keep": 2}),
    (19, "H", {"text": "#001 :: short_term_reversal"}),
    (20, "C", {"cmd": "$ plot reversal.idea", "shape": "dipbounce", "xl": "t-5", "xr": "t+5", "foot": "# drops vs peers, you buy, it bounces"}),
    (24, "R", {"rows": ["$ backtest reversal --univ SP100", ("gross_sharpe", "0.05")]}),
    (28, "R", {"rows": ["$ backtest reversal --univ midcap", ("gross_sharpe", "...")]}),
    (29, "R", {"rows": ["$ backtest reversal --univ midcap", ("gross_sharpe", "0.05 -> 0.445")], "keep": 1}),
    (30, "B", {"value": "0.058", "label": "net sharpe", "sub": "# sheeiiii"}),
    (32, "R", {"rows": [("gross_sharpe", "0.445"), ("net_sharpe", "0.058")]}),
    (33, "R", {"rows": [("gross_sharpe", "0.445"), ("net_sharpe", "0.058"), ("trades_per_yr", "143")], "keep": 2}),
    (34, "R", {"rows": [("gross_sharpe", "0.445"), ("net_sharpe", "0.058"), ("trades_per_yr", "143"), ("spread_paid", "every. time."), "$ add signal_decay"], "keep": 3}),
    (35, "R", {"rows": [("edge_kept", "94%"), ("costs_cut", "26%"), ("net_sharpe", "0.126")]}),
    (37, "R", {"rows": [("edge_kept", "94%"), ("costs_cut", "26%"), ("net_sharpe", "0.126"), ("max_drawdown", "-40%"), ("annual_return", "~1%")], "keep": 3}),
    (42, "B", {"value": "-1.01", "label": "gross sharpe", "sub": "# crypto, reversal"}),
    (44, "R", {"rows": ["$ backtest reversal --univ crypto", "# 24/7. retail. degenerate.", ("gross_sharpe", "...")]}),
    (45, "R", {"rows": ["$ backtest reversal --univ crypto", "# 24/7. retail. degenerate.", ("gross_sharpe", "-1.01")], "keep": 2, "stamp": "WRONG"}),
    (46, "R", {"rows": ["# beautifully, catastrophically wrong", "$ flip --sign"]}),
    (47, "C", {"cmd": "$ plot #006 crypto_momentum_30d", "shape": "up", "xl": "2018", "xr": "2025", "foot": "net_sharpe ...... 1.10   yrs_positive ...... 7/8"}),
    (50, "R", {"rows": ["$ deploy #006 --venue FTMO --univ cfd_14"]}),
    (53, "B", {"value": "0.38", "label": "net sharpe", "sub": "# FTMO CFDs"}),
    (54, "R", {"rows": [("net_sharpe", "0.38"), "# slightly bad", "$ measure swap --live"]}),
    (55, "R", {"rows": [("swap_crypto_cfd", "30% / yr / side"), ("stress_test_case", "15%")]}),
    (56, "R", {"rows": [("swap_crypto_cfd", "30% / yr / side"), ("stress_test_case", "15%"), "# reality = 2x worst case"], "keep": 2}),
    (63, "R", {"rows": [("btc_intraday_trend", "DEAD"), ("us500_open_to_close", "DEAD")], "stamp": "DEAD"}),
    (64, "R", {"rows": ["$ grep papers/ --anomaly"]}),
    (66, "R", {"rows": [("btc_intraday_trend", "DEAD")]}),
    (67, "R", {"rows": [("btc_intraday_trend", "DEAD"), ("us500_open_to_close", "DEAD")], "keep": 1}),
    (70, "R", {"rows": [("anomaly_half_life", "\"publication\"")]}),
    (71, "C", {"cmd": "$ plot anomaly --window paper,after", "shape": "diesafter", "xl": "paper sample", "xr": "after", "foot": "# there, then gone. every time."}),
    (72, "R", {"rows": ["# if I can read it,"]}),
    (73, "R", {"rows": ["# if I can read it,", "# everyone can read it", ("anomaly_half_life", "\"publication\"")], "keep": 1}),
    (74, "R", {"rows": ["$ backtest trend --univ multi_asset_45", ("result", "DEAD"), "# not from cost"], "stamp": "DEAD"}),
    (75, "R", {"rows": ["# those instruments just don't trend"]}),
    (76, "R", {"rows": ["$ backtest btc_weekly_trend", ("gross", "+0.95% / wk")]}),
    (77, "R", {"rows": ["$ backtest btc_weekly_trend", ("gross", "+0.95% / wk"), "# genuinely real"], "keep": 2}),
    (78, "R", {"rows": ["$ backtest btc_weekly_trend", ("gross", "+0.95% / wk"), ("swap", "-0.577% / wk")], "keep": 2}),
    (79, "C", {"cmd": "$ plot btc_weekly_trend.pnl --net", "shape": "spikeflat", "xl": "2016", "xr": "2025", "foot": "# leftover profit: 100% the 2017 mania"}),
    (80, "R", {"rows": ["$ backtest fx_time_of_day --pairs 3", ("short", "21:00 London"), ("long", "23:00 London")]}),
    (82, "B", {"value": "5.28", "label": "net sharpe (backtest)", "sub": "# EINSTEIN"}),
    (83, "R", {"rows": [("net_sharpe", "5.28"), ("annual_return", "+12.5%"), ("oos_years_positive", "5/5")]}),
    (84, "R", {"rows": ["$ deploy fx_time_of_day --live", "# deployed"]}),
    (87, "R", {"rows": ["# half the edge wasn't real"]}),
    (88, "R", {"rows": ["$ pull tick_data --spread hourly", "# costs weren't guessed"]}),
    (89, "R", {"rows": ["$ pull tick_data --spread hourly", "# costs weren't guessed", ("swap", "free, by design")], "keep": 2}),
    (92, "R", {"rows": ["# deployed it."]}),
    (93, "R", {"rows": ["$ report live --since deploy"]}),
    (95, "B", {"value": "0.00", "label": "live edge", "sub": "# gross: negative"}),
    (96, "R", {"rows": ["# half the edge wasn't real", ("21:00_session", "bid quotes")]}),
    (97, "R", {"rows": ["# half the edge wasn't real", ("21:00_session", "bid quotes"), "$ remeasure --mid"], "keep": 2}),
    (98, "R", {"rows": [("book_sharpe", "~1.0")]}),
    (99, "R", {"rows": [("book_sharpe", "~1.0"), ("not", "5.3"), "# a quoting artifact"], "keep": 1}),
    (100, "R", {"rows": [("fx_commission", "$0.25 / deal"), ("round_trip", "$0.50 / leg"), ("cost", "2.00 bp / night"), ("edge", "1.24 bp / night")], "stamp": "NEGATIVE"}),
    (101, "R", {"rows": [("live_edge", "0")]}),
    (102, "R", {"rows": [("live_edge", "0"), "# not smaller. zero.", ("gross", "negative")], "keep": 1}),
    (103, "R", {"rows": ["$ grep -r commission ~/scripts", ("hits", "0")]}),
    (104, "R", {"rows": [("fx_commission", "$0.25 / deal")]}),
    (105, "R", {"rows": [("fx_commission", "$0.25 / deal"), ("round_trip", "$0.50 / leg")], "keep": 1}),
    (109, "H", {"text": "#019 :: dealer_gamma_exposure"}),
    (110, "R", {"rows": ["# very cool. very quant-twitter."]}),
    (111, "R", {"rows": [("low_gamma_days", "trend"), ("high_gamma_days", "revert")]}),
    (112, "R", {"rows": ["$ grep -r commission ~/scripts"]}),
    (113, "R", {"rows": ["$ grep -r commission ~/scripts", ("hits", "0")], "keep": 1, "stamp": "ZERO"}),
    (114, "R", {"rows": [("spread", "modelled"), ("swap", "modelled"), ("slippage", "modelled"), ("impact", "modelled")]}),
    (115, "R", {"rows": [("spread", "modelled"), ("swap", "modelled"), ("slippage", "modelled"), ("impact", "modelled"), ("invoice", "..."), "# well well well"], "keep": 4}),
    (116, "H", {"text": "#019 :: dealer_gamma_exposure"}),
    (117, "R", {"rows": ["# theory:", ("low_gamma_days", "trend"), ("high_gamma_days", "revert")]}),
    (118, "R", {"rows": ["$ test index_intraday_seasonality", ("hours_surviving_mtc", "0")], "stamp": "DEAD"}),
    (119, "R", {"rows": [("low_gamma_days", "trend"), ("high_gamma_days", "revert")], "strike": 1}),
    (120, "R", {"rows": [("high_gamma_days", "quiet")]}),
    (122, "R", {"rows": ["$ race gex realised_vol --y ret_t+1", ("gex_t_stat", "...")]}),
    (123, "R", {"rows": ["$ race gex realised_vol --y ret_t+1", ("gex_t_stat", "-1.1"), ("past_5d_return", "does the work")], "keep": 1}),
    (124, "R", {"rows": [("ml_regime_model", "loses"), ("200d_moving_avg", "wins")]}),
    (125, "R", {"rows": [("auc_dev", "0.68"), ("auc_oos", "0.57"), "# holy molly"]}),
    (127, "R", {"rows": ["$ test cot_positioning", ("reversal_at_extremes", "real")]}),
    (130, "C", {"cmd": "$ plot fx_month_end_flow --from 2019", "shape": "up", "xl": "2019", "xr": "2025", "foot": "# looked great"}),
    (131, "C", {"cmd": "$ plot fx_month_end_flow --from 2003", "shape": "downthenup", "xl": "2003", "xr": "2025", "foot": "# the sign flipped"}),
    (133, "R", {"rows": ["$ fit regime_model --walk-forward --sealed-vault"]}),
    (134, "R", {"rows": ["$ test daily_stat_arb", ("wti_brent", "robust"), ("everything_else", "dead")]}),
    (137, "H", {"text": "#027 :: intraday_fx_stat_arb"}),
    (140, "R", {"rows": ["$ test cot_positioning", ("reversal_at_extremes", "real")]}),
    (141, "R", {"rows": ["$ test cot_positioning", ("reversal_at_extremes", "real"), ("swap", "killed it"), ("driver", "crude oil")], "keep": 2}),
    (142, "R", {"rows": ["# crude oil in a trench coat"]}),
    (143, "R", {"rows": ["$ backtest fx_month_end_flow", ("since_2019", "looks great")]}),
    (144, "R", {"rows": ["$ apply spreads --per-bar"]}),
    (145, "B", {"value": "+0.03%", "label": "a year, after spreads", "sub": "# gross sharpe was 3.71"}),
    (146, "R", {"rows": [("sign_2003_2019", "flipped"), "# a window artifact", "# a coincidence with a name"]}),
    (147, "R", {"rows": ["$ test daily_stat_arb", ("wti_brent", "robust")]}),
    (148, "R", {"rows": ["$ test daily_stat_arb", ("wti_brent", "robust"), ("oil_swap", "ate it"), ("everything_else", "dead gross")], "keep": 2}),
    (149, "H", {"text": "#027 :: intraday_fx_stat_arb"}),
    (150, "R", {"rows": ["# the one that keeps me up"]}),
    (151, "R", {"rows": [("information_coef", "+0.0205"), ("observations", "2.16M")]}),
    (152, "R", {"rows": ["$ run pool #028", ("net", "sub-economic")]}),
    (153, "R", {"rows": [("information_coef", "+0.0205"), ("observations", "2.16M"), ("z_score", "~30"), "# not noise. not a bug."], "keep": 2}),
    (154, "R", {"rows": [("gross_sharpe", "3.71"), "$ apply spreads --per-bar"]}),
    (155, "R", {"rows": [("gross_sharpe", "3.71"), "$ apply spreads --per-bar", ("net", "+0.03% / yr")], "keep": 2}),
    (156, "C", {"cmd": "$ plot ic_decay --bars 0..5", "shape": "decay", "xl": "bar 0", "xr": "bar 5", "foot": "decay ...... 75% in one bar"}),
    (157, "R", {"rows": ["# the spread is right there waiting", "$ build pool #028"]}),
    (158, "R", {"rows": ["# the book says: run opposing signals", "# and their trades cancel"]}),
    (159, "R", {"rows": ["$ run #030 --orders limit", ("spread_recovered", "~full")]}),
    (160, "R", {"rows": ["$ run pool #028", ("turnover_netted", "87%")]}),
    (161, "R", {"rows": ["$ run pool #028", ("turnover_netted", "87%"), ("net", "sub-economic")], "keep": 2}),
    (162, "R", {"rows": ["$ run pool #029 --pairs 12->28", ("gross", "up")]}),
    (163, "R", {"rows": ["$ run pool #029 --pairs 12->28", ("gross", "up"), ("net_sharpe", "-85")], "keep": 2, "stamp": "DEAD"}),
    (166, "R", {"rows": ["$ add spread_gate", ("net", "positive"), ("bars_traded", "1%")]}),
    (167, "R", {"rows": ["$ add spread_gate", ("net", "positive"), ("bars_traded", "1%"), ("annual_return", "~0%")], "keep": 3}),
    (168, "H", {"text": "#030 :: limit_order_salvage"}),
    (172, "R", {"rows": ["$ backtest #030 --costs 0", "# free. magic. perfect.", ("edge", "0.057 bp / signal")]}),
    (173, "R", {"rows": ["$ backtest #030 --costs 0", "# free. magic. perfect.", ("edge", "0.057 bp / signal"), ("annual", "~0.8%")], "keep": 3}),
    (175, "R", {"rows": [("required_latency", "flash + quicksilver")]}),
    (176, "R", {"rows": [("required_latency", "flash + quicksilver"), ("jane_street", "false"), "# yet"], "keep": 1}),
    (177, "R", {"rows": ["$ tag v1", "# deployed. boring. fine."]}),
    (181, "R", {"rows": ["$ build v2 --smarter"]}),
    (185, "B", {"value": "0.313", "label": "fraction of green nights", "sub": "# impossible"}),
    (187, "R", {"rows": [("swap_snapshot", "17:00 broker")]}),
    (188, "R", {"rows": [("swap_snapshot", "17:00 broker"), ("enter_after", "snapshot")], "keep": 1}),
    (189, "R", {"rows": [("swap_snapshot", "17:00 broker"), ("enter_after", "snapshot"), ("overnight_move", "most of it"), ("financing", "0")], "keep": 2}),
    (190, "R", {"rows": ["# two: raw overnight is long beta"]}),
    (191, "C", {"cmd": "$ plot overnight --gate ma200", "shape": "up", "xl": "1990", "xr": "2026", "foot": "# stops bleeding in bears"}),
    (192, "R", {"rows": [("sharpe", "0.47 -> 0.77")]}),
    (193, "R", {"rows": [("sharpe", "0.47 -> 0.77"), ("max_drawdown", "-20% -> -8.3%"), "$ deploy v1"], "keep": 1}),
    (195, "R", {"rows": ["# not wrong data.", "# absent data."]}),
    (197, "R", {"rows": ["$ new notebook v2", "[1] frac_green_nights()"]}),
    (199, "R", {"rows": ["$ new notebook v2", "[1] frac_green_nights()", ("out", "...")], "keep": 2}),
    (200, "R", {"rows": ["$ new notebook v2", "[1] frac_green_nights()", ("out", "0.313")], "keep": 2, "stamp": "IMPOSSIBLE"}),
    (203, "R", {"rows": ["$ inspect yahoo ^GSPC --field open"]}),
    (204, "R", {"rows": ["$ inspect yahoo ^GSPC --field open", ("pre_2014", "stale copies of close")], "keep": 1}),
    (205, "R", {"rows": [("zero_gap_rate_to_2005", "78-98%"), ("zero_gap_rate_2012_13", "25%")]}),
    (206, "R", {"rows": [("validation_#023", "36 years"), ("computed_on", "made-up opens")], "stamp": "FAKE"}),
    (210, "R", {"rows": ["$ rebuild --data SPY --prints real", ("nights", "8,262")]}),
    (211, "R", {"rows": ["$ rebuild --data SPY --prints real", ("nights", "8,262"), ("base_rate", "0.559")], "keep": 2}),
    (212, "B", {"value": "1.38", "label": "sharpe, filtered, real prints", "sub": "# survived. by luck."}),
    (214, "R", {"rows": [("dsr", "0.988"), ("bar", "0.95"), "$ deploy v2"]}),
    (215, "R", {"rows": ["# smaller effect and I'd be trading", "# a vendor's fill-forward for months"]}),
    (216, "R", {"rows": ["$ fit random_forest --v2"]}),
    (217, "R", {"rows": ["$ fit random_forest --v2", ("features", "30")], "keep": 1}),
    (218, "R", {"rows": [("features", "30, entry-knowable")]}),
    (219, "R", {"rows": [("features", "30, entry-knowable"), ("splits", "purged, chronological")], "keep": 1}),
    (220, "R", {"rows": [("features", "30, entry-knowable"), ("splits", "purged, chronological"), ("trials_logged", "72"), "# multiple testing charge: honest"], "keep": 2}),
]

CHART = {
    "up": [(0, .8), (.15, .78), (.3, .66), (.45, .6), (.6, .45), (.75, .38), (.9, .22), (1, .15)],
    "dipbounce": [(0, .3), (.35, .32), (.5, .8), (.6, .74), (.75, .4), (1, .35)],
    "diesafter": [(0, .8), (.2, .6), (.45, .3), (.55, .32), (.7, .34), (.85, .33), (1, .35)],
    "spikeflat": [(0, .8), (.1, .78), (.2, .2), (.3, .6), (.45, .7), (.7, .72), (1, .73)],
    "downthenup": [(0, .2), (.3, .45), (.6, .78), (.75, .6), (.9, .45), (1, .4)],
    "decay": [(0, .1), (.2, .72), (.4, .8), (.6, .83), (1, .85)],
}


def row_html(i, r):
    if isinstance(r, tuple):
        return f"<span class='row' id='r{i}'>{lead(*r)}</span>"
    cls = "cmt" if r.startswith("#") else "dim" if r.startswith("$") or r.startswith("[") else ""
    return f"<span class='row {cls}' id='r{i}'>{r}</span>"


def rows_slot(n, spec, dur):
    rows = spec["rows"]
    keep = spec.get("keep", 0)
    body = "<div class='scr'>" + "".join(row_html(i, r) for i, r in enumerate(rows)) + "<span class='cur' id='cur'></span></div>"
    tl = [f"tl.set('#r{i}', {{width: 'auto'}}, 0);" for i in range(keep)]
    typed = [f"'#r{i}'" for i in range(keep, len(rows))]
    budget = max(0.3, min(dur * 0.55, dur - 0.8))
    chars = sum(len(r if isinstance(r, str) else r[0] + r[1]) + 20 for r in rows[keep:]) or 1
    cps = max(45, chars / budget)
    tl.append(f"var end = typeRows(tl, [{', '.join(typed)}], 0.05, {cps:.0f}, 0.06);")
    tl.append(f"blink(tl, '#cur', end, {dur + 1:.2f});")
    if spec.get("stamp"):
        body += f"<div class='stamp' id='st'>{spec['stamp']}</div>"
        tl.append(f"stamp(tl, '#st', Math.min(end + 0.15, {max(0.2, dur - 0.9):.2f}));")
    if spec.get("strike"):
        body += "".join(f"<div class='strike' id='k{i}' style='left:150px;top:{130 + 51 * i + 26}px'></div>" for i in range(len(rows)))
        tl += [f"strike(tl, '#k{i}', 820, Math.min(end + 0.1, {max(0.2, dur - 0.9):.2f}) + {0.12 * i:.2f});" for i in range(len(rows))]
    return body, "\n".join(tl)


def chart_slot(n, spec, dur):
    pts = CHART[spec["shape"]]
    W, H = 1300, 400
    step = []
    for i, (x, y) in enumerate(pts):
        X, Y = round(x * W), round(y * H)
        step.append(f"{'M' if i == 0 else 'H'}{X}" + ("" if i == 0 else "") + (f" {Y}" if i == 0 else f" V{Y}"))
    d = " ".join(step)
    svg = (f"<svg class='plot' width='{W + 40}' height='{H + 60}'>"
           + "".join(f"<line class='grid' x1='0' x2='{W}' y1='{g}' y2='{g}'/>" for g in (100, 200, 300))
           + f"<path class='axis' d='M0 {H + 10} H{W}'/><path class='line' id='ln' d='{d}'/>"
           + f"<text x='0' y='{H + 45}'>{spec['xl']}</text><text x='{W}' y='{H + 45}' text-anchor='end'>{spec['xr']}</text></svg>")
    body = (f"<div class='scr'><span class='row dim' id='r0'>{spec['cmd']}</span></div>{svg}"
            f"<div class='foot' id='ft'>{spec['foot']}</div>")
    tl = ["var end = typeRow(tl, '#r0', 0.05, 70);",
          f"drawLine(tl, '#ln', end, {max(0.4, min(dur * 0.5, dur - 1.0)):.2f});",
          f"reveal(tl, '#ft', {max(0.3, min(dur * 0.6, dur - 0.8)):.2f});"]
    return body, "\n".join(tl)


def big_slot(n, spec, dur):
    v = spec["value"]
    body = (f"<div class='scr'><div class='hdr'>{spec['label'].upper()}</div>"
            f"<div class='big' id='v'>{v}</div><div class='sub' id='sb'>{spec['sub']}</div></div>")
    num = v.replace("%", "").replace("+", "")
    tl = []
    try:
        target = float(num)
        dec = len(num.split(".")[1]) if "." in num else 0
        tl.append(f"countUp(tl, '#v', {target}, 0.05, {max(0.3, min(0.8, dur * 0.4)):.2f}, {dec}, '{'+' if v.startswith('+') else ''}', '{'%' if v.endswith('%') else ''}');")
    except ValueError:
        tl.append("reveal(tl, '#v', 0.05);")
    tl.append(f"reveal(tl, '#sb', {max(0.2, min(dur * 0.5, dur - 0.8)):.2f});")
    return body, "\n".join(tl)


def header_slot(n, spec, dur):
    body = f"<div class='scr'><span class='row' id='r0' style='font-size:56px'>{spec['text']}</span><span class='cur' id='cur'></span></div>"
    tl = f"var end = typeRow(tl, '#r0', 0.1, {max(30, len(spec['text']) / max(0.3, dur * 0.5)):.0f});\nblink(tl, '#cur', end, {dur + 1:.2f});"
    return body, tl


def overlay_slot(n, caption, dur):
    body = f"<div class='card'><span class='row' id='r0'>{caption}</span></div>"
    return body, f"typeRow(tl, '#r0', 0.05, {max(40, len(caption) / max(0.3, dur * 0.4)):.0f});"


def main():
    SLOTS.mkdir(parents=True, exist_ok=True)
    for f in SLOTS.glob("*.json"):
        f.unlink()
    fns = {"R": rows_slot, "C": chart_slot, "B": big_slot, "H": header_slot}
    mg = {s["shot_number"] for s in PLAN["shots"] if s["visual"]["type"] == "MOTION_GRAPHICS"}
    specced = set()
    for n, layout, spec in SPECS:
        if n not in mg:
            continue
        body, tl = fns[layout](n, spec, DUR[n])
        (SLOTS / f"{n}.json").write_text(json.dumps({"key": str(n), "flavor": "full_frame", "duration": DUR[n],
                                                      "body": body, "timeline": tl}), encoding="utf-8")
        specced.add(n)
    for s in PLAN["shots"]:
        if s.get("overlay") and s["overlay"].get("caption") and s["visual"]["type"] != "MOTION_GRAPHICS":
            n = s["shot_number"]
            body, tl = overlay_slot(n, s["overlay"]["caption"], DUR[n])
            (SLOTS / f"{n}-overlay.json").write_text(json.dumps({"key": f"{n}-overlay", "flavor": "overlay",
                                                                 "duration": DUR[n], "body": body, "timeline": tl}), encoding="utf-8")
    print(json.dumps({"specced": len(specced), "mg_shots": len(mg), "missing": sorted(mg - specced)}))


if __name__ == "__main__":
    main()
