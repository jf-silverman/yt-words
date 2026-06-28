from __future__ import annotations

"""
Mad Money daily pipeline.

Steps:
  1. Discover new Mad Money episodes on the CNBC YouTube channel
  2. Fetch transcripts (saved to data/output/)
  3. Analyze with Claude Haiku → structured JSON (sections + stocks)
  4. Update data/stock_sentiments.json
  5. Find matching podcast episode in RSS feed → build Overcast deep links
  6. Format HTML email
  7. Send via Gmail (smtp or mcp mode)

Usage:
    python pipeline.py [--max-episodes N] [--email-mode smtp|mcp] [--dry-run]

Environment variables:
    ANTHROPIC_API_KEY     required for Haiku analysis
    GMAIL_APP_PASSWORD    required for --email-mode smtp
    GMAIL_FROM            sender address (default: joelfsilverman@gmail.com)
    GMAIL_TO              recipient address (default: joelfsilverman@gmail.com)
"""

import argparse
import json
from collections import Counter
import os
import re
import smtplib
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

import anthropic
import requests
import yt_dlp

from db import (
    init_db,
    upsert_episode,
    upsert_mention,
    upsert_stock,
    upsert_daily_prices,
    build_analytics_json,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent


def _load_dotenv() -> None:
    """Load .env file from project root into os.environ (no third-party deps)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()
import re

# Ensure SQLite DB is initialized on first run
init_db()
import subprocess

DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "transcripts"
SUMMARIES_DIR = DATA_DIR / "summaries"
DOCS_DIR = ROOT / "docs"
TICKER_DATA_DIR = DOCS_DIR / "data"
SENTIMENTS_FILE = DATA_DIR / "stock_sentiments.json"
PROCESSED_FILE = DATA_DIR / "processed_episodes.json"
OVERCAST_CACHE_FILE = DATA_DIR / "overcast_episode_ids.json"
RULES_FILE = ROOT / "prompts" / "mad_money_rules.md"

CNBC_CHANNEL_ID = "UCrp_UI8XtuYfpiqluWLD7Lw"
MAD_MONEY_RSS = "https://feeds.simplecast.com/TkQfZXMD"
OVERCAST_PODCAST_URL = "https://overcast.fm/itunes147247199/"
GITHUB_PAGES_BASE = "https://jf-silverman.github.io/yt-words"

GMAIL_FROM = "joelfsilverman@gmail.com"
GMAIL_TO = "joelfsilverman@gmail.com"
GMAIL_SMTP = ("smtp.gmail.com", 587)

BROTHER_TO = "riversdirect@hotmail.com"
BROTHER_TICKERS = {"MU", "RVI", "UVXY", "WD", "AMD"}

# Companies that are private or recently IPO'd; skip Yahoo Finance price lookup
# ipo_date = None means still private; otherwise price data exists from that date onward
PRIVATE_COMPANIES: dict[str, dict] = {
    "ANTH": {"name": "Anthropic", "ipo_date": None},
    "OPAI": {"name": "OpenAI",    "ipo_date": None},
    "SPCX": {"name": "SpaceX",   "ipo_date": "2026-06-12"},
}


def _is_private(ticker: str, date_str: str) -> bool:
    """Return True if ticker had no public market on date_str."""
    info = PRIVATE_COMPANIES.get(ticker)
    if not info:
        return False
    if info["ipo_date"] is None:
        return True
    return date_str < info["ipo_date"]

USER_HOLDINGS = {
    "ARM", "AEVA", "INTC", "CRWV", "BE", "AUR", "ABSI", "PWR", "RVMD", "LRCX",
    "GNRC", "LIN", "NEE", "ABNB", "MP", "NUE", "GOOGL", "VXUS", "QUBT", "COST",
    "NET", "MRNA", "ARKK", "GLD", "CRSP", "NVDA", "MRVL", "MU", "AMZN", "CRWD",
    "TWLO", "QS", "AAPL", "QBTS", "SHOP", "BEAM", "LLY", "SNOW", "RDDT", "VCX",
    "LITE", "FPS", "VRT", "FSLR", "GILT", "RVI", "ONDS", "HAWK", "IRDM",
}

SENTIMENT_COLORS = {
    "strong_buy":        "#1a7f37",
    "buy":               "#2da44e",
    "mild_buy":          "#80e09a",
    "buy_on_pullback":   "#4ac26b",
    "wait_hold_neutral": "#8b949e",
    "caution_concern":   "#f0a030",
    "sell_avoid":        "#a00000",
}

# Canonical order (most bullish → most bearish)
SENTIMENT_ORDER = [
    "strong_buy", "buy", "mild_buy", "buy_on_pullback",
    "wait_hold_neutral", "caution_concern", "sell_avoid",
]

# Map legacy values to consolidated canonical values
_SENTIMENT_MAP = {
    "hold":    "wait_hold_neutral",
    "wait":    "wait_hold_neutral",
    "neutral": "wait_hold_neutral",
    "caution": "caution_concern",
    "concern": "caution_concern",
    "sell":    "sell_avoid",
    "avoid":   "sell_avoid",
}

def normalize_sentiment(s: str) -> str:
    """Map any legacy or raw sentiment string to a canonical value."""
    if not s:
        return "wait_hold_neutral"
    return _SENTIMENT_MAP.get(s, s)


# ── 1. Episode discovery ───────────────────────────────────────────────────────

def load_processed() -> list[dict]:
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return []


def save_processed(records: list[dict]) -> None:
    PROCESSED_FILE.write_text(json.dumps(records, indent=2))


def _date_from_title(title: str) -> str:
    """Parse upload date from CNBC titles like 'Mad Money 06/10/26 | Audio Only'."""
    m = re.search(r'(\d{2})/(\d{2})/(\d{2})', title)
    if m:
        month, day, year = m.groups()
        return f"20{year}-{month}-{day}"
    return ""


def _date_from_ydlp(video_id: str) -> str:
    """Fetch upload date via yt-dlp (requires unauthenticated YouTube access)."""
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    raw = info.get("upload_date", "")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def discover_new_episodes(max_n: int = 5) -> list[dict]:
    """Return up to max_n unprocessed Mad Money video dicts [{id, title, upload_date}]."""
    processed_ids = {r["video_id"] for r in load_processed()}

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": 200,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(
            f"https://www.youtube.com/channel/{CNBC_CHANNEL_ID}/videos",
            download=False,
        )

    episodes = []
    for entry in result.get("entries", []):
        title = entry.get("title") or ""
        if "Mad Money" not in title:
            continue
        vid = entry.get("id")
        if vid in processed_ids:
            continue
        # Prefer upload_date from flat-extract; fall back to title parsing
        raw_date = entry.get("upload_date", "")
        if raw_date:
            upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        else:
            upload_date = _date_from_title(title)
        episodes.append({"id": vid, "title": title, "upload_date": upload_date})
        if len(episodes) >= max_n:
            break

    return episodes


# ── 2. Transcript fetch ────────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m}:{s:02d}]"


def _parse_json3(data: dict) -> str:
    """Convert YouTube JSON3 caption data to timestamp-prefixed transcript text."""
    lines, prev = [], None
    for event in data.get('events', []):
        if 'segs' not in event:
            continue
        secs = event['tStartMs'] / 1000.0
        text = ''.join(seg.get('utf8', '') for seg in event['segs']).replace('\n', ' ').strip()
        if text and text != prev:
            lines.append(f'{_fmt_ts(secs)} {text}')
            prev = text
    return '\n'.join(lines)


def _parse_vtt(vtt: str) -> str:
    """Convert WebVTT captions to timestamp-prefixed transcript text, deduplicating the sliding window."""
    lines, prev_text = [], None
    for block in re.split(r'\n\n+', vtt.strip()):
        if '-->' not in block:
            continue
        blines = block.strip().split('\n')
        ts_line = next((l for l in blines if '-->' in l), None)
        if not ts_line:
            continue
        start_raw = ts_line.split('-->')[0].strip().split()[0]
        try:
            h, m, s = start_raw.split(':')
            secs = int(h) * 3600 + int(m) * 60 + float(s)
        except ValueError:
            continue
        text_lines = [l for l in blines
                      if '-->' not in l and l.strip() and not re.match(r'^\d+$', l.strip())]
        text = re.sub(r'<[^>]+>', '', ' '.join(text_lines)).strip()
        if text and text != prev_text:
            lines.append(f'{_fmt_ts(secs)} {text}')
            prev_text = text
    return '\n'.join(lines)


def fetch_transcript(video_id: str, upload_date: str = "") -> tuple[str, list, str]:
    """Returns (date_str, [], transcript_text). Skips download if file exists."""
    date_str = upload_date or _date_from_ydlp(video_id)
    out_path = OUTPUT_DIR / f"{date_str}_transcript.txt"

    if out_path.exists():
        print(f"  Transcript already on disk: {out_path.name}")
        return date_str, [], out_path.read_text()

    cookie_file = os.environ.get("YOUTUBE_COOKIE_FILE")
    browser     = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER")
    opts = {'quiet': True, 'no_warnings': True}
    if cookie_file:
        opts['cookiefile'] = cookie_file
    elif browser:
        opts['cookiesfrombrowser'] = (browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False, process=False)

    en_caps = (info or {}).get('automatic_captions', {}).get('en', [])
    if not en_caps:
        raise ValueError(f'No English auto-captions for {video_id}')
    cap = (next((c for c in en_caps if c.get('ext') == 'json3'), None) or
           next((c for c in en_caps if c.get('ext') == 'vtt'), None))
    if not cap:
        raise ValueError(f'No usable caption format for {video_id}')

    resp = requests.get(cap['url'], timeout=30)
    resp.raise_for_status()
    text = _parse_json3(resp.json()) if cap['ext'] == 'json3' else _parse_vtt(resp.text)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    return date_str, [], text


# ── 3. Haiku analysis ──────────────────────────────────────────────────────────

def analyze_with_haiku(date_str: str, transcript_text: str) -> dict:
    """Call Claude Haiku with the Mad Money rules. Returns parsed analysis dict."""
    system_prompt = RULES_FILE.read_text()
    client = anthropic.Anthropic()

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Episode date: {date_str}\n\n"
                    f"Transcript:\n{transcript_text}"
                ),
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip accidental markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(raw)


# ── 4. Sentiment JSON update ───────────────────────────────────────────────────

def fetch_closing_price(ticker: str, date_str: str) -> float | None:
    """Return the closing price for ticker on date_str using Yahoo Finance. Returns None on any error."""
    try:
        dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        p1 = int(dt.timestamp())
        p2 = p1 + 86400
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?interval=1d&period1={p1}&period2={p2}")
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        price = next((c for c in closes if c is not None), None)
        return round(price, 2) if price is not None else None
    except Exception:
        return None


def fetch_price_history(ticker: str, days: int = 180) -> list[dict]:
    """Fetch daily closing prices for the past `days` days from Yahoo Finance.
    Returns [{date, close}, ...] sorted oldest-first, empty list on error."""
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        p1 = int(start.timestamp())
        p2 = int(end.timestamp())
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?interval=1d&period1={p1}&period2={p2}")
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result["indicators"]["quote"][0]["close"]
        out = []
        for t, c in zip(timestamps, closes):
            if c is None:
                continue
            day = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            out.append({"date": day, "close": round(c, 2)})
        return out
    except Exception:
        return []


def _load_price_archive(ticker: str) -> list[dict]:
    """Load accumulated daily prices from data/daily_prices/{TICKER}.json."""
    archive_dir = DATA_DIR / "daily_prices"
    path = archive_dir / f"{ticker}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save_price_archive(ticker: str, prices: list[dict]) -> None:
    """Save accumulated daily prices to data/daily_prices/{TICKER}.json."""
    archive_dir = DATA_DIR / "daily_prices"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{ticker}.json"
    path.write_text(json.dumps(prices, separators=(",", ":")))


def _merge_prices(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new prices into existing, avoiding duplicates by date. Returns sorted oldest-first."""
    by_date = {p["date"]: p for p in existing}
    by_date.update({p["date"]: p for p in new})
    return sorted(by_date.values(), key=lambda p: p["date"])


def write_price_files(stocks: dict, only: set[str] | None = None) -> None:
    """Write docs/data/{TICKER}_prices.json for active tickers and archive to data/daily_prices/.

    When only is None, fetches all public tickers mentioned in the last 180 days.
    When only is a set, fetches just those tickers (still skips private ones).
    Archives all fetched prices to data/daily_prices/{TICKER}.json for long-term history.
    """
    cutoff = (date.today() - timedelta(days=180)).isoformat()
    today  = date.today().isoformat()
    targets = []
    for ticker, entry in stocks.items():
        if only is not None and ticker not in only:
            continue
        if _is_private(ticker, today):
            continue
        if any(m.get("date", "") >= cutoff for m in entry.get("mentions", [])):
            targets.append(ticker)

    if not targets:
        return
    print(f"  Fetching daily price history for {len(targets)} ticker(s)…")
    for i, ticker in enumerate(targets, 1):
        hist = fetch_price_history(ticker)
        if hist:
            existing = _load_price_archive(ticker)
            merged = _merge_prices(existing, hist)
            _save_price_archive(ticker, merged)
            upsert_daily_prices(ticker, merged)
            (TICKER_DATA_DIR / f"{ticker}_prices.json").write_text(
                json.dumps(hist, separators=(",", ":"))
            )
        if i % 20 == 0:
            print(f"    {i}/{len(targets)} done")
        time.sleep(0.2)


def update_stock_sentiments(analysis: dict, video_id: str = "") -> None:
    if SENTIMENTS_FILE.exists():
        db = json.loads(SENTIMENTS_FILE.read_text())
    else:
        db = {
            "_schema": {
                "sentiment_values": list(SENTIMENT_COLORS.keys()),
                "segment_values": [
                    "opening_commentary", "caller_qa", "interview",
                    "in_depth_analysis", "lightning_round", "closing_commentary",
                ],
            },
            "stocks": {},
        }

    stocks = db.setdefault("stocks", {})
    episode_date = analysis["episode_date"]

    # Ensure episode row exists in DB (video_id may be filled in later by main loop)
    if video_id:
        episode_id = upsert_episode(date=episode_date, video_id=video_id)
    else:
        episode_id = None

    for stock in analysis.get("stocks", []):
        ticker = stock.get("ticker", "").upper()
        if not ticker:
            continue
        entry = stocks.setdefault(ticker, {
            "company": stock.get("company", ""),
            "mentions": [],
        })
        mention = {
            "date": episode_date,
            "sentiment": normalize_sentiment(stock.get("sentiment", "wait_hold_neutral")),
            "segment": stock.get("segment", ""),
            "note": stock.get("note", ""),
        }
        if "price_target" in stock:
            mention["price_target"] = stock["price_target"]
        if "price_level" in stock:
            mention["price_level"] = stock["price_level"]
        if not _is_private(ticker, episode_date):
            price = fetch_closing_price(ticker, episode_date)
            if price is not None:
                mention["closing_price"] = price
        entry["mentions"].append(mention)

        # Write to SQLite
        upsert_stock(
            ticker=ticker,
            company=stock.get("company", entry.get("company", "")),
            sector=entry.get("sector"),
            style=entry.get("style"),
        )
        if episode_id:
            upsert_mention(
                episode_id=episode_id,
                ticker=ticker,
                sentiment=mention["sentiment"],
                segment=mention["segment"],
                closing_price=mention.get("closing_price"),
                note=mention.get("note", ""),
                date=episode_date,
            )

    SENTIMENTS_FILE.write_text(json.dumps(db, indent=2))

    # Write per-ticker shards for touched tickers + refresh index
    touched = {s.get("ticker", "").upper() for s in analysis.get("stocks", []) if s.get("ticker")}
    _write_ticker_shards(stocks, only=touched)
    write_price_files(stocks, only=touched)


def _write_ticker_shards(stocks: dict, only: set[str] | None = None) -> None:
    """Write docs/data/{TICKER}.json shards and refresh docs/data/index.json."""
    from db import get_connection
    TICKER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Batch-fetch each ticker's most recent closing price from the DB so shards
    # show the latest pipeline-fetched price rather than the mention-date close.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, close, date FROM daily_prices
        WHERE (ticker, date) IN (
            SELECT ticker, MAX(date) FROM daily_prices GROUP BY ticker
        )
    """)
    latest_prices = {r["ticker"]: {"price": r["close"], "date": r["date"]}
                     for r in cur.fetchall()}
    conn.close()

    targets = only if only is not None else set(stocks.keys())
    for ticker in targets:
        if ticker in stocks:
            lp = latest_prices.get(ticker)
            shard = {**stocks[ticker]}
            if lp:
                shard["price_latest"]      = lp["price"]
                shard["price_latest_date"] = lp["date"]
            (TICKER_DATA_DIR / f"{ticker}.json").write_text(json.dumps(shard))
    index = {}
    for t, e in stocks.items():
        mentions = e.get("mentions", [])
        dates_with_price = len({m.get("date") for m in mentions if m.get("closing_price") is not None})
        index[t] = {"name": e.get("company", ""), "count": len(mentions), "dates": dates_with_price}
    (TICKER_DATA_DIR / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    _write_recent_json(stocks)
    build_analytics_json(str(TICKER_DATA_DIR / "analytics.json"))


def _write_recent_json(stocks: dict) -> None:
    """Write docs/data/recent.json with all mentions from the last 90 days."""
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    _sent_rank = {s: i for i, s in enumerate(SENTIMENT_ORDER)}
    # Group all mentions by (ticker, date, segment)
    groups: dict[tuple, list[dict]] = {}
    for ticker, entry in stocks.items():
        total = len(entry.get("mentions", []))
        sector = entry.get("sector", "")
        style  = entry.get("style", "")
        for m in entry.get("mentions", []):
            if m.get("date", "") < cutoff:
                continue
            key = (ticker, m["date"], m.get("segment", ""))
            row = {"ticker": ticker, "company": entry.get("company", ""),
                   "sector": sector, "style": style, "total_mentions": total, **m}
            groups.setdefault(key, []).append(row)
    # Deduplicate: use mode sentiment; break ties by highest conviction (SENTIMENT_ORDER)
    mentions = []
    for rows in groups.values():
        if len(rows) == 1:
            mentions.append(rows[0])
            continue
        counts = Counter(r.get("sentiment", "") for r in rows)
        max_count = max(counts.values())
        modal_sents = {s for s, c in counts.items() if c == max_count}
        # Among modal sentiments, pick the one with highest conviction
        chosen_sent = min(modal_sents, key=lambda s: _sent_rank.get(s, 99))
        # Use the first row that has the chosen sentiment as the base row
        chosen_row = next(r for r in rows if r.get("sentiment") == chosen_sent)
        mentions.append(chosen_row)
    mentions.sort(key=lambda x: x["date"], reverse=True)
    out = {"generated": date.today().isoformat(), "mentions": mentions}
    (TICKER_DATA_DIR / "recent.json").write_text(json.dumps(out, separators=(",", ":")))


def _market_cap_category(market_cap: float | None) -> str:
    """Classify market cap into standard size categories."""
    if market_cap is None:
        return ""
    if market_cap >= 200_000_000_000:
        return "mega"
    if market_cap >= 10_000_000_000:
        return "large"
    if market_cap >= 2_000_000_000:
        return "mid"
    if market_cap >= 300_000_000:
        return "small"
    if market_cap >= 50_000_000:
        return "micro"
    return "nano"


def _fetch_ticker_metadata(tickers: list[str]) -> dict[str, dict]:
    """Fetch sector, industry, style, pe_ratio, market_cap for each ticker via yfinance.

    Uses 3 workers with a 0.5 s per-request sleep to stay well under Yahoo
    Finance's rate limit (~6 req/s vs the 8-worker burst that caused lockouts).
    """
    import time
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _one(ticker):
        time.sleep(0.5)   # throttle to avoid Yahoo Finance rate limits
        try:
            info = yf.Ticker(ticker).info
            sector   = info.get("sector")   or ""
            industry = info.get("industry") or ""
            pe       = info.get("trailingPE")
            mktcap   = info.get("marketCap")

            if pe is None or pe <= 0:
                style = ""
            elif pe > 30:
                style = "growth"
            elif pe < 12:
                style = "value"
            else:
                style = "blend"

            return ticker, {
                "sector":               sector,
                "industry":             industry,
                "style":                style,
                "pe_ratio":             round(pe, 2) if pe else None,
                "market_cap":           mktcap,
                "market_cap_category":  _market_cap_category(mktcap),
            }
        except Exception:
            return ticker, {
                "sector": "", "industry": "", "style": "",
                "pe_ratio": None, "market_cap": None, "market_cap_category": "",
            }

    result = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_one, t): t for t in tickers}
        for i, f in enumerate(as_completed(futures), 1):
            ticker, meta = f.result()
            result[ticker] = meta
            if i % 50 == 0:
                print(f"  {i}/{len(tickers)} tickers fetched…")
    return result


def fetch_all_sectors() -> None:
    """Batch-fetch sector/industry/style/pe_ratio/market_cap for tickers missing that data."""
    if not SENTIMENTS_FILE.exists():
        print("stock_sentiments.json not found.")
        return
    db = json.loads(SENTIMENTS_FILE.read_text())
    stocks = db.get("stocks", {})
    # Only target tickers that have no sector yet — avoids unnecessary rate-limiting
    # and prevents overwriting good data with empty strings on a rate-limited response.
    tickers = [t for t, v in stocks.items() if not v.get("sector")]
    if not tickers:
        print("All tickers already have sector data.")
        return
    print(f"Fetching metadata for {len(tickers)} tickers missing sector data…")
    metadata = _fetch_ticker_metadata(tickers)
    updated = 0
    for ticker, meta in metadata.items():
        if ticker not in stocks or not meta["sector"]:
            # Don't overwrite existing data with an empty result (e.g. rate limit hit)
            continue
        stocks[ticker]["sector"]              = meta["sector"]
        stocks[ticker]["industry"]            = meta["industry"]
        stocks[ticker]["style"]               = meta["style"]
        stocks[ticker]["pe_ratio"]            = meta["pe_ratio"]
        stocks[ticker]["market_cap"]          = meta["market_cap"]
        stocks[ticker]["market_cap_category"] = meta["market_cap_category"]
        updated += 1
        # Sync to SQLite
        upsert_stock(
            ticker=ticker,
            company=stocks[ticker].get("company", ""),
            sector=meta["sector"] or None,
            industry=meta["industry"] or None,
            style=meta["style"] or None,
            pe_ratio=meta["pe_ratio"],
            market_cap=meta["market_cap"],
            market_cap_category=meta["market_cap_category"] or None,
        )
    db["stocks"] = stocks
    SENTIMENTS_FILE.write_text(json.dumps(db, indent=2))
    _write_ticker_shards(stocks)
    print(f"Updated metadata for {updated}/{len(tickers)} tickers.")


def _sync_mentions_from_db(stocks: dict) -> None:
    """Overwrite mention lists in stocks dict with data pulled from the DB.

    The DB is the authoritative source for mention data after any manual
    correction (ticker rename, deletion, price fix).  stock_sentiments.json
    is authoritative only for ticker metadata (company, sector, style).
    """
    from db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, date, sentiment, segment, note, closing_price
        FROM mentions ORDER BY ticker, date
    """)
    rows = cur.fetchall()
    conn.close()

    db_mentions: dict[str, list] = {}
    for row in rows:
        ticker = row["ticker"]
        db_mentions.setdefault(ticker, []).append({
            "date":          row["date"],
            "sentiment":     row["sentiment"],
            "segment":       row["segment"],
            "note":          row["note"],
            "closing_price": row["closing_price"],
        })

    # Add stub entries for DB tickers not yet in JSON metadata
    for ticker in db_mentions:
        if ticker not in stocks:
            stocks[ticker] = {"company": ticker, "sector": "", "style": "", "mentions": []}

    # Overwrite mentions from DB; tickers removed from DB get empty lists (pruned below)
    for ticker in list(stocks):
        stocks[ticker]["mentions"] = db_mentions.get(ticker, [])

    # Prune tickers that have been fully deleted from the DB
    for ticker in [t for t, e in stocks.items() if not e.get("mentions")]:
        del stocks[ticker]


def rebuild_ticker_shards() -> None:
    """Rebuild all per-ticker shards, syncing mention data from the DB first.

    After any manual DB correction (ticker rename, deletion, closing-price fix)
    simply run --rebuild-shards and the shards will reflect the current DB state
    without needing to also hand-edit stock_sentiments.json.
    """
    if not SENTIMENTS_FILE.exists():
        print("stock_sentiments.json not found.")
        return
    db_json = json.loads(SENTIMENTS_FILE.read_text())
    stocks = db_json.get("stocks", {})

    # DB is authoritative for mention data — sync before building shards
    _sync_mentions_from_db(stocks)

    # Persist synced state back to stock_sentiments.json so it stays consistent
    SENTIMENTS_FILE.write_text(json.dumps(db_json, separators=(",", ":")))

    _write_ticker_shards(stocks)
    print(f"Wrote {len(stocks)} ticker shards + index.json to {TICKER_DATA_DIR}")


def update_all_prices() -> None:
    """Fetch/refresh price history files for all public tickers with recent mentions."""
    if not SENTIMENTS_FILE.exists():
        print("stock_sentiments.json not found.")
        return
    db = json.loads(SENTIMENTS_FILE.read_text())
    stocks = db.get("stocks", {})
    write_price_files(stocks)
    print(f"Done. Price files written to {TICKER_DATA_DIR}")


def _update_db_closing_price(ticker: str, date: str, segment: str, price: float) -> None:
    """Update closing_price in the DB for a specific mention row."""
    from db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE mentions SET closing_price=? WHERE ticker=? AND date=? AND segment=?",
        (price, ticker, date, segment),
    )
    conn.commit()
    conn.close()


def backfill_prices(tickers: list[str] | None = None) -> None:
    """Fetch closing prices for mentions that are missing them.

    Args:
        tickers: if supplied, re-fetch prices for these specific tickers even
                 when a closing_price already exists.  Use this after a manual
                 ticker correction in the DB so the old (wrong-ticker) price is
                 replaced with the correct one.
                 Example: --backfill-prices --tickers LITE,CRWV
    """
    if not SENTIMENTS_FILE.exists():
        print("stock_sentiments.json not found.")
        return
    force_set = {t.upper() for t in tickers} if tickers else set()
    if force_set:
        print(f"Force-refreshing prices for: {', '.join(sorted(force_set))}")
    db = json.loads(SENTIMENTS_FILE.read_text())
    filled = skipped = failed = 0
    for ticker, entry in db.get("stocks", {}).items():
        force = ticker in force_set
        for mention in entry.get("mentions", []):
            if "closing_price" in mention and not force:
                skipped += 1
                continue
            if _is_private(ticker, mention["date"]):
                skipped += 1
                continue
            price = fetch_closing_price(ticker, mention["date"])
            if price is not None:
                mention["closing_price"] = price
                filled += 1
                print(f"  {ticker} {mention['date']} → ${price}")
                # Keep the DB in sync
                _update_db_closing_price(ticker, mention["date"], mention.get("segment", ""), price)
            else:
                failed += 1
                print(f"  {ticker} {mention['date']} → no data")
            time.sleep(0.3)
    SENTIMENTS_FILE.write_text(json.dumps(db, indent=2))
    print(f"\nDone. Filled: {filled}  Already had price: {skipped}  No data: {failed}")


# ── 5. Podcast RSS + Overcast links ───────────────────────────────────────────

def _parse_rss_pubdate(pubdate_str: str) -> date | None:
    """Parse RFC 2822 pubDate like 'Wed, 17 Sep 2025 22:00:00 +0000'."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(pubdate_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def find_podcast_episode(date_str: str) -> str | None:
    """
    Fetch Mad Money RSS feed and return the audio enclosure URL for the episode
    matching date_str (YYYY-MM-DD), or None if not found.
    """
    target = date.fromisoformat(date_str)
    try:
        resp = requests.get(MAD_MONEY_RSS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  RSS fetch failed: {e}")
        return None

    root = ET.fromstring(resp.content)
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}

    for item in root.iter("item"):
        pubdate_el = item.find("pubDate")
        if pubdate_el is None or not pubdate_el.text:
            continue
        ep_date = _parse_rss_pubdate(pubdate_el.text)
        if ep_date != target:
            continue
        enclosure = item.find("enclosure")
        if enclosure is not None:
            return enclosure.get("url")

    return None


def yt_link(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


def overcast_fm_link(episode_id: str, seconds: int) -> str:
    """Build https://overcast.fm/+EPISODE_ID/[H:]M:SS universal link."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"https://overcast.fm/+{episode_id}/{h}:{m:02d}:{s:02d}"
    return f"https://overcast.fm/+{episode_id}/{m}:{s:02d}"


def _load_overcast_cache() -> dict:
    if OVERCAST_CACHE_FILE.exists():
        return json.loads(OVERCAST_CACHE_FILE.read_text())
    return {}


def _save_overcast_cache(cache: dict) -> None:
    OVERCAST_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def fetch_overcast_episode_id(date_str: str) -> str | None:
    """
    Log into Overcast, fetch the Mad Money podcast page, and return the
    Overcast episode ID (e.g. 'AApaDLzNP6o') for the given date.
    Caches results in data/overcast_episode_ids.json.
    Returns None if credentials are missing or episode not found.
    """
    cache = _load_overcast_cache()
    if date_str in cache:
        return cache[date_str]

    email = os.environ.get("OVERCAST_EMAIL")
    password = os.environ.get("OVERCAST_PASSWORD")
    if not email or not password:
        print("  OVERCAST_EMAIL/OVERCAST_PASSWORD not set — using YouTube fallback links")
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })

    try:
        resp = session.post(
            "https://overcast.fm/login",
            data={"email": email, "password": password, "then": "podcasts"},
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
        # Overcast returns 200 on bad credentials but body contains the login form again
        if 'name="password"' in resp.text:
            print("  Overcast login failed — check OVERCAST_EMAIL and OVERCAST_PASSWORD")
            return None
    except Exception as e:
        print(f"  Overcast login error: {e}")
        return None

    try:
        resp = session.get(OVERCAST_PODCAST_URL, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Overcast podcast page fetch failed: {e}")
        return None

    # Episode links look like: href="/+AApaDLzNP6o"
    # Titles look like: "Mad Money w/ Jim Cramer 6/11/26"
    target = datetime.fromisoformat(date_str)
    date_patterns = [
        target.strftime("%-m/%-d/%y"),    # "6/11/26"
        target.strftime("%-m/%-d/%Y"),    # "6/11/2026"
        target.strftime("%B %-d, %Y"),    # "June 11, 2026"
        target.strftime("%b %-d, %Y"),    # "Jun 11, 2026"
    ]

    # Title lives in <div class="title singleline"> inside each <a href="/+ID"> block
    for match in re.finditer(
        r'href="/\+([A-Za-z0-9]+)"[^>]*>.*?<div class="title singleline">([^<]+)</div>',
        resp.text, re.S,
    ):
        ep_id, title = match.group(1), match.group(2).strip()
        for pat in date_patterns:
            if pat in title:
                cache[date_str] = ep_id
                _save_overcast_cache(cache)
                print(f"  Overcast episode ID: {ep_id}  (matched '{title}')")
                return ep_id

    print(f"  No Overcast episode found for {date_str} — using YouTube fallback links")
    return None


# ── 6. GitHub Pages redirect pages ────────────────────────────────────────────

def _section_slug(name: str) -> str:
    """'Interview: Honeywell International (HON)' → 'interview-honeywell-international-hon'"""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _redirect_page_html(section_name: str, date_label: str, time_label: str,
                        overcast_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{section_name} · Mad Money {date_label}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, Arial, sans-serif; background: #f6f8fa;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; padding: 20px; }}
    .card {{ background: #fff; border-radius: 16px; padding: 32px 28px;
             max-width: 380px; width: 100%; text-align: center;
             box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
    .show  {{ font-size: 12px; font-weight: 600; letter-spacing: .08em;
              color: #8b949e; text-transform: uppercase; margin-bottom: 6px; }}
    h1     {{ font-size: 20px; color: #24292f; margin-bottom: 6px; line-height: 1.3; }}
    .meta  {{ font-size: 13px; color: #8b949e; margin-bottom: 28px; }}
    .btn   {{ display: block; background: #fc7a1e; color: #fff; padding: 15px 20px;
              border-radius: 12px; text-decoration: none; font-size: 17px;
              font-weight: 600; margin-bottom: 12px; }}
    .btn:active {{ opacity: .85; }}
    .hint  {{ font-size: 12px; color: #8b949e; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="show">Mad Money · Jim Cramer</div>
    <h1>{section_name}</h1>
    <div class="meta">{date_label} &middot; {time_label}</div>
    <a class="btn" href="{overcast_url}">🎙 Open in Overcast</a>
    <div class="hint">Tap the button to jump to this moment in the episode.</div>
  </div>
</body>
</html>"""


def generate_redirect_pages(analysis: dict, date_str: str,
                             overcast_episode_id: str | None = None,
                             audio_url: str | None = None) -> dict[str, str]:
    """
    Write one HTML redirect page per section (and subsection).
    Returns a dict mapping section start_seconds → GitHub Pages URL.

    Prefers Overcast universal links (https://overcast.fm/+ID/MM:SS) when
    overcast_episode_id is provided; falls back to the RSS audio URL approach.
    Returns {} if neither is available.
    """
    if not overcast_episode_id and not audio_url:
        return {}

    dt = datetime.fromisoformat(date_str)
    date_label = dt.strftime("%b %-d, %Y")
    redirect_dir = DOCS_DIR / "redirect" / date_str
    redirect_dir.mkdir(parents=True, exist_ok=True)

    pages: dict[str, str] = {}

    def _write(section: dict, parent_slug: str = "") -> None:
        secs = section.get("start_seconds", 0)
        name = section.get("name", "section")
        slug = _section_slug(name)
        if parent_slug:
            slug = f"{parent_slug}-{slug}"
        time_label = _fmt_seconds(secs)
        if overcast_episode_id:
            oc_url = overcast_fm_link(overcast_episode_id, secs)
        else:
            oc_url = f"overcast://x-callback-url/add?url={quote(audio_url)}&t={secs}"
        html = _redirect_page_html(name, date_label, time_label, oc_url)
        page_path = redirect_dir / f"{slug}.html"
        page_path.write_text(html)
        pages[secs] = f"{GITHUB_PAGES_BASE}/redirect/{date_str}/{slug}.html"

        for sub in section.get("subsections", []):
            _write(sub, parent_slug=slug)

    for section in analysis.get("sections", []):
        _write(section)

    return pages


# ── 7. HTML email formatter ────────────────────────────────────────────────────

def _sentiment_badge(sentiment: str) -> str:
    color = SENTIMENT_COLORS.get(sentiment, "#8b949e")
    label = sentiment.replace("_", " ").upper()
    return (
        f'<span style="background:{color};color:#fff;padding:2px 7px;'
        f'border-radius:3px;font-size:11px;font-weight:bold">{label}</span>'
    )


def _fmt_seconds(s: int) -> str:
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _section_segments(section_name: str) -> set[str]:
    """Map a section display name to the stock segment values it corresponds to."""
    name = section_name.lower()
    if "lightning" in name:
        return {"lightning_round"}
    if "opening" in name or "episode summary" in name:
        return {"opening_commentary"}
    if "closing" in name:
        return {"closing_commentary"}
    if "caller" in name or "q&a" in name or "q & a" in name:
        return {"caller_qa"}
    if "interview" in name:
        return {"interview"}
    if "in-depth" in name or "in depth" in name or "deep dive" in name:
        return {"in_depth_analysis"}
    return set()


def build_email_html(summaries: list[dict],
                     highlight_tickers: set[str] | None = None) -> str:
    """
    summaries: list of dicts with keys:
        date_str, analysis, audio_url (or None), video_id, redirect_pages
    highlight_tickers: tickers to highlight in yellow (defaults to USER_HOLDINGS)
    redirect_pages: dict mapping start_seconds (int) → GitHub Pages URL
    """
    hl = highlight_tickers if highlight_tickers is not None else USER_HOLDINGS
    parts = ["""
<html><head><meta charset="utf-8">
<style>
  body { font-family: -apple-system, Arial, sans-serif; color: #24292f;
         max-width: 700px; margin: 0 auto; padding: 20px; }
  h2   { color: #0969da; border-bottom: 2px solid #0969da; padding-bottom: 6px; }
  h3   { margin: 20px 0 4px; }
  h3 a { color: #24292f; text-decoration: none; }
  h3 a:hover { text-decoration: underline; }
  .market-headline { font-size: 15px; font-weight: 600; color: #0969da;
                     margin: 4px 0 6px; }
  .sec-headline { font-size: 13px; font-weight: 600; color: #24292f;
                  margin: 3px 0 4px; font-style: italic; }
  .sub   { margin-left: 20px; }
  .summary { color: #57606a; margin: 4px 0 6px; font-size: 14px; }
  ul.summary { color: #57606a; margin: 4px 0 6px 18px; font-size: 14px; }
  ul.summary li { margin-bottom: 3px; }
  .sec-tickers { margin: 0 0 14px; font-size: 12px; }
  .tlink { font-family: monospace; font-weight: bold; font-size: 11px;
           color: #0969da; text-decoration: none; background: #ddf4ff;
           padding: 2px 5px; border-radius: 3px; margin-right: 4px;
           white-space: nowrap; }
  .tlink:hover { text-decoration: underline; }
  table  { border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 13px; }
  th     { background: #f6f8fa; text-align: left; padding: 6px 10px;
           border-bottom: 2px solid #d0d7de; }
  td     { padding: 5px 10px; border-bottom: 1px solid #d0d7de;
           vertical-align: top; }
  .ticker  { font-weight: bold; font-family: monospace; }
  .holding { background: #fff8c5; }
  .holding .ticker::after { content: " ★"; font-size: 10px; color: #9a6700; }
  .note    { color: #57606a; font-size: 12px; }
  .footer { margin-top: 24px; color: #8b949e; font-size: 11px; border-top: 1px solid #d0d7de; padding-top: 8px; }
</style></head><body>
"""]

    for ep in summaries:
        analysis = ep["analysis"]
        video_id = ep["video_id"]
        redirect_pages = ep.get("redirect_pages", {})
        overcast_id = ep.get("overcast_episode_id")
        ep_date = analysis.get("episode_date", ep["date_str"])
        dt = datetime.fromisoformat(ep_date)
        date_label = dt.strftime("%A, %B %-d, %Y")

        parts.append(f'<h2>Mad Money &mdash; {date_label}</h2>')
        if analysis.get("market_headline"):
            parts.append(f'<p class="market-headline">{analysis["market_headline"]}</p>')
        market_bullets = analysis.get("market_bullets")
        if market_bullets and isinstance(market_bullets, list):
            items = "".join(f"<li>{b}</li>" for b in market_bullets)
            parts.append(f'<ul class="summary">{items}</ul>')
        elif analysis.get("market_summary"):
            parts.append(f'<p class="summary">{analysis["market_summary"]}</p>')

        stocks = analysis.get("stocks", [])

        def _ticker_links(section_name: str) -> str:
            segs = _section_segments(section_name)
            tickers = [s["ticker"] for s in stocks
                       if s.get("segment") in segs and s.get("ticker")]
            if not tickers:
                return ""
            links = "".join(
                f'<a class="tlink" href="#ticker-{t}" '
                f'style="{"background:#fff8c5;border:1px solid #d4a017;" if t in hl else ""}">'
                f'{t}{"★" if t in hl else ""}</a>'
                for t in tickers
            )
            return f'<p class="sec-tickers">{links}</p>'

        def _section_parts(section: dict, indent: bool = False,
                           display_name: str = "") -> None:
            secs = section.get("start_seconds", 0)
            ts_label = _fmt_seconds(secs)
            name = section.get("name", "")
            show_name = display_name or name
            if overcast_id:
                href = overcast_fm_link(overcast_id, secs)
                icon = "🎙"
            elif secs in redirect_pages:
                href = redirect_pages[secs]
                icon = "🎙"
            else:
                href = yt_link(video_id, secs)
                icon = "▶"
            tag_open = '<div class="sub">' if indent else ""
            tag_close = "</div>" if indent else ""
            headline = section.get("headline", "")
            ticker_html = _ticker_links(name)
            bullets = section.get("bullets")
            if bullets and isinstance(bullets, list):
                body_html = '<ul class="summary">' + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
            else:
                body_html = f'<p class="summary">{section.get("summary", "")}</p>'
            parts.append(
                f'{tag_open}'
                f'<h3><a href="{href}">{icon} {show_name} [{ts_label}]</a></h3>'
                + (f'<p class="sec-headline">{headline}</p>' if headline else "")
                + body_html
                + ticker_html
                + tag_close
            )

        for i, section in enumerate(analysis.get("sections", [])):
            name = section.get("name", "")
            if i == 0 and not name.lower().startswith("episode summary"):
                display_name = f"Episode Summary: {name}"
            else:
                display_name = name
            _section_parts(section, display_name=display_name)

        # Stock table
        if stocks:
            parts.append('<h3>Stocks Mentioned</h3>')
            parts.append(
                '<table><tr>'
                '<th>Ticker</th><th>Company</th><th>Sentiment</th>'
                '<th>Segment</th><th>Note</th>'
                '</tr>'
            )
            for s in stocks:
                seg = s.get("segment", "").replace("_", " ").title()
                pt = ""
                if "price_target" in s:
                    pt = f' (target ${s["price_target"]})'
                elif "price_level" in s:
                    pt = f' (at ${s["price_level"]})'
                ticker = s.get("ticker", "")
                row_class = ' class="holding"' if ticker in hl else ""
                note = s.get("note", "")
                ticker_note = s.get("ticker_note", "")
                note_html = note
                if ticker_note:
                    note_html += f'<br><em style="color:#f0a030;font-size:11px">{ticker_note}</em>'
                parts.append(
                    f'<tr id="ticker-{ticker}"{row_class}>'
                    f'<td class="ticker">{ticker}</td>'
                    f'<td>{s.get("company","")}</td>'
                    f'<td>{_sentiment_badge(s.get("sentiment","neutral"))}{pt}</td>'
                    f'<td>{seg}</td>'
                    f'<td class="note">{note_html}</td>'
                    f'</tr>'
                )
            parts.append('</table>')

        parts.append('<br>')

    has_overcast_id = any(ep.get("overcast_episode_id") for ep in summaries)
    has_redirect = any(ep.get("redirect_pages") for ep in summaries)
    if has_overcast_id:
        link_note = "🎙 section links open directly in Overcast at that timestamp"
    elif has_redirect:
        link_note = "🎙 section links open a redirect page that jumps to Overcast"
    else:
        link_note = "▶ section links open on YouTube (Overcast episode ID not found)"
    parts.append(
        f'<div class="footer">Generated by Claude Haiku &middot; {link_note} &middot; '
        f'stock_sentiments.json updated</div>'
    )
    parts.append("</body></html>")
    return "\n".join(parts)


# ── 7. Email delivery ──────────────────────────────────────────────────────────

def send_email_smtp(html: str, subject: str, recipient: str | None = None) -> None:
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD environment variable not set")

    sender = os.environ.get("GMAIL_FROM", GMAIL_FROM)
    recipient = recipient or os.environ.get("GMAIL_TO", GMAIL_TO)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(*GMAIL_SMTP) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"  Email sent to {recipient}")


def send_email_mcp(html: str, subject: str) -> None:
    """
    Placeholder for Gmail MCP delivery used by the cloud-scheduled agent.
    When running as a cloud agent, replace this body with the MCP tool calls.
    """
    raise NotImplementedError(
        "MCP email mode is for use inside a Claude Code cloud agent. "
        "Run locally with --email-mode smtp instead."
    )


def send_email(html: str, subject: str, mode: str = "smtp",
               recipient: str | None = None) -> None:
    if mode == "smtp":
        send_email_smtp(html, subject, recipient=recipient)
    elif mode == "mcp":
        send_email_mcp(html, subject)
    else:
        raise ValueError(f"Unknown email mode: {mode!r}")


# ── 9. Git commit + push ──────────────────────────────────────────────────────

def commit_and_push(date_str: str) -> None:
    """Stage docs/ and data/, commit, and push to origin/main."""
    try:
        subprocess.run(["git", "add", "docs/", "data/"], cwd=ROOT, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Mad Money {date_str}: redirect pages + sentiment update"],
            cwd=ROOT, check=True,
        )
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
        print("  Pushed redirect pages to GitHub Pages")
    except subprocess.CalledProcessError as e:
        print(f"  Git push failed: {e} — links will use YouTube fallback until next push")


# ── Redirect page repair utility ──────────────────────────────────────────────

def fix_redirect_pages(date_str: str) -> None:
    """
    Re-generate redirect pages for an already-processed date using the
    correct Overcast universal link format (https://overcast.fm/+ID/MM:SS).

    Reads existing pages from docs/redirect/DATE/, extracts section names and
    timestamps from the old HTML, fetches the Overcast episode ID, then rewrites
    each page with the corrected URL.
    """
    redirect_dir = DOCS_DIR / "redirect" / date_str
    if not redirect_dir.exists():
        print(f"No redirect pages found for {date_str} — nothing to fix.")
        return

    overcast_episode_id = fetch_overcast_episode_id(date_str)
    if not overcast_episode_id:
        print("Cannot fix redirect pages without Overcast episode ID.")
        return

    dt = datetime.fromisoformat(date_str)
    date_label = dt.strftime("%b %-d, %Y")

    fixed = 0
    for page in redirect_dir.glob("*.html"):
        content = page.read_text()
        # Extract seconds from old overcast://x-callback-url/add?...&t=SECONDS
        m_t = re.search(r"[?&]t=(\d+)", content)
        # Extract section name from <h1>
        m_name = re.search(r"<h1>([^<]+)</h1>", content)
        if not m_t or not m_name:
            print(f"  Could not parse {page.name} — skipping")
            continue
        secs = int(m_t.group(1))
        name = m_name.group(1)
        time_label = _fmt_seconds(secs)
        oc_url = overcast_fm_link(overcast_episode_id, secs)
        page.write_text(_redirect_page_html(name, date_label, time_label, oc_url))
        fixed += 1
        print(f"  Fixed {page.name} → {oc_url}")

    print(f"Fixed {fixed} redirect pages for {date_str}.")


# ── Main ───────────────────────────────────────────────────────────────────────

def _cookie_age_days() -> int | None:
    """Return age of YOUTUBE_COOKIE_FILE in days, or None if not using a file."""
    path = os.environ.get("YOUTUBE_COOKIE_FILE")
    if not path:
        return None
    try:
        return int((time.time() - Path(path).stat().st_mtime) / 86400)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-episodes", type=int, default=1,
                        help="Max new episodes to process (default: 1)")
    parser.add_argument("--email-mode", choices=["smtp", "mcp"], default="smtp",
                        help="Email delivery mode (default: smtp)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze and format but do not send email")
    parser.add_argument("--fix-redirects", metavar="DATE",
                        help="Re-generate existing redirect pages for DATE (YYYY-MM-DD) "
                             "with correct Overcast universal links")
    parser.add_argument("--backfill-prices", action="store_true",
                        help="Fetch closing prices for all mentions missing them in stock_sentiments.json")
    parser.add_argument("--tickers", metavar="TICKER1,TICKER2",
                        help="With --backfill-prices: comma-separated tickers to force-refresh "
                             "even when a closing price already exists (use after ticker corrections)")
    parser.add_argument("--rebuild-shards", action="store_true",
                        help="Rebuild all per-ticker JSON shards in docs/data/ from stock_sentiments.json")
    parser.add_argument("--update-prices", action="store_true",
                        help="Fetch/refresh daily price history files for all active tickers in docs/data/")
    parser.add_argument("--fetch-sectors", action="store_true",
                        help="Batch-fetch sector/style from Yahoo Finance for all tickers and rebuild shards")
    args = parser.parse_args()

    age = _cookie_age_days()
    if age is not None:
        if age > 60:
            print(f"\n⚠️  WARNING: YouTube cookie file is {age} days old — refresh soon or the pipeline may fail.\n")
        else:
            print(f"  YouTube cookie file age: {age} days")

    if args.fix_redirects:
        fix_redirect_pages(args.fix_redirects)
        return

    if args.rebuild_shards:
        rebuild_ticker_shards()
        return

    if args.update_prices:
        update_all_prices()
        return

    if args.fetch_sectors:
        fetch_all_sectors()
        return

    if args.backfill_prices:
        tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
        backfill_prices(tickers=tickers)
        return

    episodes = discover_new_episodes(args.max_episodes)
    if not episodes:
        print("No new episodes found.")
        return

    print(f"Found {len(episodes)} new episode(s):")
    for ep in episodes:
        print(f"  {ep['id']} — {ep['title']}")

    summaries = []
    processed = load_processed()

    for ep in episodes:
        video_id = ep["id"]
        print(f"\n── Processing {video_id} ──")

        print("  Fetching transcript...")
        date_str, snippets, transcript_text = fetch_transcript(
            video_id, ep.get("upload_date", "")
        )
        print(f"  Date: {date_str}  Lines: {len(snippets)}")

        print("  Analyzing with Claude Haiku...")
        analysis = analyze_with_haiku(date_str, transcript_text)
        n_stocks = len(analysis.get("stocks", []))
        n_sections = len(analysis.get("sections", []))
        print(f"  Sections: {n_sections}  Stocks: {n_stocks}")

        print("  Updating stock_sentiments.json...")
        update_stock_sentiments(analysis, video_id=video_id)

        print("  Looking up podcast episode in RSS feed...")
        audio_url = find_podcast_episode(date_str)

        print("  Looking up Overcast episode ID...")
        overcast_episode_id = fetch_overcast_episode_id(date_str)

        # Update episode row with transcript and overcast ID now that we have them
        upsert_episode(
            date=date_str,
            video_id=video_id,
            transcript_text=transcript_text,
            overcast_episode_id=overcast_episode_id,
        )

        if overcast_episode_id:
            link_mode = "Overcast universal links (https://overcast.fm/+ID/MM:SS)"
        elif audio_url:
            link_mode = "GitHub Pages redirect (audio URL)"
        else:
            link_mode = "YouTube fallback"
        print(f"  Links: {link_mode}")

        print("  Generating redirect pages...")
        redirect_pages = generate_redirect_pages(
            analysis, date_str,
            overcast_episode_id=overcast_episode_id,
            audio_url=audio_url,
        )
        print(f"  Redirect pages: {len(redirect_pages)}")

        summaries.append({
            "date_str": date_str,
            "analysis": analysis,
            "audio_url": audio_url,
            "video_id": video_id,
            "redirect_pages": redirect_pages,
            "overcast_episode_id": overcast_episode_id,
        })
        processed.append({"video_id": video_id, "date": date_str})

    # Build email
    dates = [s["date_str"] for s in summaries]
    total_stocks = sum(len(s["analysis"].get("stocks", [])) for s in summaries)
    if len(dates) == 1:
        dt = datetime.fromisoformat(dates[0])
        subject = f"Mad Money — {dt.strftime('%a %b %-d')} · {total_stocks} stocks"
    else:
        subject = f"Mad Money — {dates[-1]} to {dates[0]} · {total_stocks} stocks"

    # Push redirect pages to GitHub Pages (needed before email so links are live)
    if not args.dry_run:
        print("\nPushing redirect pages to GitHub...")
        commit_and_push(dates[0])

    html = build_email_html(summaries)

    # Check if any episode mentions a ticker from the brother's watch list
    all_tickers = {
        s.get("ticker", "").upper()
        for ep in summaries
        for s in ep["analysis"].get("stocks", [])
    }
    brother_hits = all_tickers & BROTHER_TICKERS

    # Archive one HTML summary per episode date
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    for ep_summary in summaries:
        ep_html = build_email_html([ep_summary])
        arc = SUMMARIES_DIR / f"{ep_summary['date_str']}_summary.html"
        arc.write_text(ep_html)
        print(f"  Archived summary → {arc.name}")

    if args.dry_run:
        out = OUTPUT_DIR / f"{dates[0]}_email_preview.html"
        out.write_text(html)
        print(f"\nDry run — redirect pages written to docs/ (not pushed)")
        print(f"Email preview saved to {out}")
        if brother_hits:
            bro_html = build_email_html(summaries, highlight_tickers=BROTHER_TICKERS)
            bro_out = OUTPUT_DIR / f"{dates[0]}_email_preview_brother.html"
            bro_out.write_text(bro_html)
            print(f"Brother preview saved to {bro_out} (hits: {', '.join(sorted(brother_hits))})")
    else:
        print(f"\nSending email: {subject}")
        send_email(html, subject, mode=args.email_mode)
        if brother_hits:
            print(f"  Brother's tickers mentioned: {', '.join(sorted(brother_hits))} — sending copy to {BROTHER_TO}")
            bro_html = build_email_html(summaries, highlight_tickers=BROTHER_TICKERS)
            send_email(bro_html, subject, mode=args.email_mode, recipient=BROTHER_TO)

    save_processed(processed)
    print("\nDone.")


if __name__ == "__main__":
    main()
