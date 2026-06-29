# Mad Money Stock Lookup and Analytics

A personal project that watches CNBC's Mad Money YouTube channel, analyzes transcripts with Claude AI, and maintains a [GitHub Pages stock-lookup site](https://jf-silverman.github.io/yt-words/stocks.html).

## What It Does

- **Discovers** new Mad Money episodes via yt-dlp
- **Transcribes** each episode from YouTube auto-captions
- **Analyzes** transcripts with Claude Haiku → structured JSON of segments and stock picks
- **Tracks** sentiment, closing price, and forward returns per mention in SQLite
- **Sends** a nightly HTML email summarizing each episode
- **Publishes** a client-side GitHub Pages site for searching and filtering all picks

## The Site

[**jf-silverman.github.io/yt-words/stocks.html**](https://jf-silverman.github.io/yt-words/stocks.html)

- **Search** — look up any ticker; see all mentions with sentiment, closing price, and a Chart.js price chart
- **Stock Picker** — filterable table of the last 7/30/90 days of picks, with sector, style, and segment filters
- **Analytics** — aggregated stats: win rate by sentiment/segment/sector, market cap breakdown, and Cramer's top % Days Right stocks

## Running Locally

```bash
pip install anthropic requests yt-dlp yfinance

# Create .env with ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD, OVERCAST_EMAIL, OVERCAST_PASSWORD
python3 code/pipeline.py --email-mode smtp
```

See [`docs/important_commands.md`](docs/important_commands.md) for the full command reference.

## Layout

```
code/
  pipeline.py        — main pipeline (all steps + --flag utilities)
  backfill.py        — date-range backfill utility
  db.py              — SQLite schema, upsert helpers, build_analytics_json()
prompts/
  mad_money_rules.md — system prompt for Claude Haiku
data/
  mad_money.db       — SQLite database (authoritative source)
  stock_sentiments.json — JSON mirror of ticker metadata
docs/
  stocks.html        — GitHub Pages site (fully client-side)
  index.html         — home page
  data/              — pre-computed JSON shards served to the browser
```

## Disclaimer

This site is for educational and entertainment purposes only — not investment advice. Data may contain errors. I'm not a financial advisor.
