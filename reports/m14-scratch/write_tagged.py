import pathlib
ROOT = pathlib.Path(r"C:\Users\User\ESTA-v3\sessions")
T = {
"the-clock-was-wrong-2026-10-13": """[HOOK]
{happy, proud} I passed a *sealed* test. First time ever.
{happy, excited | pace: fast} Rules written down before I looked, data nobody had touched, t-stat of nine point five.
{happy, amused | pause: 300} I was a genius.
{sad, deflated | pace: slow | pause: 500} For about three days.

[BODY]
{calm} The idea: when buyers on Binance pile in, the pile keeps going for a few minutes. So ride it on FTMO.
{happy, excited} Plus 1.07 basis points a trade, *ten* times the cost.
{happy, amused | pause: 600} Champagne.
{calm, afraid | pause: 300} Then I checked the clock.
{surprised, afraid | pause: 400} Sheeiiii.
{calm | pace: fast} FTMO stamps its prices in server time, so I converted them to Athens time.
{disgusted, angry} Except the broker doesn't change its clocks when Athens does.
{sad, melancholic | pause: 400} Two windows a year, my FTMO prices were sitting an *hour* behind.
{surprised} And 99.7 percent of the profit lived in *exactly* those windows.
{calm, sad} Fixed the clock, ran it again.
{sad, melancholic | pace: slow | pause: 300} Minus 0.17.
{sad, disgusted | pause: 600} Gone.

[CTA]
{melancholic, amused} Nine point five t-stat, built on being an hour late.
{calm, amused} I'm not even mad.
{angry, amused | pace: fast} Okay, I'm a bit mad.
""",
"fade-the-crowd-2026-10-13": """[HOOK]
{calm} Every five minutes, Binance publishes how many accounts are betting Bitcoin goes up.
{happy, amused | pause: 400} And on paper, the crowd is *reliably* wrong.

[BODY]
{calm} I read it through a poker book. The Mathematics of Poker.
{happy, amused | pause: 300} Treat the crowd like a table of bad players, and bet against them.
{happy, excited | pace: fast} On two and a half years of training data, it worked everywhere. Every window, every horizon, same sign.
{happy, proud | pause: 400} Thirty fake versions on scrambled data, and not *one* beat it.
{calm, afraid | pause: 300} Then the validation year.
{surprised} The edge didn't fade. It *flipped*. Same size, opposite sign.
{surprised, afraid | pause: 300} Holy molly.
{sad, melancholic | pause: 500} I traded the old sign for eight months.
{disgusted, sad} And the model couldn't notice, because I built it to *never* forget.
{angry, disgusted} That setting won on training. Of course it did.
{calm, melancholic | pace: slow | pause: 500} Forgetting only pays when something changes.

[CTA]
{calm} Poker hands you the odds. Markets make you guess them.
{happy, amused} Arc's still open though. I'm not folding yet.
""",
"five-ways-backtest-lies-2026-10-13": """[HOOK]
{happy, amused} Five ways to make your backtest *lie* to you.
{calm, amused | pause: 500} I've done all five, so trust me.

[BODY]
{calm | pause: 200} Number one. Forget the commission.
{amused, happy | pace: fast} Model the spread, the swap, the slippage. Just not the invoice.
{disgusted, sad | pause: 400} I did this *twice*. On crypto it was 94 percent of my cost.
{calm | pause: 200} Number two. Trust the vendor.
{disgusted, angry} Yahoo's old S&P opening prices are just copies of the previous close.
{sad, melancholic | pause: 400} Three decades of my validation, on numbers that never existed.
{calm | pause: 200} Number three. Trust the clock.
{amused, disgusted | pace: fast} The broker says Athens time. The broker's daylight saving says otherwise.
{sad, amused | pause: 400} Your sealed test pass is now an hour of hindsight.
{calm | pause: 200} Number four. Check the rows, not the columns.
{surprised} Every file had all 288 rows. The columns inside were *blank*.
{sad, afraid | pause: 400} Requiring them deleted 87 percent of the only bear market.
{calm | pause: 200} Number five. Kill ideas early.
{melancholic, sad | pause: 500} Six of my verdicts got reversed. All six were premature kills.

[CTA]
{happy, amused} Follow for part two. There will be a part two.
{melancholic, amused | pace: slow} Unfortunately.
""",
"the-label-was-the-defect-2026-10-13": """[HOOK]
{calm} A hundred and eleven models. Straight lines, forests, everything.
{disgusted, sad | pause: 400} Every single one landed between 0.53 and 0.58.

[BODY]
{calm, melancholic} So the edge can't be made bigger. Fine.
{surprised | pause: 400} But my label was asking the *wrong* question.
{calm} It asked: did price move a full volatility, about two hundred basis points, in twelve hours?
{calm | pause: 300} The question that pays is smaller.
{calm, happy} Would this trade have cleared the toll? About *ten* basis points.
{happy, excited | pause: 300} So I rewrote the label. Profitable after cost.
{happy, surprised} Long is good on 48 percent of bars, not 27.
{happy, excited | pace: fast} Edge per trade: 5.96 to 19.95.
{happy, amused | pause: 200} Pewwww. Tripled.
{happy, proud} And for the first time, the more confident the model got, the more often it was right.
{happy, calm | pause: 500} 50, 56, 61 percent.

[CTA]
{calm, melancholic} It still missed my bar. But it got closer than anything before it.
{calm | pace: slow} Same data, same models. Different question.
""",
}
for sid, t in T.items():
    (ROOT / sid / "script.tagged.md").write_text(t, encoding="utf-8")
    print(sid)
