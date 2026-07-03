# Prediction-Market Lens on the Mad Money Analytics Tab

A review of `docs/stocks.html` (Analytics tab) and `code/db.py` (`build_analytics_json`)
through the vocabulary betting/forecasting analysts use to grade tipsters: calibration,
edge vs. breakeven, closing-line-value-style framing, variance/drawdown, hot-hand effects,
and format-specific accuracy. Written for the site owner to triage — nothing here has been
implemented.

**What's already there, so this doesn't re-suggest it:**
- Win rates with confidence intervals (`ciHtml`/`ciMargin` — Wilson-ish margin already computed) per sentiment bucket, 7/30/90/180d
- Median *and* mean returns per sentiment, segment, sector, market cap
- A benchmark comparison against VOO/QQQ (`median_spy_30d`, `median_spy_90d`, `median_qqq_30d`, `median_qqq_90d` in `sentiment_perf`) — this is already a "beat the market" framing, just not labeled that way in the UI
- `top_days_right` — a walk-forward, day-by-day directional accuracy per ticker (closest thing on the site to a Brier-style granular score)
- Segment-level (`segment_by_type`) and sector-level (`sector_by_type`) win rates split by buy/sell call type

---

## Quick Wins (near-zero new data, easy to compute from what exists)

### 1. Hit rate vs. breakeven ("edge" framing)
**What it is:** The win rate needed to break even given the *size* of losses vs. wins on losing/winning calls — i.e., is Cramer's win rate actually higher than the rate a coin-flip strategy would need to clear, given his average win/loss magnitude?
**Why it matters:** A 55% win rate sounds good, but if losers average -15% and winners average +5%, you need >75% win rate to break even. The site reports win rate and median return as separate numbers; nobody's connected them into "is this actually profitable to follow."
**How to compute:** From `forward_returns`, per sentiment bucket, split into winners/losers at each horizon, take `AVG(return)` for winners and losers separately (or median, consistent with the rest of the site), then breakeven_win_rate = `abs(avg_loss) / (avg_win + abs(avg_loss))`. Compare against `win_rate_30d`/`win_rate_90d` already in `sentiment_perf`. Add two columns to `sentiment_performance` view or compute in Python inside `build_analytics_json`.
**Effort:** Trivial — one more SQL aggregate + one derived field per row, render as a new column or a "edge" hero sentence (`heroes.sentiment`) alongside the existing beat-SPY sentence.

### 2. "Beat the market" labeling — surface what's already computed
**What it is:** `median_spy_30d`/`median_qqq_30d`/`median_spy_90d`/`median_qqq_90d` already sit in `sentiment_perf` and get used in the hero sentence generator (`_generate_heroes`), but they're not shown as a standalone column in the sentiment performance *table* itself (only in prose above it).
**Why it matters:** This is the single most important prediction-market reframe: "was he right" is less useful than "would you have done better just buying the index." The data exists; it's underexposed in the table UI.
**How to compute:** No new computation — add "vs SPY" / "vs QQQ" delta columns to the sentiment table render in `stocks.html` (`renderAnalytics`), e.g. `median_return_30d - median_spy_30d`.
**Effort:** Trivial — pure front-end, data already in `analytics.json`.

### 3. Alpha (excess return over benchmark), not just beat/lose
**What it is:** The literal `median_return_Xd - median_spy_Xd` delta as its own tracked number, both per-sentiment and aggregated buy-vs-sell — a single "alpha" figure rather than requiring the reader to subtract two columns mentally.
**Why it matters:** Bettors talk in terms of edge (%) over the market price; this is the direct analogue. It also naturally extends to sector/segment tables which currently have no benchmark comparison at all (`sector_by_type`, `segment_by_type` have no spy/qqq fields).
**How to compute:** Same benchmark-price-fetch logic already in `build_analytics_json` (`_fetch_benchmark_prices`, `_nearest_price`) generalizes trivially — bucket by sector/segment instead of just sentiment when building `spy_30d_buckets`/`qqq_30d_buckets`. Currently that fetch loop only buckets by `row['sentiment']`; add sector/segment keys to the same loop.
**Effort:** Trivial-to-moderate — reuses existing benchmark fetch, just needs additional bucketing dimensions in the existing loop (~10-15 lines in `db.py`).

### 4. Sample-size-aware "confidence-weighted accuracy"
**What it is:** Instead of a flat win-rate number, weight it by the CI width (or just always show n alongside it — already partially done via `ciHtml`). Extend the same CI logic used in the sentiment table (currently only wired to `win_rate_30d`/`win_rate_90d`, `ciMargin`) to the sector/segment/mktcap tables, which currently show raw percentages with no uncertainty band.
**Why it matters:** `sector_by_type` and `segment_by_type` already gate on `n_mentions >= 30` for hero sentences and `>= 3` for table inclusion — but a sector with 3 mentions and a sector with 300 both render as a plain percentage in the table with no visual distinction of reliability beyond the hero prose.
**How to compute:** `ciMargin`/`ciHtml` already exist in `stocks.html` — just call them on the sector/segment/mktcap win-rate cells too.
**Effort:** Trivial — front-end only, reuse existing helper functions.

---

## Worth Building (meaningful value, moderate effort)

### 5. Calibration curve / reliability diagram (conviction → outcome correlation)
**What it is:** The classic prediction-market check: bucket calls by *stated* confidence (here, sentiment strength: strong_buy > buy > mild_buy > buy_on_pullback, and mirrored on the sell side) and plot actual win rate against that ordering. Perfect calibration = monotonically increasing win rate as conviction increases.
**Why it matters:** This is explicitly asked for in the brief and is a real blind spot. The site already computes `win_rate_30d` etc. per sentiment and even sorts `sentiment_perf` implicitly by return, but nothing tests whether `strong_buy` actually beats `mild_buy` in win rate or magnitude — i.e., does higher conviction language predict a bigger/more reliable move, or is Cramer's stated intensity just noise/enthusiasm with no signal? Given the current `sentiment_perf` data snapshot fetched here, `buy_on_pullback` beat `wait_hold_neutral` in win rate (63.3% vs 50.2% at 30d) — that's the kind of ordering check this metric would formalize across all 7 buckets at once.
**How to compute:** No new data. Take `sentiment_perf` (already has `SENTIMENT_ORDER` ranking baked into the UI), plot win_rate_30d/90d and avg_return_30d/90d against the ordinal rank of `SENTIMENT_ORDER`. A Spearman correlation (or even just eyeballing the ordering) between conviction-rank and win-rate is the deliverable. Could literally be one small chart: x = sentiment (ordered strong_buy→sell_avoid), y = win_rate_30d, with a fit line — reusing Chart.js already loaded on the page.
**Effort:** Moderate — mostly a new chart panel; computation is a rank-correlation over 7 existing rows (trivial in Python, could even compute it client-side in JS from `analytics.json`).

### 6. Brier-score-style accuracy (proper scoring rule)
**What it is:** True Brier score needs an explicit predicted *probability*, which Cramer doesn't give — he gives a sentiment bucket, not "70% confident." The pragmatic adaptation: map each sentiment bucket to an implied probability of the stock going up (e.g., strong_buy→0.8, buy→0.7, mild_buy→0.6, buy_on_pullback→0.55, wait_hold_neutral→0.5, caution_concern→0.4, sell_avoid→0.3 — calibrate these from historical win rates rather than guessing), then compute `(implied_prob - actual_outcome)^2` averaged across all calls at each horizon, where actual_outcome = 1 if price rose, 0 if not.
**Why it matters:** Gives a single summary number (lower = better calibrated) that's comparable across horizons (7d/30d/90d/180d) and over time (is he getting *more* or *less* well-calibrated as the show goes on?), which none of the current metrics do — everything today is win-rate/return snapshots, not a scoring-rule trend line.
**How to compute:** Requires picking the probability mapping (best derived empirically: use each bucket's actual historical win rate as its "implied probability" — this becomes self-calibrating and avoids arbitrary guesses). Then a straightforward SQL aggregate over `forward_returns`: `AVG(POWER(implied_prob - CASE WHEN return_Xd > 0 THEN 1 ELSE 0 END, 2))` grouped by sentiment or overall. Track this over time by adding a `mention_date` bucket (quarter/half-year) to see if the score trends down (improving).
**Effort:** Moderate — needs a probability-mapping decision + one new aggregate query; genuinely the most "interesting" number to add since it condenses everything into one trend line.

### 7. Return volatility / drawdown of a "follow every call" strategy
**What it is:** If you mechanically bought every buy-rated call and held it (equal-weighted, no sizing), what would your equity curve's volatility and max drawdown look like versus just holding SPY? Standard deviation of returns per call, and a simulated cumulative-return path over time.
**Why it matters:** The brief explicitly calls this out, and it's a real gap — the site shows *central tendency* (median/avg return, win rate) everywhere but never *dispersion*. A sentiment bucket with the same median return but wildly higher variance is a much worse "bet" in Kelly-criterion terms, and this would surface tickers/sectors that are all bark (occasional home runs) vs. genuinely consistent.
**How to compute:** `STDEV` isn't native to SQLite, but can be computed in Python from the same `return_30d`/`return_90d` arrays already pulled into `sent_buckets`/`seg_buckets`/etc. in `build_analytics_json` (just add `statistics.pstdev(vals)` alongside the existing `_median()` calls). For a drawdown/equity-curve, would need an ordered walk over `buy_call_pool` by `mention_date` treating each call as an equal-weighted position opened and (simplistically) held to `return_since_mention` — this is the part that requires more design (overlapping positions, when to "close" a position) so scope it as: assume one unit invested per call, compute cumulative sum of daily portfolio value using `daily_prices` already in the DB. That's the moderate-to-significant part.
**Effort:** Standard deviation addition: trivial. Full equity-curve/drawdown simulation: significant (see Tier 3) — split this into two: (a) stdev per bucket [quick], (b) full drawdown curve [defer to Tier 3].

### 8. Segment-specific calibration (Lightning Round vs. In-Depth vs. Interview)
**What it is:** The brief specifically asks whether Cramer is more accurate in some formats than others. `segment_by_type` already splits win rate and median return by segment × buy/sell, and `SEGMENT_PRIORITY` in `stocks.html` already ranks segment display order — but there's no *summary ranking* of segments by accuracy shown prominently (it's currently buried inside per-ticker call rows and the segment hero prose).
**Why it matters:** This is a natural story for the site: "Lightning Round calls are right X% of the time vs Y% for In-Depth Analysis" is a genuinely interesting finding people would want front-and-center, not just in hero paragraph text.
**How to compute:** No new data — `segment_by_type` already has everything (`win_rate_30d`, `win_rate_90d`, `median_return_30d`, `n_mentions`). Just needs a dedicated leaderboard-style table/chart in the Analytics tab (parallel to how sector and market-cap already get tables), sorted by win_rate_30d descending, with the existing `n_mentions >= 30` (or lower) reliability gate visualized via CI.
**Effort:** Moderate — mostly front-end (new table/chart component); zero new backend computation needed beyond what `segment_by_type` already provides.

### 9. "Hot hand" / streak metric
**What it is:** Is Cramer currently on a hot or cold streak — e.g., rolling win rate over his last N calls (last 20, last 90 days) vs. his all-time win rate — and do winning streaks predict continued winning (real "hot hand") or mean-revert (gambler's fallacy territory)?
**Why it matters:** Directly requested in the brief. Distinguishes "he's been on fire lately" (recency-relevant to a reader deciding whether to act on tonight's picks) from static all-time stats. Also testable: does a streak of 5+ correct calls in a row predict the 6th call's outcome better than base rate? (Likely not — but that's itself an interesting, quotable finding: "no evidence of a hot hand," which is exactly the kind of finding sports-betting analysts report about tipsters.)
**How to compute:** Walk `latest_mention_performance`-style data ordered by `mention_date` across the whole dataset (not per-ticker — needs a global chronological ordering of all directional calls with `return_30d > 0`/`< 0` as win/loss), compute a rolling win rate (e.g., trailing 20-call window) as a time series, and separately a simple streak-autocorrelation check (does win at t predict win at t+1?). This is new: needs a query ordering *all* mentions across all tickers by date (not grouped by ticker like `top_days_right` is), which nothing currently does at that granularity.
**Effort:** Moderate — new query + rolling-window computation in Python (straightforward with a sorted list and a deque), plus a new line-chart panel for the rolling win rate. The streak-autocorrelation stat itself is a one-line computation once the chronological win/loss sequence exists.

---

## Interesting but Lower Priority (higher effort or lower payoff for a hobby project)

### 10. Full equity-curve / max-drawdown simulation
Building an actual simulated portfolio (equal-weighted, one unit per buy call, position sizing/exit rules, overlapping positions across many tickers) that produces a real max-drawdown percentage and Sharpe-like ratio. This is the "if you actually did this" backtest. Valuable but requires real decisions about position sizing, holding period, and re-investment that don't have an obvious canonical answer here (unlike the SPY-comparison-per-call framing already used, which sidesteps portfolio construction entirely). Significant effort, and results would be sensitive to arbitrary methodology choices — riskier to over-claim precision on a hobby project.
**Effort:** Significant.

### 11. Kelly-criterion "optimal bet size" per sentiment bucket
Given a bucket's empirical win rate and average win/loss magnitude, compute the Kelly-optimal fraction of a bankroll to allocate. Cute, and a natural extension of the "hit rate vs breakeven" quick win (#1) — but for a single-developer hobby site with no real trading/position-sizing feature, this is decorative rather than actionable. Only worth doing if #1 (breakeven framing) lands well and there's appetite for more.
**Effort:** Trivial computation once #1 exists, but genuinely low payoff — nobody is sizing real positions off this site.

### 12. ELO-style rating system (per ticker or per sector, updated call-by-call)
Treating each call as a "match" between Cramer's prediction and the market, with an ELO-like rating that rises/falls based on surprising wins/losses (a call on a stock that was "expected" to be volatile getting it right matters less than nailing a low-volatility name). This is the most sophisticated ask in the brief but also the hardest to justify: ELO is designed for *repeated head-to-head* competition where opponents' ratings interact (chess players, sports teams); here there's no natural "opponent" to rate against except the market itself, which the SPY/QQQ benchmark (#2/#3) already captures more directly and interpretably. An ELO layer on top would mostly just be a fancier repackaging of win rate with recency weighting — the rolling win rate in #9 gets most of the same value with far less conceptual overhead.
**Effort:** Significant, and the "why not just use rolling win rate + benchmark delta" question doesn't have a great answer for a hobby project — recommend skipping unless there's a specific desire to build/showcase an ELO system for its own sake.

### 13. Segment × sentiment 2-D calibration matrix
Full cross of segment × sentiment bucket (not just segment × buy/sell as `segment_by_type` currently does) — e.g., is a `strong_buy` in Lightning Round as reliable as a `strong_buy` in In-Depth Analysis? Interesting but sample sizes get thin fast once you cross 7 segments × 7 sentiments (49 cells), most of which will fail the `n_mentions >= 30` reliability bar already used elsewhere on the site. Worth revisiting once total mention count grows substantially; not worth building against current data volume.
**Effort:** Moderate build effort, but low payoff today due to sparse cells — revisit later.

---

## Summary Table

| # | Metric | Tier | Effort | New data needed? |
|---|--------|------|--------|-------------------|
| 1 | Hit rate vs. breakeven | Quick win | Trivial | No |
| 2 | Surface existing SPY/QQQ deltas in table | Quick win | Trivial | No |
| 3 | Alpha vs. benchmark for sector/segment | Quick win | Trivial-moderate | No (reuse fetch loop) |
| 4 | CI bands on sector/segment/mktcap tables | Quick win | Trivial | No |
| 5 | Calibration curve (conviction vs. outcome) | Worth building | Moderate | No |
| 6 | Brier-score-style accuracy | Worth building | Moderate | No (needs prob mapping) |
| 7a | Return stdev per bucket | Worth building | Trivial | No |
| 7b | Full drawdown/equity curve | Lower priority | Significant | No, but methodology-heavy |
| 8 | Segment accuracy leaderboard | Worth building | Moderate | No |
| 9 | Rolling win rate / hot-hand check | Worth building | Moderate | No |
| 10 | Full portfolio backtest | Lower priority | Significant | No |
| 11 | Kelly-optimal sizing | Lower priority | Trivial (low payoff) | No |
| 12 | ELO rating system | Lower priority | Significant | No |
| 13 | Segment × sentiment matrix | Lower priority | Moderate (sparse) | No |

**Suggested order if picking a few:** #2 and #4 first (pure UI, ~an hour combined), then #1
(breakeven framing — probably the single most "so what" number missing today), then #5
(calibration curve — directly answers the brief's headline question about whether
conviction language means anything), then #9 (hot hand) if there's appetite for a new chart.
