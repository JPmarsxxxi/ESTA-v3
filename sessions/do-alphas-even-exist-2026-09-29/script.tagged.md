[HOOK]
{disgusted, unimpressed} so Alphas...nah not these guys [Andrew Tate picture]
{disgusted, unimpressed | pause: 400} Or these guys[wolves picture]
{angry, exasperated | pace: fast} This...fucking...annoying ass shit...you see these ones wouldn't drive you to edge of the world questioning your sanity and intelligence and make you stare at the ceiling at question your while existence from the moment you ran from your dad's balls and spun into the world
{disgusted, weary | pace: slow | pause: 600} ...goodness gracious
{amused, calm | pause: 500} Sorry I went off on a tangent there but yh so, let's talk about alphas
{calm | pace: slow | voice: preset_brit_male_12s} "Fundamentally, an alpha is an idea about how the market works. Concretely, it's an automated predictive model that decodes some market relation...
{calm | pace: slow | voice: preset_brit_male_12s | pause: 400} It contains rules that convert input data to positions/trades in the securities markets."
{calm | pause: 500} Igor Tulchinsky, Finding Alphas (WorldQuant/Wiley, 2020)
{amused, happy | pause: 600} Thanks Tulch
{happy, amused | pace: fast} I love money you love money we all love money so why not do some maths and make some money sounds easy doesn't it
{disgusted, deflated | pace: slow} well, sike I've been writing maths equations to find these alphas for the past 2 months and I might be convinced they *don't exist*

[BODY]
{calm} Started where everyone starts. Short-term reversal.
{amused, happy} Stock drops relative to its peers, you buy it, it bounces, you're a *genius*.
{calm | pause: 400} It's in every paper. Lehmann 1990. It's practically folklore.
{calm} Ran it on the S&P 100. Gross Sharpe 0.05.
{disgusted, unimpressed | pace: slow} Hmmm ok bad .
{calm, thinking} hmmm maybe reversal lives in illiquid names, and the S&P 100 is the most picked-over stretch of water on earth. Fine. Moved to mid-caps.
{surprised, happy} Pewwww, Gross Sharpe jumped 0.05 to 0.445. *Beautiful*.
{sad, disgusted | pace: slow} Net Sharpe: 0.058. [pause: 400] sheeiiii
{calm} The strategy traded 143 times a year and paid a spread *every single time*.
{calm} I added signal decay to slow it down, kept 94% of the edge, cut costs 26%, and got net Sharpe 0.126 with a 40% drawdown.
{disgusted, deflated | pace: slow} For about *1%* a year. [slightly stressed picture]
{disgusted, weary} Then I sector-neutralised it to reduce risk and it *deleted* the signal, because the sector-level move was the edge. Tripled the vol, lowered the gross.
{calm, resigned | pause: 400} Ok  lets switch locations
{happy, hopeful} Ran the same reversal on crypto expecting it to be stronger, more retail presence, 24/7, degenerate[degenerate crypto bro picture]
{disgusted, amused | pace: slow} Got gross Sharpe minus 1.01. [pause: 400] *Beautifully*, catastrophically *wrong*. [more stressed picture]
{surprised, happy | pace: fast} But wait! flip it, crypto doesn't revert, it *trends*.
{happy} number 006, crypto 30-day momentum, net Sharpe 1.10, positive in 7 of 8 years including the 2022 bear.
{happy, amused | pace: fast} I'm a fucking *genius*, where Einstein at? [pause: 300] rolling in his grave [happy guy]
{calm} Then I ran it on the FTMO's 14 coin CFD....
{amused, disgusted | pace: fast} don't ask me why i'm trying to trade prop firms, their a scam blah blah blah, well...I need to start somewhere init.
{sad, deflated} Net Sharpe 0.38.
{calm} Ok slightly bad, Then I went and measured the actual swap.
{surprised, disgusted} Crypto CFD: *30%* a year, per side.
{disgusted, weary | pace: slow} I'd stress-tested it at 15% as my worst case. Reality was *double* my worst case.
{calm, resigned} Ok I don't seem to be getting anywhere solely based on my own ideas, so...lets go jack some ideas then, Stand on the shoulders of giants and all that.
{amused, happy} Hey Einstein I take what I said back[hands up in defeat]
{calm | pause: 400} So I went looking for papers.
{disgusted, flat | pace: slow} BTC intraday trend: *dead* at the decay check. [pause: 300] US500 first-half-hour into last-half-hour: *dead* at the decay check. [pause: 300] US500 overnight drift: *dead* at the decay check.
{disgusted, weary} Three for three. The pattern is there in the paper's sample window and gone afterwards, every time, like clockwork.
{amused, disgusted} DUhhhh…If I can read it, *everyone* can read it.
{calm | pause: 400} The half-life of a published anomaly is roughly "publication."
{disgusted, flat} Multi-asset trend across 45 instruments: dead, and not from cost — those instruments just don't trend.
{sad, weary} BTC weekly trend: gross +0.95% a week, genuinely real, eaten by 0.577% a week of swap, and the leftover profit was *100%* the 2017 mania.
{calm} FX time-of-day seasonality. Three pairs. Short at 21:00, long at 23:00 London.
{surprised, happy} Backtest net Sharpe *5.28*. +12.5% a year. Five out of five out-of-sample years positive.
{happy} It held on currencies I never fit it on. Costs weren't guessed, I pulled tick data and measured the real spread hour by hour. Swap-free by design.
{happy, surprised | pace: fast | pause: 400} EINNNSTEIIINNNN!!!!
{happy, calm | pause: 500} This cleared a prop firm's target organically. No leverage games.
{calm | pause: 600} Deployed it.
{calm | pause: 500} How did it actually do?
{sad, disgusted | pace: slow} Well... [pause: 400] Half the edge wasn't real.
{calm, weary} The 21:00 session had been measured on bid quotes and when I redid it properly the book was Sharpe about 1.0, not 5.3.
{disgusted, weary | pause: 400} A quoting artifact I had built a strategy on top of.
{sad, disgusted | pace: slow} The live edge was *zero*. [pause: 400] Not smaller. [pause: 300] *Zero*. Gross negative.
{calm} FTMO charges a commission on FX. 25 cents a deal. 50 cents a leg round trip.
{disgusted} On my size that's 2.00 bp a night across three legs, against an expected edge of 1.24 bp a night.
{disgusted, weary} *Negative* before it opened the first trade.
{sad, amused} I grepped every script I'd ever written for a commission term. [pause: 400] Zero hits.
{disgusted, weary | pace: slow} I had been modelling spread, swap, slippage, impact and just... [pause: 400] not the *invoice*.
{amused, calm | pause: 400} Well well well I cant give up now might as well keep going
{calm} Went to options dealer positioning. Gamma exposure.
{amused, happy} Very cool, very quant-twitter.
{calm | pause: 300} The theory: low-gamma days trend, high-gamma days revert.
{disgusted, flat} The reverting half *doesn't exist*. High-gamma days are just quiet.
{calm} And when I raced GEX against boring free realised volatility to predict tomorrow's return, GEX's t-stat collapsed to minus 1.1 and past-5-day return did all the work.
{amused, disgusted} The expensive data was a *worse* proxy for short-term reversal than the price itself.
{disgusted, flat} Index intraday seasonality: *zero* hours survive multiple-testing correction.
{disgusted, weary} FX day-of-week: t of 1.75, plausible, not significant, and the pairs contradict each other.
{calm, determined | pause: 300} Ok lets seek the help of the machines now, [Machine gun meme]
{happy, confident | pace: fast} Machine learning regime model, walk-forward, sealed vault, all done properly...take that, boom boom boom...
{surprised, disgusted | pace: slow} loses to a *200-day moving average*.
{disgusted} AUC 0.68 in development, 0.57 out of sample. [pause: 400] Holy molly
{calm} COT positioning. Real reversal at extremes.
{amused, disgusted} Swap-killed, and the entire effect was crude oil in a *trenchcoat*.
{calm} Month-end FX rebalancing flow. Looked great 2019+.
{disgusted, weary} Pulled 2003 to 2019 and the sign *flipped*.
{amused, sad} A window artifact, i.e. I'd found a coincidence and given it a name.
{calm} Daily statistical arbitrage. WTI-Brent was the only robust pair.
{disgusted, flat} Oil swap ate it. Everything else was dead gross.
{calm} Intraday FX stat-arb [label: #027].
{sad, melancholic | pace: slow | pause: 400} This is the one that keeps me up.
{surprised, calm} Information coefficient of +0.0205 on 2.16 million observations. That's about *thirty* standard errors from zero.
{calm, insistent} It is not noise, it is not a bug, Gross Sharpe 3.71.
{disgusted, deflated | pace: slow} After real per-bar spreads: [pause: 300] +0.03% a year.
{disgusted, weary} It decays 75% in one bar, so you have to trade it *instantly*, and the spread is right there waiting.
{calm} So I built a pool [label: #028], because the book says if you run opposing signals together their trades cancel and you stop paying the toll.
{surprised, happy} Guess what — it *works*. 87% of the turnover netted out.
{disgusted, deflated | pause: 400} And the pool was still sub-economic.
{calm} Widened it from 12 to 28 pairs [label: #029], gross went up, net went to minus 85 Sharpe, because the extra breadth came from crosses with 3 bp spreads.
{amused, disgusted} Added a spread gate, which flips it positive and then trades *1%* of available bars, which is roughly *0%* a year.
{calm} Final salvage [label: #030]: use limit orders, become a maker instead of a taker, get the spread back.
{happy, surprised} It works. Limits recover essentially the full spread.
{calm} And then I measured the ceiling — what this thing earns with execution costs set to zero, free, magic, perfect —
{disgusted, deflated | pace: slow} and it's 0.057 bp per signal. Call it 0.8% a year in a universe where friction doesn't exist.
{amused, sad} You'd need some absolute superhuman flash plus quicksilver type speed.
{amused, happy | pause: 500} And I aint Jane street...well not yet.
{calm, wry | pause: 400} Well turns out the only thing that worked was simply buy the S&P overnight.
{amused, calm | pause: 400} That's it. That's the whole idea. Close to open, go home flat.
{calm} Two wrinkles make it mine.
{calm} One: swap is only charged on positions open at the broker's 17:00 rollover snapshot, so if you enter after the snapshot you get most of the overnight move and pay *zero* financing.
{calm} Two: raw overnight is just long beta pump-faking, so gate it with the 200-day moving average and it stops bleeding in bears.
{happy, calm | pause: 400} Sharpe 0.47 to 0.77, drawdown minus 20% to minus 8.3%.
{calm | pace: slow} That's v1. [pause: 300] Deployed. [pause: 300] Boring. [pause: 300] Fine.
{amused, calm | pause: 500} Then I tried to make it smarter.
{surprised, afraid} First, the notebook caught me trading on prices that *never existed*.
{calm} Cell 1 of the new build had one sanity line in it: what fraction of nights are green?
{surprised} It came back 0.313. [pause: 400] That's *impossible*.
{calm} The market goes up overnight more often than that, everyone knows it, that's the whole premise.
{surprised, disgusted} Yahoo's opening prints for GSPC (the S&P index feed, not the ETF) are *fake* before roughly 2014.
{disgusted} They're stale copies of the previous close. Zero-gap rate of 78 to 98% a year through 2005 and still 25% in 2012 to 13.
{angry, disgusted} Which means my beautiful 36-year validation of number 023 had been computed across three decades of a number the vendor *made up*.
{disgusted, weary | pace: slow} Not wrong data. [pause: 300] *Absent* data, silently padded.
{calm} Rebuilt it on SPY, the actual ETF, actual prints. 8,262 real nights. Base rate 0.559.
{happy, surprised} The strategy survived, and got better (Sharpe 1.38 filtered on the real prints).
{afraid, calm | pace: slow} But it survived by *luck*. If the effect had been smaller I'd have been trading a vendor's fill-forward for months.
{calm} Then, v2: put a random forest on it. 30 features, all entry-knowable, purged chronological splits, 72 logged trials so the multiple-testing charge is honest.
{happy, calm} Champion model on a sealed 2021 to 26 window it had never seen: +3.21 bp per night vs +1.76 for always-long, Sharpe 0.90 vs 0.44, ahead in every year, +1.0 in 2022 while the baseline did minus 6.7.
{calm} Deflated Sharpe ratio: 0.887. My bar is 0.95.
{sad, disgusted | pause: 400} The frozen model did *not* graduate.
{calm, determined} So I walked forward the recipe instead — freeze the features and hyperparameters, refit every January, never peek.
{happy, calm} 2,870 out-of-sample nights: +3.59 vs +2.13, Sharpe 0.96, positive in *all 12 years*. DSR 0.988.
{happy, proud | pause: 400} That *graduates*. Deployed as v2.
{calm} And I plugged SHAP to it to actually see what the model learned.
{happy, calm | pause: 500} Dip-buying, confirmed by trend, plus high VIX is bullish.

[CTA]
{happy, calm | pace: slow} So I did finally find something and I guess this is evidence that alpha maybe....*exists*?
