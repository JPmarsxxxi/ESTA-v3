import json, datetime, pathlib, re
now = datetime.datetime.now().isoformat()
LOG = "C:/Users/User/finding-alphas/alpha_log.md"
ROOT = pathlib.Path(r"C:\Users\User\ESTA-v3")
scripts = {
"the-clock-was-wrong-2026-10-13": ("""[HOOK]
I passed a sealed test. First time ever. Rules written down before I looked, data nobody had touched, t-stat of nine point five. I was a genius. For about three days.

[BODY]
The idea: when buyers on Binance pile in, the pile keeps going for a few minutes. So ride it on FTMO. Plus 1.07 basis points a trade, ten times the cost. Champagne.

Then I checked the clock. Sheeiiii. FTMO stamps its prices in server time, so I converted them to Athens time. Except the broker doesn't change its clocks when Athens does. Two windows a year, my FTMO prices were sitting an hour behind.

And 99.7 percent of the profit lived in exactly those windows. Fixed the clock, ran it again. Minus 0.17. Gone.

[CTA]
Nine point five t-stat, built on being an hour late. I'm not even mad. Okay, I'm a bit mad.
""", [
 ("#044 flow-imbalance continuation passed a pre-registered sealed-half test: +1.07 bp, t 9.5, 9.8x cost", "alpha_log.md #044 sealed test table (variant B IMB)"),
 ("FTMO time_msc is stamped in server time; Europe/Athens localisation was used, but the broker's DST calendar differs from Athens in ~Oct 26-Dec 8 and ~Mar 8-Mar 29, so FTMO prices sat 60 min behind", "alpha_log.md #044 continued 2026-08-22/23, clock bug #2"),
 ("99.7% of the +1.076 came from the cross-venue basis closing; P&L sat in Oct and Mar, the two disagreement windows", "alpha_log.md #044 continued, 'Where did the headline live'"),
 ("Re-run on the clock-fixed series: -0.169 bp per round trip (t -0.4)", "alpha_log.md #044 continued, re-run x070"),
 ("Sealed pass logged 2026-08-19/20, second clock bug found 2026-08-22/23 (about three days)", "alpha_log.md session headers"),
], ["The backward-looking-hour mechanism is NOT yet directly tested (the +-60 min re-injection test is outstanding); the script states only what was measured.", "The arc is open, not a verdict (findings-vs-verdicts rule)."]),
"fade-the-crowd-2026-10-13": ("""[HOOK]
Every five minutes, Binance publishes how many accounts are betting Bitcoin goes up. And on paper, the crowd is reliably wrong.

[BODY]
I read it through a poker book. The Mathematics of Poker. Treat the crowd like a table of bad players, and bet against them.

On two and a half years of training data, it worked everywhere. Every window, every horizon, same sign. Thirty fake versions on scrambled data, and not one beat it.

Then the validation year. The edge didn't fade. It flipped. Same size, opposite sign. Holy molly. I traded the old sign for eight months.

And the model couldn't notice, because I built it to never forget. That setting won on training. Of course it did. Forgetting only pays when something changes.

[CTA]
Poker hands you the odds. Markets make you guess them. Arc's still open though. I'm not folding yet.
""", [
 ("Signal: Binance count_long_short_ratio (share of accounts long vs short, BTCUSDT perps, 5m), 7-day z-score, traded as fade the crowd", "alpha_log.md #047 'The signal'"),
 ("Lens: Chen & Ankenman, The Mathematics of Poker", "alpha_log.md #047 header"),
 ("TRAIN 2020-09 to 2023-03: IC same sign at all windows and horizons; 0 of 30 permutation nulls beat it, p = 0.032", "alpha_log.md #047 'What was measured', 'Two nulls'"),
 ("12h IC inverted: TRAIN -0.0874 to VAL +0.0893, same magnitude opposite sign; 'We traded the old sign for eight months' (VAL 251 days)", "alpha_log.md #047 'THE IC DID NOT DECAY - IT INVERTED'"),
 ("Shipped lambda = 1.0 (never forget) because it scored best on TRAIN; forgetting only costs when nothing changes", "alpha_log.md #047 'Why it could not adapt'"),
 ("The lens is about deciding given a probability, not producing one: in poker the deck supplies it", "alpha_log.md #047 'What the lens gave'"),
], ["Arc #047 is open; findings only, no verdict."]),
"five-ways-backtest-lies-2026-10-13": ("""[HOOK]
Five ways to make your backtest lie to you. I've done all five, so trust me.

[BODY]
Number one. Forget the commission. Model the spread, the swap, the slippage. Just not the invoice. I did this twice. On crypto it was 94 percent of my cost.

Number two. Trust the vendor. Yahoo's old S&P opening prices are just copies of the previous close. Three decades of my validation, on numbers that never existed.

Number three. Trust the clock. The broker says Athens time. The broker's daylight saving says otherwise. Your sealed test pass is now an hour of hindsight.

Number four. Check the rows, not the columns. Every file had all 288 rows. The columns inside were blank. Requiring them deleted 87 percent of the only bear market.

Number five. Kill ideas early. Six of my verdicts got reversed. All six were premature kills.

[CTA]
Follow for part two. There will be a part two. Unfortunately.
""", [
 ("Commission never modelled twice: #016 FX (25 cents a deal) and #045 crypto, where the 0.0325%/side commission was 94% of the cost", "alpha_log.md #045 through the engine; #016 live review 2026-08-13"),
 ("Yahoo ^GSPC opening prints before ~2014 are stale copies of the previous close; the 36-year #023 validation ran across three decades of them", "alpha_log.md 2026-07-17 FAKE-OPEN TRAP"),
 ("FTMO prices are in server time; Athens DST calendar is not the broker's, and the #044 sealed pass did not survive the fix", "alpha_log.md #044 continued"),
 ("Binance archive files have all 288 rows but blank top-trader columns for ~all of 2022; requiring all 23 features deletes 87% of the only bear market", "alpha_log.md #046 DATA TRAP"),
 ("Six premature verdicts were later reversed, every one a premature negative", "alpha_log.md FINDINGS vs VERDICTS"),
], []),
"the-label-was-the-defect-2026-10-13": ("""[HOOK]
A hundred and eleven models. Straight lines, forests, everything. Every single one landed between 0.53 and 0.58.

[BODY]
So the edge can't be made bigger. Fine. But my label was asking the wrong question.

It asked: did price move a full volatility, about two hundred basis points, in twelve hours?

The question that pays is smaller. Would this trade have cleared the toll? About ten basis points.

So I rewrote the label. Profitable after cost. Long is good on 48 percent of bars, not 27.

Edge per trade: 5.96 to 19.95. Pewwww. Tripled. And for the first time, the more confident the model got, the more often it was right. 50, 56, 61 percent.

[CTA]
It still missed my bar. But it got closer than anything before it. Same data, same models. Different question.
""", [
 ("111 model fits, every architecture from a straight line to an unlimited-depth forest, AUC 0.53-0.58", "alpha_log.md 2026-09-01/02 header"),
 ("Triple-barrier label demanded a 1-vol (~200 bp) move in 12h; cost is ~10 bp, 7.4% of a typical 12h move", "alpha_log.md 'THE LABEL WAS THE DEFECT'"),
 ("'Long is good' share: 26.8% old label vs 47.8% profitable-after-cost", "alpha_log.md 'THE LABEL WAS THE DEFECT'"),
 ("New label tripled edge/trade 5.96 to 19.95 bp; hit rate rose with confidence 50.4 to 56.2 to 60.8%, first time any model produced that", "alpha_log.md header + cell_09"),
 ("All three candidates still fail the 0.90 bar, at 0.82-0.84", "alpha_log.md 2026-09-01/02 header"),
], []),
}
for sid, (text, facts, oq) in scripts.items():
    d = ROOT / "sessions" / sid
    req = json.loads((d / "requirements.json").read_text(encoding="utf-8"))
    (d / "research.json").write_text(json.dumps({"session_id": sid, "researched_at": now, "topic_query": req["topic"],
        "context_summary": "Canon is the user's own research log (finding-alphas/alpha_log.md); every claim below is checked against the cited section of that log, not the web. The log's findings-vs-verdicts rule applies: open arcs are stated as findings.",
        "key_facts": [{"claim": c, "status": "verified", "confidence": "high", "evidence": src,
                       "sources": [{"url": LOG, "title": "alpha_log.md (user's research log)", "snippet": src}], "flag": ""} for c, src in facts],
        "open_questions": oq, "sources_seen": [LOG]}, indent=1), encoding="utf-8")
    secs = {k: re.search(rf"\[{k}\]\n(.*?)(?=\n\[|\Z)", text, re.S).group(1).strip() for k in ("HOOK", "BODY", "CTA")}
    wc = {k: len(v.split()) for k, v in secs.items()}
    (d / "script.md").write_text(text, encoding="utf-8")
    (d / "script_metadata.json").write_text(json.dumps({"session_id": sid, "written_at": now, "target_word_count": 120,
        "target_hook": 20, "target_body": 80, "target_cta": 20, "final_word_count": sum(wc.values()),
        "final_hook_words": wc["HOOK"], "final_body_words": wc["BODY"], "final_cta_words": wc["CTA"],
        "talking_points": [], "talking_points_regens": 0, "script_regens": 0, "user_edited_talking_points": False,
        "user_finalized": False, "user_skipped_humanization": False, "ai_draft": text, "humanized_draft": text,
        "research_sources": [LOG], "example_scripts_used": 0, "llm_provider": "claude",
        "note": "Unattended overnight test: word target 120 for 60 s because the user's clone reads at ~117 wpm (do-alphas: 1650 words in 843 s). Voice anchored on the user's do-alphas script."}, indent=1), encoding="utf-8")
    print(sid, wc, sum(wc.values()))
