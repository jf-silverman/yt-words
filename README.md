# Mad Money — Stock Lookup, Analytics, and Nightly Pipeline

A self-initiated end-to-end data project: scrape YouTube transcripts, extract structured stock calls with an LLM, track forward returns in a relational database, and surface the analytics on a fully client-side website — all running automatically every weekday night.

**Live site:** [jf-silverman.github.io/yt-words/stocks.html](https://jf-silverman.github.io/yt-words/stocks.html)

---

## The Question

Jim Cramer makes dozens of stock picks per episode of Mad Money. Most coverage of his calls is anecdotal. Does his conviction level actually predict accuracy? Does segment matter — is he sharper in his carefully prepared Opening Commentary than in the rapid-fire Lightning Round? Which sectors does he call best?

This project builds the infrastructure to answer those questions rigorously, from raw YouTube audio to a queryable analytics dashboard.

---

## Skills Demonstrated

| Area | What's Here |
|------|-------------|
| **Self-directed project** | Conceived, designed, and built end-to-end without a team or specification — from YouTube scraping to a public analytics site |
| **Data acquisition / scraping** | `yt-dlp` to extract YouTube auto-captions (JSON3/VTT format); Yahoo Finance v8 chart API for daily closing prices; Overcast podcast API for deep-link timestamps |
| **LLM prompt engineering** | Structured prompt that instructs Claude Haiku to return validated JSON: segments, sentiment categories, tickers, confidence signals, and private company handling — including few-shot examples and explicit rules to prevent hallucination |
| **Relational database design** | SQLite schema with `episodes`, `mentions`, `stocks`, `daily_prices` tables; a `forward_returns` SQL view pre-computes 7/30/90/180-day returns joined to benchmark (S&P 500, Nasdaq) prices; proper UNIQUE constraints and upsert logic |
| **ETL pipeline** | Automated GitHub Actions workflow (2 AM nightly) discovers new episodes, fetches transcripts, calls the LLM, stores results, fetches closing prices, computes analytics JSON, and pushes to GitHub Pages in a single run |
| **SQL querying & aggregation** | Complex queries for win rates by sentiment/segment/sector/market cap; median return calculations; benchmark-relative performance; confidence interval computation |
| **Client-side web development** | GitHub Pages site (`docs/stocks.html`) — fully static, no backend; Chart.js time-scale charts with sentiment markers; async live price fetching; dynamic filter UI; per-ticker JSON shards fetched on demand |
| **Analytics & data storytelling** | Win-rate and median-return comparisons across 1,100+ tickers, 6+ months, and 5 sentiment categories; pipeline-generated hero text that auto-updates each night |
| **Backtesting & benchmark methodology** | 60-day hold backtest of every buy call, each benchmarked against the S&P 500 / Nasdaq over its *own* matching window. Uses **paired per-call excess returns** — the naive "median of returns minus median of index returns" is invalid because different calls land in different market windows, and it can flip the sign of the result (NVDA reads as a loser by that method and a winner when paired correctly). Models a realistic "sell when he downgrades" variant, and rejects the tempting "drop the calls he later soured on" filter as lookahead bias |
| **Predictive modeling** | scikit-learn logistic regression predicting which "buy on pullback" calls never pull back — 0.76 AUC / 77% accuracy, cross-validated with **grouped folds** (by ticker *and* by call date) so a stock can't leak across the split. Systematically tested volatility, fundamentals, valuation, market-regime (VIX/SPY) and analyst features; all failed to beat a single point-in-time momentum feature on n≈100. Caught and excluded **lookahead-biased features** (yfinance's `52WeekChange` embeds today's price and scored a fake 0.745 AUC), and rebuilt the target after discovering the original label was circular — it was derived from beta, which was also the model's strongest input |
| **Troubleshooting complex systems** | Debugged YouTube authentication failures (bot-check evasion with filtered Netscape cookies), SQLite UNIQUE constraint violations in bulk ticker corrections, GitHub Actions Node.js deprecation, Yahoo Finance rate limiting, and yt-dlp format-selection failures |
| **Iterative improvement** | Haiku prompt refined over dozens of episodes — added private company ticker rules (Anthropic, OpenAI, SpaceX), tease-mention suppression, segment boundary detection, and caller Q&A incorporation |

---

## What the Data Shows (So Far)

Based on ~117 episodes (Jan–Jul 2026). Figures below are point-in-time; the site recomputes them nightly.

- **Conviction predicts accuracy.** "Buy on Pullback" calls are right 65% of the time vs. 57% for generic buy calls and 53% for Lightning Round picks.
- **Segment matters.** Closing Commentary (70% win rate, +6.4% median 30d return) significantly outperforms Lightning Round picks despite both being "buy calls."
- **Sector is the strongest signal.** Technology picks are right 69% of the time with +8.3% median 30-day return vs. Financial Services at 38% / -2.1%.
- **Sell calls are underrated.** At 90 days, stocks Cramer warned against fell 2.6% while the Nasdaq gained ~14% in the same windows — a 17-point gap. Against the S&P 500 the spread is still 8.5 points (-2.6% vs +5.9%).

### Would following his buy calls have beaten an index fund?

Buying every buy call and holding 60 days, each call benchmarked against the index over its *own* 60-day window (~1,260 calls across ~370 tickers; the live site recomputes these nightly):

| | Cramer | S&P 500 | Nasdaq |
|---|---|---|---|
| **Mean** return | **+8.0%** | +2.9% | +6.8% |
| **Median** return | **+1.0%** | +3.7% | +8.3% |
| Calls that beat the index | — | **48%** | **43%** |

- **The mean and the median disagree — and the median is the honest one.** By the average he beats the S&P by 5 points; by the typical call he *loses* to it, and beats it less than half the time. The average is carried by a thin tail: the **top 5% of calls returned ~+106%**, while the other 95% averaged +2.9% (median −0.1%).
- **Nearly all of his edge was one sector.** His AI-complex buy calls beat the S&P by **~+10 points per call** (70% rose). Everything else *trailed* the index by ~4.5 points. Take AI out and his stock picking added nothing.
- **He picked the right sector and then mistimed it.** He was *more* bullish on AI than elsewhere (Strong Buy on 18% of AI calls vs. 10%), but hedged with "buy on pullback" ~2× as often — and **that dip never came ~38% of the time** (buying anyway returned a ~+31% median). Acting on his later downgrades cut the mean return from +8.0% to +5.0%.
- **His bearish calls are good — except on AI.** Across all Caution/Sell calls the stock fell 54% of the time (median −1.3%, 4 points below the index). On AI names the same calls *rose*. AI takes 6 of the 10 worst bearish calls to follow, but only 3 of the 10 best.
- **A 0.76-AUC model predicts which "buy on pullback" calls never pull back**, using a single point-in-time feature (20-day pre-call momentum), cross-validated with folds grouped by ticker. Beta, fundamentals, valuation, market regime, and analyst targets were all tested and *none* improved held-out AUC.

⚠️ **All of this sits inside one ~6-month AI-driven bull market (Jan–Jul 2026).** In that regime "the stock he was cautious on kept climbing" is nearly tautological for the leading sector. Read it as a verdict on this period, not on his process.

---

## How It Works

```
YouTube transcript (yt-dlp)
       ↓
Claude Haiku (structured JSON extraction)
       ↓
SQLite DB  ←→  Yahoo Finance closing prices
       ↓
analytics.json + per-ticker shards
       ↓
GitHub Pages (stocks.html)
```

### Pipeline steps (daily, automated via GitHub Actions)

1. Discover new Mad Money episodes via yt-dlp channel scan
2. Fetch auto-captions (JSON3 preferred, VTT fallback); skip if transcript exists
3. Analyze transcript with Claude Haiku → segments, sentiment, tickers, notes
4. Upsert episode + mentions into SQLite; fetch closing price per ticker per date
5. Rebuild analytics JSON and per-ticker shards; push `docs/` to GitHub Pages

### LLM prompt engineering

The `prompts/mad_money_rules.md` system prompt is the core reliability layer:

- **Structured output:** defines exact JSON schema with field names, types, and validation rules
- **Segment detection:** rules for recognizing Opening Commentary, Lightning Round, Closing Commentary, interviews, and in-depth analyses by transcript cues
- **Ticker accuracy:** hard-coded symbol overrides for companies Cramer refers to by name (Anthropic → `ANTH`, OpenAI → `OPAI`, SpaceX → `SPCX`); tease-mention suppression logic
- **Sentiment taxonomy:** 6 ordered categories from Strong Buy to Sell/Avoid with clear definitions and boundary examples
- **Hallucination prevention:** explicit rules on what NOT to do (no nested subsections, no invented tickers, no separating caller Q&A into standalone sections)

### Database design

```sql
episodes     — date, video_id, episode_type (regular | fundamentals), is_fundamentals flag
mentions     — ticker, date, sentiment, segment, note, closing_price
             — UNIQUE (episode_id, ticker, segment) prevents duplicate mentions
stocks       — ticker, company, sector, style (Growth/Blend/Value from P/E)
daily_prices — ticker, date, close
forward_returns (VIEW) — pre-joins mentions → daily_prices at 7/30/90/180d horizons
                       — excludes fundamentals episodes from analytics
```

---

## Running Locally

```bash
pip install anthropic requests yt-dlp yfinance

# Create .env with:
# ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD, OVERCAST_EMAIL, OVERCAST_PASSWORD

python3 code/pipeline.py --email-mode smtp   # full run + email
python3 code/pipeline.py --rebuild-shards    # regenerate site data
python3 code/pipeline.py --dry-run           # analyze without sending
python3 code/backfill.py --start 2026-01-01  # reprocess a date range
```

---

## Repository Layout

```
code/
  pipeline.py        — main pipeline (discovery → analysis → email → publish)
  backfill.py        — date-range reprocessing utility
  db.py              — SQLite schema, upsert helpers, build_analytics_json()
prompts/
  mad_money_rules.md — Claude Haiku system prompt (segment rules, ticker rules, JSON schema)
data/
  mad_money.db       — SQLite database (source of truth for all mention data)
  stock_sentiments.json — ticker metadata mirror (sector, style, company name)
  summaries/         — archived HTML email per episode date
  transcripts/       — raw transcript text files
docs/
  stocks.html        — GitHub Pages site (fully client-side, no backend)
  data/
    analytics.json   — pre-computed analytics (regenerated nightly)
    {TICKER}.json    — per-ticker shards (fetched on demand by site)
.github/workflows/
  daily_pipeline.yml — GitHub Actions cron (2:07 AM UTC Tue–Sat)
```

---

## Disclaimer

Educational and entertainment use only — not investment advice. Data may contain errors from LLM transcript analysis. I am not a financial advisor.
