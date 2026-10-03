[HOOK]
so Alphas...nah not these guys [Andrew Tate picture]
  Or these guys[wolves picture]
  This...fucking...annoying ass shit...you see these ones wouldn't drive you to edge of the world questioning your sanity and intelligence and make you stare at the ceiling at question your while existence from the moment you ran from your dad's balls and spun into the world...goodness gracious

  Sorry I went off on a tangent there but yh so, let's talk about alphas

  "Fundamentally, an alpha is an idea about how the market works. Concretely, it's an automated predictive model that decodes some market relation... It contains rules that convert input data → positions/trades in the securities markets."
 — Igor Tulchinsky, Finding Alphas (WorldQuant/Wiley, 2020)

  Thanks Tulch
  I love money you love money we all love money so why not do some maths and make some money sounds easy doesn't it well, sike I've been writing maths equations to find these alphas for the past 2 months and I might be convinced they don't exist

[BODY]
Started where everyone starts. Short-term reversal. Stock drops relative to its peers, you buy it, it bounces, you're a genius. It's in every paper. Lehmann 1990. It's practically folklore.

Ran it on the S&P 100. Gross Sharpe 0.05. Hmmm ok bad . hmmm maybe reversal lives in illiquid names, and the S&P 100 is the most picked-over stretch of water on earth. Fine. Moved to mid-caps. Pewwww, Gross Sharpe jumped 0.05 → 0.445. Beautiful.

Net Sharpe: 0.058. sheeiiii

The strategy traded 143 times a year and paid a spread every single time. I added signal decay to slow it down, kept 94% of the edge, cut costs 26%, and got net Sharpe 0.126 with a 40% drawdown. For about 1% a year. [slightly stressed picture]

Then I sector-neutralised it to reduce risk and it deleted the signal, because the sector-level move was the edge. Tripled the vol, lowered the gross.
Ok  lets switch locations

Ran the same reversal on crypto expecting it to be stronger, more retail presence, 24/7, degenerate[degenerate crypto bro picture]
 
Got gross Sharpe −1.01. Beautifully, catastrophically wrong. [more stressed picture]
But wait! flip it, crypto doesn't revert, it trends. #006, crypto 30-day momentum, net Sharpe 1.10, positive in 7 of 8 years including the 2022 bear.

I'm a fucking genius, where Einstein at? rolling in his grave [happy guy]
Then I ran it on the FTMO's 14 coin CFD....don't ask me why i'm trying to trade prop firms, their a scam blah blah blah, well...I need to start somewhere init.
 Net Sharpe 0.38.
Ok slightly bad, Then I went and measured the actual swap. Crypto CFD: 30% a year, per side. I'd stress-tested it at 15% as my worst case. Reality was double my worst case.

Ok I don't seem to be getting anywhere solely based on my own ideas, so...lets go jack some ideas then, Stand on the shoulders of giants and all that. Hey Einstein I take what I said back[hands up in defeat]
So I went looking for papers.

BTC intraday trend: dead at the decay check. US500 first-half-hour into last-half-hour: dead at the decay check. US500 overnight drift: dead at the decay check. Three for three. The pattern is there in the paper's sample window and gone afterwards, every time, like clockwork.

DUhhhh…If I can read it, everyone can read it. The half-life of a published anomaly is roughly "publication."

Multi-asset trend across 45 instruments: dead, and not from cost — those instruments just don't trend. BTC weekly trend: gross +0.95% a week, genuinely real, eaten by 0.577% a week of swap, and the leftover profit was 100% the 2017 mania.

FX time-of-day seasonality. Three pairs. Short at 21:00, long at 23:00 London. Backtest net Sharpe 5.28. +12.5% a year. Five out of five out-of-sample years positive. It held on currencies I never fit it on. Costs weren't guessed, I pulled tick data and measured the real spread hour by hour. Swap-free by design. EINNNSTEIIINNNN!!!!

This cleared a prop firm's target organically. No leverage games.

Deployed it.
How did it actually do? 
Well...Half the edge wasn't real. The 21:00 session had been measured on bid quotes and when I redid it properly the book was Sharpe ~1.0, not 5.3. A quoting artifact I had built a strategy on top of.

The live edge was zero. Not smaller. Zero. Gross negative.
FTMO charges a commission on FX. 25 cents a deal. 50 cents a leg round trip. On my size that's 2.00 bp a night across three legs, against an expected edge of 1.24 bp a night. Negative before it opened the first trade. I grepped every script I'd ever written for a commission term. Zero hits. I had been modelling spread, swap, slippage, impact and just... not the invoice.

Well well well I cant give up now might as well keep going

Went to options dealer positioning. Gamma exposure. Very cool, very quant-twitter. The theory: low-gamma days trend, high-gamma days revert.

The reverting half doesn't exist. High-gamma days are just quiet. And when I raced GEX against boring free realised volatility to predict tomorrow's return, GEX's t-stat collapsed to −1.1 and past-5-day return did all the work. The expensive data was a worse proxy for short-term reversal than the price itself.

Index intraday seasonality: zero hours survive multiple-testing correction. FX day-of-week: t of 1.75, plausible, not significant, and the pairs contradict each other. 
Ok lets seek the help of the machines now, [Machine gun meme]
Machine learning regime model, walk-forward, sealed vault, all done properly...take that, boom boom boom... 
loses to a 200-day moving average. AUC 0.68 in development, 0.57 out of sample. Holy molly

- COT positioning. Real reversal at extremes. Swap-killed, and the entire effect was crude oil in a trenchcoat.
- Month-end FX rebalancing flow. Looked great 2019+. Pulled 2003–2019 and the sign flipped. A window artifact, i.e. I'd found a coincidence and given it a name.
- Daily statistical arbitrage. WTI–Brent was the only robust pair. Oil swap ate it. Everything else was dead gross.
- Intraday FX stat-arb [label: #027]. This is the one that keeps me up. Information coefficient of +0.0205 on 2.16 million observations. That's about thirty standard errors from zero. It is not noise, it is not a bug, Gross Sharpe 3.71. After real per-bar spreads: +0.03% a year. It decays 75% in one bar, so you have to trade it instantly, and the spread is right there waiting.
- So I built a pool [label: #028], because the book says if you run opposing signals together their trades cancel and you stop paying the toll. Guess what — it works. 87% of the turnover netted out. And the pool was still sub-economic. Widened it from 12 to 28 pairs [label: #029], gross went up, net went to −85 Sharpe, because the extra breadth came from crosses with 3 bp spreads. Added a spread gate, which flips it positive and then trades 1% of available bars, which is roughly 0% a year.
- Final salvage [label: #030]: use limit orders, become a maker instead of a taker, get the spread back. It works. Limits recover essentially the full spread. And then I measured the ceiling — what this thing earns with execution costs set to zero, free, magic, perfect — and it's 0.057 bp per signal. Call it 0.8% a year in a universe where friction doesn't exist. You'd need some absolute superhuman flash + quicksilver type speed. And I aint Jane street...well not yet.

Well turns out the only thing that worked was simply buy the S&P overnight. That's it. That's the whole idea. Close to open, go home flat.

Two wrinkles make it mine. One: swap is only charged on positions open at the broker's 17:00 rollover snapshot, so if you enter after the snapshot you get most of the overnight move and pay zero financing. Two: raw overnight is just long beta pump-faking, so gate it with the 200-day moving average and it stops bleeding in bears. Sharpe 0.47 → 0.77, drawdown −20% → −8.3%.

That's v1. Deployed. Boring. Fine.

Then I tried to make it smarter.

First, the notebook caught me trading on prices that never existed. Cell 1 of the new build had one sanity line in it: what fraction of nights are green? It came back 0.313. That's impossible. The market goes up overnight more often than that, everyone knows it, that's the whole premise.

Yahoo's opening prints for ^GSPC(the S&P index feed, not the ETF) are fake before roughly 2014. They're stale copies of the previous close. Zero-gap rate of 78-98% a year through 2005 and still 25% in 2012-13. Which means my beautiful 36-year validation of #023 had been computed across three decades of a number the vendor made up. Not wrong data. Absent data, silently padded.

Rebuilt it on SPY, the actual ETF, actual prints. 8,262 real nights. Base rate 0.559. The strategy survived, and got better (Sharpe 1.38 filtered on the real prints). But it survived by luck. If the effect had been smaller I'd have been trading a vendor's fill-forward for months.

Then, v2: put a random forest on it. 30 features, all entry-knowable, purged chronological splits, 72 logged trials so the multiple-testing charge is honest. Champion model on a sealed 2021-26 window it had never seen: +3.21 bp/night vs +1.76 for always-long, Sharpe 0.90 vs 0.44, ahead in every year, +1.0 in 2022 while the baseline did −6.7.

Deflated Sharpe ratio: 0.887. My bar is 0.95. The frozen model did not graduate. So I walked forward the recipe instead — freeze the features and hyperparameters, refit every January, never peek. 2,870 out-of-sample nights: +3.59 vs +2.13, Sharpe 0.96, positive in all 12 years. DSR 0.988. That graduates. Deployed as v2.

And I plugged SHAP to it to actually see what the model learned. Dip-buying, confirmed by trend, plus high VIX is bullish.

[CTA]
So I did finally find something and I guess this is evidence that alpha maybe....exists?
