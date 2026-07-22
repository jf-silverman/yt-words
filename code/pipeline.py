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
import base64
import csv
import io
import json
from collections import Counter
import os
import re
import smtplib
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date, timezone, timedelta
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

import anthropic
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import requests
import yt_dlp

matplotlib.use('Agg')  # Use non-interactive backend for server/batch use

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
EMAIL_PREVIEW_DIR = DATA_DIR / "email_previews"
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
    # Public in Korea long before this, but no US listing until the Nasdaq ADR
    # (2026-07-10). Cramer discussed the pending $29B raise on 2026-07-08, so that
    # mention has no US close — same shape as a pre-IPO row.
    "SKHY": {"name": "SK Hynix", "ipo_date": "2026-07-10"},
}


def _is_private(ticker: str, date_str: str) -> bool:
    """Return True if ticker had no public market on date_str."""
    info = PRIVATE_COMPANIES.get(ticker)
    if not info:
        return False
    if info["ipo_date"] is None:
        return True
    return date_str < info["ipo_date"]


def _ticker_display(ticker: str, date_str: str) -> str:
    """Wrap tickers with no public market yet in +...+, e.g. +ANTH+."""
    return f"+{ticker}+" if _is_private(ticker, date_str) else ticker

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

    # Log upload vs. fetch timing to help track when transcripts become available
    yt_ts = (info or {}).get("timestamp") or (info or {}).get("release_timestamp")
    fetch_utc = datetime.now(tz=timezone.utc)
    timing_file = DATA_DIR / "transcript_timing.csv"
    write_header = not timing_file.exists()
    with open(timing_file, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["episode_date", "video_id", "yt_upload_utc", "pipeline_fetch_utc"])
        yt_upload_str = ""
        if yt_ts:
            yt_upload_utc = datetime.fromtimestamp(yt_ts, tz=timezone.utc)
            yt_upload_str = yt_upload_utc.strftime("%Y-%m-%d %H:%M")
            lag_hrs = (fetch_utc - yt_upload_utc).total_seconds() / 3600
            print(f"  YouTube upload: {yt_upload_str} UTC  |  fetch lag: {lag_hrs:.1f}h")
        else:
            print(f"  YouTube upload time not available in metadata")
        w.writerow([date_str, video_id, yt_upload_str, fetch_utc.strftime("%Y-%m-%d %H:%M")])

    return date_str, [], text


# ── 3. Haiku analysis ──────────────────────────────────────────────────────────

ANALYSIS_MODEL = "claude-haiku-4-5-20251001"

# A stock-heavy episode emits ~30k chars of JSON. At 8192 the 2026-07-20 episode
# truncated mid-string ("Unterminated string ... char 28896") and the whole episode was
# skipped, so give the response real headroom — unused tokens cost nothing.
ANALYSIS_MAX_TOKENS = 32000


def analyze_with_haiku(date_str: str, transcript_text: str) -> dict:
    """Call Claude Haiku with the Mad Money rules. Returns parsed analysis dict."""
    system_prompt = RULES_FILE.read_text()
    client = anthropic.Anthropic()

    message = client.messages.create(
        model=ANALYSIS_MODEL,
        max_tokens=ANALYSIS_MAX_TOKENS,
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


def _claude_bin() -> str:
    """Absolute path to the `claude` CLI.

    cron runs with a minimal PATH (/usr/bin:/bin), so a bare "claude" resolves fine in an
    interactive shell but raises FileNotFoundError under the nightly job. Resolve it here
    instead of relying on PATH.
    """
    import shutil, os

    found = shutil.which("claude")
    if found:
        return found
    for cand in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude",
                 os.path.expanduser("~/.local/bin/claude"),
                 os.path.expanduser("~/.claude/local/claude")):
        if os.path.exists(cand):
            return cand
    raise RuntimeError(
        "claude CLI not found on PATH or in the usual install locations. "
        "Install it, or run with --backend api to use Haiku API credits instead."
    )


def analyze_with_claude_code(date_str: str, transcript_text: str) -> dict:
    """Analyze using the claude CLI (Claude Code subscription — no API credits).

    Flags mirror backfill.py: pin the model explicitly (without --model this inherits
    whatever the session default is), and strip tools/settings/MCP/hooks. This is a pure
    text-in JSON-out call, and the nightly run executes *inside the project directory* —
    without --setting-sources "" it would pick up CLAUDE.md, skills and hooks and behave
    unpredictably.
    """
    import subprocess, os

    user_message = f"Episode date: {date_str}\n\nTranscript:\n{transcript_text}"
    system_prompt = RULES_FILE.read_text()

    # ANTHROPIC_API_KEY forces the CLI onto the API path rather than the
    # claude.ai subscription login, causing "connectors disabled" errors.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    result = subprocess.run(
        [
            _claude_bin(), "-p", user_message,
            "--system-prompt", system_prompt,
            "--model", ANALYSIS_MODEL,
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
        ],
        capture_output=True, text=True, env=env, timeout=900,
    )

    if result.returncode != 0:
        # Report BOTH streams. `claude -p` writes its failure reason (usage limit,
        # auth expiry, model refusal) to *stdout*, so reporting only stderr produced
        # an empty explanation and a nightly run that failed for no visible reason.
        detail = "\n".join(filter(None, [
            f"stderr: {result.stderr.strip()}" if result.stderr.strip() else "",
            f"stdout: {result.stdout.strip()[:2000]}" if result.stdout.strip() else "",
        ])) or "(both stdout and stderr were empty)"
        raise RuntimeError(f"claude CLI failed (rc={result.returncode}):\n{detail}")

    raw = result.stdout.strip()
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
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
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


def _clear_mentions_for_date(stocks: dict, date_str: str) -> set[str]:
    """Drop every mention for date_str from the in-memory JSON dict and from SQLite.

    Called before writing a fresh analysis so that re-processing a date *replaces*
    its mentions instead of layering new ones on top of the old ones.

    UNIQUE(episode_id, ticker, segment) only rejects an exact repeat, so without
    this a re-analysis that moves a call to a different segment — or names the same
    company under a different ticker — leaves both rows behind, and nothing about
    the result looks wrong. That is how 2026-07-08 came to hold the same Doncasters
    call as both DPC and '????', and six SK Hynix calls ended up under a bogus 'SK'
    carrying an unrelated company's closing price.

    Returns the tickers that lost mentions so their shards are rewritten even when
    the new analysis no longer mentions them at all.
    """
    from db import get_connection

    cleared: set[str] = set()
    for ticker, entry in stocks.items():
        mentions = entry.get("mentions", [])
        kept = [m for m in mentions if m.get("date") != date_str]
        if len(kept) != len(mentions):
            cleared.add(ticker)
            entry["mentions"] = kept

    conn = get_connection()
    conn.execute("""
        DELETE FROM mentions
        WHERE episode_id IN (SELECT id FROM episodes WHERE date = ?)
    """, (date_str,))
    conn.commit()
    conn.close()
    return cleared


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
        is_fund = 1 if analysis.get("episode_type") == "fundamentals" else 0
        episode_id = upsert_episode(date=episode_date, video_id=video_id,
                                    is_fundamentals=is_fund)
    else:
        episode_id = None

    # Make re-processing a date idempotent. Guarded on a non-empty analysis so a
    # degraded result can never wipe good data — the caller already treats
    # sections-but-no-stocks as a failure, and this is the second line of defence.
    cleared: set[str] = set()
    if analysis.get("stocks"):
        cleared = _clear_mentions_for_date(stocks, episode_date)

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
            # Throttle to avoid tripping Yahoo Finance rate limiting during bulk
            # backfill runs (~28 tickers/episode with no delay was hitting 429s
            # and burning the full 6s timeout on each failed call).
            time.sleep(0.15)
        entry["mentions"].append(mention)

        # Write to SQLite
        upsert_stock(
            ticker=ticker,
            # The established name wins over whatever the model called it tonight.
            # This was the other way round, so one bad guess in one episode
            # overwrote the DB's name for good: LRCX was stored as "Eli Lilly".
            # stock_sentiments.json is authoritative for company/sector/style, and
            # the DB should follow it rather than the other way round.
            company=entry.get("company") or stock.get("company", ""),
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
    # `cleared` covers tickers this analysis dropped entirely — without it their
    # shards would keep advertising a mention the DB no longer has.
    touched = {s.get("ticker", "").upper() for s in analysis.get("stocks", []) if s.get("ticker")}
    touched |= cleared
    _write_ticker_shards(stocks, only=touched)
    write_price_files(stocks, only=touched)


def _write_ticker_shards(stocks: dict, only: set[str] | None = None) -> None:
    """Write docs/data/{TICKER}.json shards and refresh docs/data/index.json."""
    import bisect
    from db import get_connection
    TICKER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    _BULLISH = {'strong_buy', 'buy', 'mild_buy', 'buy_on_pullback'}
    _BEARISH = {'sell_avoid', 'caution_concern'}

    conn = get_connection()
    cur = conn.cursor()

    # Latest closing price per ticker
    cur.execute("""
        SELECT ticker, close, date FROM daily_prices
        WHERE (ticker, date) IN (
            SELECT ticker, MAX(date) FROM daily_prices GROUP BY ticker
        )
    """)
    latest_prices = {r["ticker"]: {"price": r["close"], "date": r["date"]}
                     for r in cur.fetchall()}

    # Load mentions for pct_right_daily computation. Include closing_price IS
    # NULL rows too — a pre-IPO call made the day before a known IPO date (e.g.
    # SPCX calls made 6/11, IPO'd 6/12) has no closing_price of its own, but
    # enough was already known (target/expected open) to count as a real call.
    # Resolved below via _ticker_display's PRIVATE_COMPANIES ipo_date data.
    cur.execute("""
        SELECT ticker, date, sentiment, closing_price
        FROM mentions
        ORDER BY ticker, date
    """)
    m_by_ticker: dict = {}
    for r in cur.fetchall():
        t, dt, s, cp = r["ticker"], r["date"], r["sentiment"], r["closing_price"]
        if cp is None:
            info = PRIVATE_COMPANIES.get(t)
            if not info or not info.get("ipo_date"):
                continue  # no known IPO date to anchor a pre-listing call to
            day_before_ipo = (datetime.fromisoformat(info["ipo_date"]) - timedelta(days=1)).date().isoformat()
            if dt < day_before_ipo:
                continue  # too far ahead of the IPO to have a real price basis
            # cp resolved after daily prices are loaded, below
        m_by_ticker.setdefault(t, {}).setdefault(dt, {"price": cp, "sents": set()})
        m_by_ticker[t][dt]["sents"].add(s)

    # Load daily prices for all tickers
    cur.execute("SELECT ticker, date, close FROM daily_prices ORDER BY ticker, date")
    d_by_ticker: dict = {}
    for r in cur.fetchall():
        d_by_ticker.setdefault(r["ticker"], {})[r["date"]] = r["close"]
    d_sorted: dict = {t: sorted(dm.keys()) for t, dm in d_by_ticker.items()}

    conn.close()

    # Anchor any pre-IPO call's price to the first available daily close on
    # or after the call date (i.e. IPO day), since the call itself predates
    # the ticker having a real market price.
    for ticker, date_map in m_by_ticker.items():
        dates = d_sorted.get(ticker, [])
        if not dates:
            continue
        for dt, entry in list(date_map.items()):
            if entry["price"] is not None:
                continue
            idx = bisect.bisect_left(dates, dt)
            if idx < len(dates):
                entry["price"] = d_by_ticker[ticker][dates[idx]]
            else:
                del date_map[dt]

    # Small-sample threshold — matches the n_mentions >= 30 cutoff code/db.py
    # already uses for "small sample, treat with caution" hero sentences.
    SMALL_SAMPLE_N = 30

    # No minimum on tallied days — even a call whose window only runs a day
    # or two before the next mention still gets shown (flagged via
    # small_sample below 30 tallied days). Excluding thin windows would let
    # frequent call-changing quietly disappear from the stat rather than
    # being reflected in it. The only real floor is total >= 1 (a call with
    # zero subsequent trading days has nothing to divide).
    def _pack(total: int, right: int, calls: int | None = None) -> dict | None:
        if total < 1:
            return None
        out = {
            "pct": round(right / total * 100, 1),
            "n": total,
            "small_sample": total < SMALL_SAMPLE_N,
        }
        if calls is not None:
            out["calls"] = calls
        return out

    # For each ticker: walk call periods and tally right vs. wrong days,
    # split by call type (buy/sell), plus a separate fell/rose outcome split
    # for hold/wait calls (no right/wrong label — see notes/prediction-market-analysis.md).
    pct_right: dict = {}
    for ticker, date_map in m_by_ticker.items():
        daily = d_by_ticker.get(ticker, {})
        dates = d_sorted.get(ticker, [])
        if not dates:
            continue
        last_date = dates[-1]
        mention_dates = sorted(date_map.keys())
        buy_total = buy_right = buy_calls = 0
        sell_total = sell_right = sell_calls = 0
        hold_fell = hold_rose = hold_calls = 0
        for i, dt in enumerate(mention_dates):
            e = date_map[dt]
            sents = e["sents"]
            is_buy  = bool(sents & _BULLISH)
            is_sell = bool(sents & _BEARISH)
            call_price = e["price"]
            end_date = mention_dates[i + 1] if i + 1 < len(mention_dates) else last_date
            lo = bisect.bisect_right(dates, dt)
            hi = bisect.bisect_right(dates, end_date)
            window = dates[lo:hi]
            if is_buy:
                buy_calls += 1
                for d in window:
                    buy_total += 1
                    if daily[d] > call_price:
                        buy_right += 1
            elif is_sell:
                sell_calls += 1
                for d in window:
                    sell_total += 1
                    if daily[d] < call_price:
                        sell_right += 1
            elif "wait_hold_neutral" in {normalize_sentiment(s) for s in sents}:
                hold_calls += 1
                for d in window:
                    price = daily[d]
                    if price < call_price:
                        hold_fell += 1
                    elif price > call_price:
                        hold_rose += 1

        entry: dict = {}
        buy_stat = _pack(buy_total, buy_right, buy_calls)
        sell_stat = _pack(sell_total, sell_right, sell_calls)
        combined_stat = _pack(buy_total + sell_total, buy_right + sell_right, buy_calls + sell_calls)
        if buy_stat:
            entry["buy"] = buy_stat
        if sell_stat:
            entry["sell"] = sell_stat
        if combined_stat:
            entry["combined"] = combined_stat
        # Entry exists whenever there was at least one hold/wait call, even if
        # that call's window happened to have zero subsequent trading days
        # (e.g. it's the very last mention with no daily price after it) —
        # in that edge case fell_pct/rose_pct are None (rendered as N/A)
        # rather than a misleading 0%.
        hold_total = hold_fell + hold_rose
        if hold_calls >= 1:
            entry["hold_wait"] = {
                "fell_pct": round(hold_fell / hold_total * 100, 1) if hold_total else None,
                "rose_pct": round(hold_rose / hold_total * 100, 1) if hold_total else None,
                "n_fell": hold_fell,
                "n_rose": hold_rose,
                "calls": hold_calls,
                "small_sample": hold_total < SMALL_SAMPLE_N,
            }
        if entry:
            pct_right[ticker] = entry

    targets = only if only is not None else set(stocks.keys())
    for ticker in targets:
        if ticker in stocks and not is_unknown_ticker(ticker):
            lp = latest_prices.get(ticker)
            shard = {**stocks[ticker]}
            if lp:
                shard["price_latest"]      = lp["price"]
                shard["price_latest_date"] = lp["date"]
            pr = pct_right.get(ticker)
            if pr:
                combined = pr.get("combined")
                if combined:
                    # Kept for backward compatibility with existing front-end
                    # readers of the old combined-only fields.
                    shard["pct_right_daily"] = combined["pct"]
                    shard["n_right_days"]    = combined["n"]
                shard["days_right"] = pr
            (TICKER_DATA_DIR / f"{ticker}.json").write_text(json.dumps(shard))
    index = {}
    for t, e in stocks.items():
        if is_unknown_ticker(t):
            continue  # unidentified companies must not be searchable — see is_unknown_ticker
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
        if is_unknown_ticker(ticker):
            continue  # keep unidentified companies out of Recent Picks too
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
        SELECT m.ticker, m.date, m.sentiment, m.segment, m.note, m.closing_price
        FROM mentions m
        JOIN episodes e ON e.id = m.episode_id
        WHERE e.is_fundamentals = 0
        ORDER BY m.ticker, m.date
    """)
    rows = cur.fetchall()
    cur.execute("SELECT ticker, company FROM stocks WHERE company != ''")
    db_companies = {r["ticker"]: r["company"] for r in cur.fetchall()}
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

    # Add stub entries for DB tickers not yet in JSON metadata. Take the company name
    # from the DB rather than defaulting to the ticker itself — otherwise a ticker that
    # first reaches the JSON via this path (e.g. one created by a manual correction) is
    # stuck showing its symbol as its name, and each worktree has its own copy of
    # stock_sentiments.json, so hand-fixing one doesn't fix the other.
    # Entries stubbed by an earlier run are repaired the same way: a company equal to its
    # own ticker is a leftover placeholder, never a real name, so adopt the DB's.
    for ticker in db_mentions:
        if ticker not in stocks:
            stocks[ticker] = {"company": db_companies.get(ticker, ticker),
                              "sector": "", "style": "", "mentions": []}
        elif stocks[ticker].get("company") == ticker and ticker in db_companies:
            stocks[ticker]["company"] = db_companies[ticker]

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

    # Persist synced state back to stock_sentiments.json so it stays consistent.
    # indent=2 matches the other writers of this file (normal pipeline path) — keeps
    # the file stably pretty-printed instead of flip-flopping to minified on rebuild.
    SENTIMENTS_FILE.write_text(json.dumps(db_json, indent=2))

    _write_ticker_shards(stocks)

    # Delete shard files for tickers no longer in stocks (removed from DB or filtered out).
    # `reserved` must list every non-shard file in docs/data/ or it gets pruned here.
    reserved = {"index.json", "recent.json", "analytics.json", "backtest_by_ticker.json"}
    # Placeholder tickers are deliberately not written as shards, so they must not count
    # as active either — otherwise their stale shards survive every prune.
    active = {t for t in stocks if not is_unknown_ticker(t)}
    removed = 0
    for p in TICKER_DATA_DIR.glob("*.json"):
        if p.name in reserved or p.name.endswith("_prices.json"):
            continue
        if p.stem not in active:
            p.unlink()
            removed += 1
    if removed:
        print(f"Removed {removed} stale shard(s).")

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

_SENTIMENT_DISPLAY_LABELS = {
    "wait_hold_neutral": "WAIT HOLD",
}


def _sentiment_badge(sentiment: str) -> str:
    color = SENTIMENT_COLORS.get(sentiment, "#8b949e")
    label = _SENTIMENT_DISPLAY_LABELS.get(sentiment, sentiment.replace("_", " ").upper())
    return (
        f'<span style="background:{color};color:#fff;padding:3px 8px;'
        f'border-radius:4px;font-size:12px;font-weight:bold">{label}</span>'
    )


def _fmt_seconds(s: int) -> str:
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# Haiku sometimes emits variant segment values instead of the 6 canonical ones
# documented in the prompt. Fold them to canonical before matching against a
# section's display name (mirrors the CASE mapping in db.py's analytics queries).
_SEGMENT_ALIASES = {
    "investing_club_qa":     "caller_qa",
    "mag_seven_analysis":    "in_depth_analysis",
    "mag7_earnings":         "in_depth_analysis",
    "mag7_analysis":         "in_depth_analysis",
    "software_opportunities": "in_depth_analysis",
}

# The 6 segment values the prompt documents; anything else is a one-off custom
# segment Haiku invented for an unusual section (e.g. "ipo_market_analysis" for
# an "IPO Market Analysis" section) that isn't in _SEGMENT_ALIASES.
_CANONICAL_SEGMENTS = {
    "opening_commentary", "caller_qa", "interview",
    "in_depth_analysis", "lightning_round", "closing_commentary",
}


def _norm_segment(seg: str) -> str:
    return _SEGMENT_ALIASES.get(seg, seg)


def _section_segments(section_name: str) -> set[str]:
    """Map a section display name to the stock segment values it corresponds to."""
    name = section_name.lower()
    if "lightning" in name:
        return {"lightning_round"}
    if "opening" in name:
        # Caller Q&A is folded into Opening Commentary's bullets rather than
        # getting its own section (see prompt rules), so its ticker mentions
        # need to surface here too or they never render anywhere.
        return {"opening_commentary", "caller_qa"}
    if "closing" in name:
        return {"closing_commentary"}
    if "caller" in name or "q&a" in name or "q & a" in name:
        return {"caller_qa"}
    if "interview" in name:
        return {"interview"}
    if ("in-depth" in name or "in depth" in name or "deep dive" in name
            or "mag 7" in name or "mag7" in name or "magnificent" in name):
        return {"in_depth_analysis"}
    return set()


CHART_CACHE_DIR = DATA_DIR / "chart_cache"

# Mirrors SEGMENT_PRIORITY / BULLISH_SET / BEARISH_SET in docs/stocks.html so the
# email chart's mention markers match the site's chart exactly.
_CHART_SEGMENT_PRIORITY = [
    "in_depth_analysis", "interview", "opening_commentary",
    "closing_commentary", "caller_qa", "lightning_round",
]
_CHART_BULLISH = {"strong_buy", "buy", "buy_on_pullback", "mild_buy"}
_CHART_BEARISH = {"sell_avoid", "caution_concern"}


def _holding_edge(ticker: str) -> dict | None:
    """Paired excess return vs both indexes for a ticker's buy calls, or None.

    Reads docs/data/backtest_by_ticker.json, which the run regenerates before the
    email is built. Only tickers with >=3 buy calls and a full 60-day window are in
    it, so None simply means "not enough calls to say anything".

    Deliberately the *paired* figure (excess_spy_median / excess_qqq_median): each
    call is compared with the index over that call's own window before the median is
    taken. See the paired-excess rule — the naive difference of medians can flip sign.
    """
    try:
        data = json.loads((TICKER_DATA_DIR / "backtest_by_ticker.json").read_text())
        e = data.get("tickers", {}).get(ticker, {}).get("hold")
        if not e:
            return None
        return {"spy": e["excess_spy_median"], "qqq": e["excess_qqq_median"],
                "n": e["n"], "window": data.get("window_days", 60)}
    except Exception:
        return None


def _generate_price_chart_png(ticker: str) -> bytes | None:
    """
    Generate a chart of Cramer's mentions for ticker: one point per episode date
    (deduped by segment priority when mentioned multiple times same day), colored/
    shaped by sentiment, connected by a line, with a dashed line extending the last
    call's price to the most recent date we have a price for — matching the
    mention-chart on docs/stocks.html (not the raw daily-close chart).
    Returns raw PNG bytes (also cached to disk at data/chart_cache/{ticker}.png).
    Returns None if fewer than 3 distinct mention dates have a price.
    """
    try:
        from db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT m.date, m.sentiment, m.segment, m.closing_price
            FROM mentions m
            WHERE m.ticker = ? AND m.closing_price IS NOT NULL AND m.closing_price > 0
            ORDER BY m.date
        """, (ticker,))
        rows = [dict(r) for r in cur.fetchall()]

        # Daily closes for the purple backdrop bars (matches the site's
        # "Show daily price history" overlay)
        cur.execute(
            "SELECT date, close FROM daily_prices WHERE ticker = ? ORDER BY date",
            (ticker,),
        )
        daily_rows = [dict(r) for r in cur.fetchall()]

        # Most recent date we have any daily price for (dashed line's right endpoint)
        cur.execute("SELECT MAX(date) AS d FROM daily_prices WHERE ticker = ?", (ticker,))
        latest_price_date_row = cur.fetchone()
        conn.close()

        if not rows:
            return None

        # Dedupe same-day mentions by segment priority (highest-priority segment wins)
        by_date: dict[str, dict] = {}
        for r in rows:
            d = r["date"]
            pri = _CHART_SEGMENT_PRIORITY.index(r["segment"]) if r["segment"] in _CHART_SEGMENT_PRIORITY else 99
            if d not in by_date or pri < by_date[d]["_pri"]:
                r["_pri"] = pri
                by_date[d] = r

        date_strs = sorted(by_date.keys())
        if len(date_strs) < 3:
            return None

        dates = [datetime.fromisoformat(d) for d in date_strs]
        prices = [by_date[d]["closing_price"] for d in date_strs]
        sentiments = [normalize_sentiment(by_date[d].get("sentiment") or "") for d in date_strs]

        fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)

        if daily_rows:
            daily_dates = [datetime.fromisoformat(r["date"]) for r in daily_rows]
            daily_closes = [r["close"] for r in daily_rows]
            # Soft filled price band (+ a faint outline) instead of heavy vertical bars —
            # reads as a modern area chart rather than a barcode. ylim (set below) clips the
            # fill's bottom to the price range so it doesn't stretch down toward $0.
            ax.fill_between(daily_dates, daily_closes, 0, color="#8250df",
                            alpha=0.10, linewidth=0, zorder=0)
            ax.plot(daily_dates, daily_closes, color="#8250df", alpha=0.45,
                    linewidth=0.8, zorder=0)

        ax.plot(dates, prices, "-", color="#0969da", linewidth=2.0, zorder=1)

        for dt, price, sent in zip(dates, prices, sentiments):
            if sent in _CHART_BULLISH:
                marker, color, size = "^", "#2da44e", 90
            elif sent in _CHART_BEARISH:
                marker, color, size = "v", "#a00000", 90
            else:
                marker, color, size = "o", "#8b949e", 55
            ax.scatter([dt], [price], marker=marker, color=color, s=size,
                       edgecolor="white", linewidth=1.2, zorder=3)

        # Dashed horizontal line: last call's price extended to most recent price date
        last_date, last_price = dates[-1], prices[-1]
        end_date = (
            datetime.fromisoformat(latest_price_date_row["d"])
            if latest_price_date_row and latest_price_date_row["d"] else datetime.now()
        )
        if end_date > last_date:
            ax.plot([last_date, end_date], [last_price, last_price],
                    linestyle="--", color="#0969da", linewidth=1.3, zorder=2)

        # Auto-range the y-axis to the data (like Chart.js does on the site) instead
        # of letting the bar chart's zero-baseline force the axis down to $0, which
        # compresses the actual price movement into a sliver at the top.
        all_vals = prices + ([r["close"] for r in daily_rows] if daily_rows else [])
        y_min, y_max = min(all_vals), max(all_vals)
        pad = (y_max - y_min) * 0.08 or y_max * 0.05
        ax.set_ylim(y_min - pad, y_max + pad)

        # % Days Right — same walk-forward methodology as the site's shard build
        # (_write_ticker_shards): for each buy/sell call, count the daily closes
        # from that call until the next call (or end of data) that landed on the
        # correct side of the call price. Requires >=5 tallied days, matching site.
        pct_right = None
        if daily_rows:
            import bisect
            daily_by_date = {r["date"]: r["close"] for r in daily_rows}
            daily_date_list = [r["date"] for r in daily_rows]
            last_daily_date = daily_date_list[-1]
            total = right = 0
            for i, d in enumerate(date_strs):
                sent = sentiments[i]
                is_buy = sent in _CHART_BULLISH
                is_sell = sent in _CHART_BEARISH
                if not is_buy and not is_sell:
                    continue
                call_price = prices[i]
                end_date = date_strs[i + 1] if i + 1 < len(date_strs) else last_daily_date
                lo = bisect.bisect_right(daily_date_list, d)
                hi = bisect.bisect_right(daily_date_list, end_date)
                for dd in daily_date_list[lo:hi]:
                    price = daily_by_date[dd]
                    total += 1
                    if is_buy and price > call_price:
                        right += 1
                    elif is_sell and price < call_price:
                        right += 1
            if total >= 5:
                pct_right = (round(right / total * 100, 1), total)

        ax.set_facecolor("#ffffff")
        fig.patch.set_facecolor("#ffffff")
        ax.grid(True, axis="y", alpha=0.14, linestyle="-", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.set_ylabel("Close ($)", fontsize=10, color="#57606a")
        ax.set_title(
            f"{ticker}  ${last_price:,.2f} at last call",
            fontsize=12, fontweight="bold", loc="left", color="#24292f",
        )
        # Headline stat: how his buy calls on this name did against BOTH indexes,
        # paired per call. Replaced "% Days Right", which answered a much weaker
        # question — a call can spend most days above its entry and still trail an
        # index fund over the same window, which is the comparison that matters.
        edge = _holding_edge(ticker)
        if edge:
            good = edge["spy"] > 0 and edge["qqq"] > 0
            bad  = edge["spy"] < 0 and edge["qqq"] < 0
            colr = "#1a7f37" if good else ("#a00000" if bad else "#9a6700")
            ax.text(
                1.0, 1.12,
                f"vs S&P {edge['spy']:+.1f}%  ·  vs Nasdaq {edge['qqq']:+.1f}%"
                f"   ({edge['n']} buy calls, {edge['window']}d)",
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=9.5, fontweight="bold", color=colr,
            )
        elif pct_right:
            # Fewer than 3 buy calls — no honest benchmark comparison exists yet.
            pct, n_days = pct_right
            pct_color = "#1a7f37" if pct >= 50 else "#a00000"
            ax.text(
                1.0, 1.12, f"% Days Right: {pct}% ({n_days}d) — too few calls to benchmark",
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=9, fontweight="bold", color=pct_color,
            )
        ax.tick_params(axis="both", labelsize=9, colors="#57606a", length=0)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#d0d7de")
        fig.autofmt_xdate(rotation=30, ha="right")

        legend_elements = [
            plt.Line2D([0], [0], marker="^", color="w", markerfacecolor="#2da44e", markersize=8, label="Bullish"),
            plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#8b949e", markersize=7, label="Neutral"),
            plt.Line2D([0], [0], marker="v", color="w", markerfacecolor="#a00000", markersize=8, label="Bearish"),
            plt.Line2D([0], [0], color="#0969da", linestyle="--", label="Price at last call"),
        ]
        if daily_rows:
            legend_elements.append(
                Patch(facecolor="#8250df", alpha=0.35, edgecolor="#8250df", label="Daily price")
            )
        ax.legend(handles=legend_elements, loc="upper left", fontsize=7, frameon=False, ncol=len(legend_elements))

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="#ffffff")
        buf.seek(0)
        png_bytes = buf.read()
        plt.close(fig)

        CHART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CHART_CACHE_DIR / f"{ticker}.png").write_bytes(png_bytes)

        return png_bytes
    except Exception as e:
        print(f"    Chart generation failed for {ticker}: {e}")
        return None


def build_email_html(summaries: list[dict],
                     highlight_tickers: set[str] | None = None,
                     embed_charts: str = "base64") -> tuple[str, list[tuple[str, bytes]]]:
    """
    summaries: list of dicts with keys:
        date_str, analysis, audio_url (or None), video_id, redirect_pages
    highlight_tickers: tickers to highlight in yellow (defaults to USER_HOLDINGS)
    redirect_pages: dict mapping start_seconds (int) → GitHub Pages URL
    embed_charts: "base64" for self-contained <img> (browser-viewable archive/preview
        files) or "cid" for cid: references (paired with MIMEImage attachments for
        actual SMTP-sent email — many clients strip/block inline base64 images).

    Returns (html, chart_attachments) where chart_attachments is a list of
    (content_id, png_bytes) tuples — empty unless embed_charts == "cid".
    """
    hl = highlight_tickers if highlight_tickers is not None else USER_HOLDINGS
    chart_attachments: list[tuple[str, bytes]] = []
    parts = ["""
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: -apple-system, Arial, sans-serif; color: #24292f;
         max-width: 700px; margin: 0 auto; padding: 20px;
         font-size: 16px; line-height: 1.5; }
  h2   { color: #0969da; border-bottom: 2px solid #0969da; padding-bottom: 6px; }
  h3   { margin: 24px 0 4px; border-top: 1px solid #d0d7de; padding-top: 12px; }
  h3 a { color: #24292f; text-decoration: none; }
  h3 a:hover { text-decoration: underline; }
  .market-headline { font-size: 15px; font-weight: 600; color: #0969da;
                     margin: 4px 0 6px; }
  .sec-headline { font-size: 14px; font-weight: 600; color: #24292f;
                  margin: 3px 0 4px; font-style: italic; }
  .sub   { margin-left: 20px; }
  .summary { color: #57606a; margin: 4px 0 6px; font-size: 15px; }
  ul.summary { color: #57606a; margin: 4px 0 6px 18px; font-size: 15px; }
  ul.summary li { margin-bottom: 3px; }
  .sec-tickers { margin: 0 0 14px; font-size: 12px; }
  .tlink { font-family: monospace; font-weight: bold; font-size: 13px;
           color: #0969da; text-decoration: none; background: #ddf4ff;
           padding: 5px 9px; border-radius: 4px; margin: 0 5px 5px 0;
           white-space: nowrap; display: inline-block; }
  .tlink:hover { text-decoration: underline; }
  table  { border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 13px; }
  th     { background: #f6f8fa; text-align: left; padding: 6px 10px;
           border-bottom: 2px solid #d0d7de; }
  td     { padding: 5px 10px; border-bottom: 1px solid #d0d7de;
           vertical-align: top; }
  .ticker  { font-weight: bold; font-family: monospace; }
  .holding { background: #fff8c5; }
  .note    { color: #57606a; font-size: 13px; }
  .chart-row td { padding: 8px 10px 14px; border-bottom: 1px solid #d0d7de; text-align: center; }
  .chart-row img { max-width: 100%; height: auto; }
  .footer { margin-top: 24px; color: #8b949e; font-size: 12px; border-top: 1px solid #d0d7de; padding-top: 8px; }
  .ep-subtitle { font-size: 13px; color: #8b949e; margin: -4px 0 10px; font-weight: 400; }
  .fundamentals-banner { background: #fff8c5; border: 1px solid #d4a017; border-radius: 6px;
    padding: 10px 14px; margin: 8px 0 14px; font-size: 13px; color: #633c01; }
  @media (max-width: 600px) {
    body   { padding: 12px; }
    h2     { font-size: 20px; }
    .summary, ul.summary { font-size: 16px; line-height: 1.6; }
    ul.summary li { margin-bottom: 6px; }
    .sec-headline { font-size: 15px; }
    .sub   { margin-left: 0; }
    table  { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; font-size: 12px; }
    th, td { padding: 4px 6px; }
    .tlink { font-size: 13px; padding: 5px 9px; }
  }
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
        parts.append('<p class="ep-subtitle">Episode Summary</p>')
        if analysis.get("episode_type") == "fundamentals":
            parts.append(
                '<div class="fundamentals-banner">'
                '<strong>📚 Investing Fundamentals Episode</strong> &mdash; '
                'This episode does not contain day-of stock commentary. '
                'Content covers timeless investing principles and may be re-aired at any time.'
                '</div>'
            )
        if analysis.get("market_headline"):
            parts.append(f'<p class="market-headline">{analysis["market_headline"]}</p>')
        market_bullets = analysis.get("market_bullets")
        if market_bullets and isinstance(market_bullets, list):
            items = "".join(f"<li>{b}</li>" for b in market_bullets)
            parts.append(f'<ul class="summary">{items}</ul>')
        elif analysis.get("market_summary"):
            parts.append(f'<p class="summary">{analysis["market_summary"]}</p>')

        stocks = analysis.get("stocks", [])

        # "Interview" sections reliably cover exactly one company, named in
        # the title (e.g. "Interview: Yum Brands (YUM)") — when an episode has
        # multiple interviews, only name-matching prevents every interview's
        # pills from showing under every other interview. "In-Depth" sections
        # don't follow this pattern: they can be single-stock deep dives OR
        # thematic multi-stock roundups (e.g. "In-Depth: Space Sector
        # Alternatives" covering 5 different tickers never named in the
        # title) — so name-matching for in-depth sections silently filters
        # everything out. Only disambiguate interviews.
        def _ticker_links(section_name: str, section_text: str = "") -> str:
            segs = _section_segments(section_name)
            name_lower = section_name.lower()
            if not segs:
                # No keyword match — this is a one-off custom section (e.g.
                # "IPO Market Analysis"). Haiku's segment value for these is
                # usually a near-literal slug of the section name (e.g.
                # "ipo_market_analysis"), so match by word-overlap against the
                # section's own title rather than lumping into a shared bucket
                # like in_depth_analysis (which would wrongly merge multiple
                # distinct custom sections in the same episode).
                custom_segs = set()
                for s in stocks:
                    raw_seg = s.get("segment", "")
                    norm_seg = _norm_segment(raw_seg)
                    if not raw_seg or norm_seg in _CANONICAL_SEGMENTS:
                        continue
                    words = [w for w in raw_seg.split("_") if w and w != "analysis"]
                    if words and all(w in name_lower for w in words):
                        custom_segs.add(raw_seg)
                if not custom_segs:
                    return ""
                segs = custom_segs
            needs_name_match = "interview" in segs
            matched = []
            for s in stocks:
                if _norm_segment(s.get("segment", "")) not in segs:
                    continue
                ticker = s.get("ticker", "")
                if not ticker:
                    continue
                if needs_name_match:
                    company = s.get("company", "")
                    if ticker.lower() not in name_lower and (not company or company.lower() not in name_lower):
                        continue
                matched.append(s)
            # Closing Commentary usually recaps names already discussed earlier
            # in the episode (under their original segment, e.g. an interview)
            # rather than introducing new closing_commentary-tagged mentions —
            # so a pure segment match often finds nothing even when the recap
            # text clearly names a ticker. Fall back to scanning the section's
            # own text for "(TICKER)" or the company name for any stock not
            # already matched.
            if "closing_commentary" in segs and section_text:
                matched_tickers = {s["ticker"] for s in matched}
                for s in stocks:
                    ticker = s.get("ticker", "")
                    if not ticker or ticker in matched_tickers:
                        continue
                    company = s.get("company", "")
                    if f"({ticker})" in section_text or (company and company.lower() in section_text.lower()):
                        matched.append(s)
                        matched_tickers.add(ticker)
            if not matched:
                return ""
            matched.sort(key=lambda s: s.get("ticker", ""))
            links = "".join(
                f'<a class="tlink" href="#ticker-{s["ticker"]}" '
                f'style="border:1.5px solid {SENTIMENT_COLORS.get(normalize_sentiment(s.get("sentiment","")), "#8b949e")};'
                f'color:{SENTIMENT_COLORS.get(normalize_sentiment(s.get("sentiment","")), "#8b949e")};background:#fff;">'
                f'{_ticker_display(s["ticker"], ep_date)}{"*" if s["ticker"] in hl else ""}</a>'
                for s in matched
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
            bullets = section.get("bullets")
            if bullets and isinstance(bullets, list):
                body_html = '<ul class="summary">' + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
                section_text = headline + " " + " ".join(bullets)
            else:
                body_html = f'<p class="summary">{section.get("summary", "")}</p>'
                section_text = headline + " " + section.get("summary", "")
            ticker_html = _ticker_links(name, section_text)
            parts.append(
                f'{tag_open}'
                f'<h3><a href="{href}">{icon} {show_name} [{ts_label}]</a></h3>'
                + (f'<p class="sec-headline">{headline}</p>' if headline else "")
                + ticker_html
                + body_html
                + tag_close
            )

        for section in analysis.get("sections", []):
            _section_parts(section)

        # Holdings table. Deliberately NOT every stock mentioned: the full list ran to
        # ~30 rows and buried the handful that matter, and each section above already
        # covers what he said about everything else. The site is there for depth.
        held = [s for s in stocks if (s.get("ticker") or "").upper() in hl]
        if stocks and not held:
            n_other = len(stocks)
            parts.append(
                '<h3>Your Holdings</h3>'
                f'<p style="color:#57606a;font-size:14px;margin:4px 0 16px">'
                f'None of your holdings were mentioned tonight '
                f'({n_other} other stock{"s" if n_other != 1 else ""} discussed — see the sections above).</p>'
            )
        if held:
            stocks = held
            parts.append('<h3>Your Holdings Mentioned Tonight</h3>')
            parts.append(
                '<table>'
                '<colgroup>'
                '<col style="width:8%"><col style="width:14%"><col style="width:13%">'
                '<col style="width:12%"><col style="width:53%">'
                '</colgroup>'
                '<tr>'
                '<th>Ticker</th><th>Company</th><th>Sentiment</th>'
                '<th>Segment</th><th>Note</th>'
                '</tr>'
            )
            for s in sorted(stocks, key=lambda s: s.get("ticker", "")):
                seg = s.get("segment", "").replace("_", " ").title()
                pt = ""
                if "price_target" in s:
                    pt = f' (target ${s["price_target"]})'
                elif "price_level" in s:
                    pt = f' (at ${s["price_level"]})'
                ticker = s.get("ticker", "")
                is_holding = ticker in hl
                # Every row in this table is a holding now, so the yellow highlight and
                # the "*" marker no longer distinguish anything — drop both.
                row_class = ""
                note = s.get("note", "")
                ticker_note = s.get("ticker_note", "")
                note_html = note
                if ticker_note:
                    note_html += f'<br><em style="color:#f0a030;font-size:11px">{ticker_note}</em>'
                parts.append(
                    f'<tr id="ticker-{ticker}"{row_class}>'
                    f'<td class="ticker">{_ticker_display(ticker, ep_date)}</td>'
                    f'<td>{s.get("company","")}</td>'
                    f'<td>{_sentiment_badge(s.get("sentiment","neutral"))}{pt}</td>'
                    f'<td>{seg}</td>'
                    f'<td class="note">{note_html}</td>'
                    f'</tr>'
                )
                # Embed chart for holdings if available
                if is_holding:
                    png_bytes = _generate_price_chart_png(ticker)
                    if png_bytes:
                        if embed_charts == "cid":
                            cid = f"chart-{ticker}"
                            chart_attachments.append((cid, png_bytes))
                            img_src = f"cid:{cid}"
                        else:
                            img_src = f"data:image/png;base64,{base64.b64encode(png_bytes).decode('utf-8')}"
                        # width="600" is an HTML *attribute*, not CSS. Gmail's reading pane is
                        # ~600px wide and is unreliable about CSS max-width on images, so a
                        # 1035px chart overflows it and later charts land outside the visible
                        # area — which is exactly why only the first one showed in the pane
                        # while all of them showed in "open in new window". display:block
                        # avoids the inline-image baseline gap.
                        parts.append(
                            f'<tr class="chart-row"><td colspan="5">'
                            f'<img src="{img_src}" alt="{ticker} price chart" width="600" '
                            f'style="display:block;width:100%;max-width:600px;height:auto;">'
                            f'</td></tr>'
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
        f'stock_sentiments.json updated &middot; * = your holding</div>'
    )
    parts.append("</body></html>")
    return "\n".join(parts), chart_attachments


# ── 7. Email delivery ──────────────────────────────────────────────────────────

def send_email_smtp(html: str, subject: str, recipient: str | None = None,
                    chart_attachments: list[tuple[str, bytes]] | None = None) -> None:
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD environment variable not set")

    sender = os.environ.get("GMAIL_FROM", GMAIL_FROM)
    recipient = recipient or os.environ.get("GMAIL_TO", GMAIL_TO)

    if chart_attachments:
        # "related" wraps the html part + its inline cid: images together
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html"))
        for cid, png_bytes in chart_attachments:
            img = MIMEImage(png_bytes, "png")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
            msg.attach(img)
    else:
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
               recipient: str | None = None,
               chart_attachments: list[tuple[str, bytes]] | None = None) -> None:
    if mode == "smtp":
        send_email_smtp(html, subject, recipient=recipient, chart_attachments=chart_attachments)
    elif mode == "mcp":
        send_email_mcp(html, subject)
    else:
        raise ValueError(f"Unknown email mode: {mode!r}")


# ── 9. Git commit + push ──────────────────────────────────────────────────────

PAGES_BRANCH = "main"   # GitHub Pages publishes from main


def commit_and_push(dates: list[str]) -> None:
    """Commit generated docs/ + data/ and push them to origin/main.

    GitHub Pages serves from main, so nightly artifacts must be committed *while checked out
    on main*. The pipeline is the source of truth for these files; this function does not
    reconcile them with anything — it stages what's dirty under docs/ + data/ and pushes.

    That "stage everything dirty" behavior is why the cron must run on a clean main and never
    on a feature branch: it would sweep any in-progress edits (e.g. an unsaved stocks.html)
    straight to the live site. Isolation is enforced structurally by running the cron from a
    dedicated main-pinned git worktree (~/Documents/DS/yt-words-cron), so this function can
    stay a plain add/commit/push and simply *refuse* to run anywhere but main.

    Earlier versions tried to publish from a feature branch by switching branches at runtime
    (first via `git stash pop`, then a filesystem snapshot). Both were fragile — the stash
    pop is a 3-way merge that conflicted on every run and stranded the repo (this broke the
    2026-07-14 run). The worktree removes the need for any of that: if we're not on main,
    that's an operator mistake, so we bail loudly and leave the files on disk rather than
    trying to move them.
    """
    label = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
    msg = f"Mad Money {label}: redirect pages + sentiment update"
    paths = ["docs/", "data/"]

    def git(*args, check=True):
        return subprocess.run(["git", *args], cwd=ROOT, check=check,
                              capture_output=True, text=True)

    def has_staged() -> bool:
        return git("diff", "--cached", "--quiet", check=False).returncode != 0

    try:
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

        if branch != PAGES_BRANCH:
            print(f"  Refusing to publish: on '{branch}', not '{PAGES_BRANCH}'.")
            print(f"  GitHub Pages serves from '{PAGES_BRANCH}' — run the pipeline from the")
            print(f"  main-pinned worktree (~/Documents/DS/yt-words-cron), not a feature branch.")
            print("  Generated files are still on disk — links will use YouTube fallback until next push.")
            return

        git("add", *paths)
        if not has_staged():
            print("  No docs/ or data/ changes to commit.")
            return
        git("commit", "-m", msg)
        git("push", "origin", PAGES_BRANCH)
        print(f"  Pushed to origin/{PAGES_BRANCH} — redirect pages are live")
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip().splitlines()[-1:] or [str(e)]
        # Loud on purpose: this failed silently for days (BUG-007) while the nightly email
        # kept arriving, so nothing signalled that the live site had stopped updating.
        print("\n" + "!" * 72)
        print(f"!! GIT PUSH FAILED: {err[0]}")
        print("!! The live site is NOT updating. Commits are stacking up locally.")
        try:
            behind = git("log", f"origin/{PAGES_BRANCH}..{PAGES_BRANCH}", "--oneline",
                         check=False).stdout.strip().splitlines()
            if behind:
                print(f"!! {len(behind)} unpushed commit(s); oldest: {behind[-1]}")
        except Exception:
            pass
        print(f"!! Recover with:  git -C {ROOT} push origin {PAGES_BRANCH}")
        print("!" * 72 + "\n")
        print("  Generated files are still on disk — links will use YouTube fallback until next push")


# ── Ticker/company validation ─────────────────────────────────────────────────
#
# Haiku picks the ticker from what it hears, and the auto-captions mangle names:
# "Newor" -> NWR instead of NUE, "Sanders" -> SNPS instead of SNDK, "Wirehouser"
# -> WHW instead of WY. A wrong ticker is worse than a missing one, because the
# call silently inherits a real, unrelated company's price history.
#
# Yahoo is the arbiter: it knows what a symbol actually is. We only *flag* —
# never auto-correct — because the model's company name can itself be the wrong
# half of the pair, and because Yahoo has no entry for private companies or for
# the placeholder tickers.

TICKER_NAME_CACHE = ROOT / "data" / "ticker_names.json"
NAME_MISMATCH_DOC = ROOT / "notes" / "ticker-name-mismatches.md"

_NAME_NOISE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|companies|ltd|limited|llc|lp|plc|"
    r"holdings?|group|the|sa|nv|ag|se|ab|as|oyj|technologies|technology|international|"
    r"and|class|common|stock|shares|depositary|receipts?)\b"
)


def _name_token_list(s: str | None) -> list[str]:
    """Significant words of a company name, in the order they appear."""
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    return [t for t in _NAME_NOISE.sub(" ", s).split() if len(t) > 1]


def _name_tokens(s: str | None) -> set[str]:
    return set(_name_token_list(s))


def names_agree(a: str | None, b: str | None) -> bool:
    """True if two company names plausibly describe the same company.

    Deliberately token-based rather than a similarity ratio. "Blackstone" and
    "BlackRock" — two real, different companies we actually confused — score 0.74
    on difflib, which sails past any threshold loose enough to accept
    "Lam Research" vs "Lam Research Corporation". Comparing token sets separates
    them cleanly: shared tokens mean the same company, a bare string resemblance
    does not.
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return True          # nothing to compare — don't cry wolf
    if ta == tb:
        return True
    # A subset counts only when the smaller name carries at least two significant
    # words. One shared word is not identity: "Marriott Vacations Worldwide" and
    # "Marriott International" are different companies, as are Liberty/Morgan/First
    # anything.
    if (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= 2:
        return True
    if len(ta & tb) / len(ta | tb) >= 0.5:
        return True
    # Fall back to the whitespace-free forms, so a name that merely spells or splits
    # differently ("JPMorgan Chase" / "JP Morgan Chase", "Symbiotic" / "Symbotic")
    # isn't reported as a different company. 0.85 is deliberately high: "blackstone"
    # vs "blackrock" scores 0.74 and must stay flagged.
    import difflib
    # Join in the order the words appear, not set order — set iteration order is not
    # stable across runs, and sorting would scramble "United Health" away from
    # "UnitedHealth".
    ca = "".join(_name_token_list(a))
    cb = "".join(_name_token_list(b))
    return difflib.SequenceMatcher(None, ca, cb).ratio() >= 0.85


def _yahoo_ticker_name(ticker: str, cache: dict) -> str | None:
    """Yahoo's name for a symbol, memoised to data/ticker_names.json."""
    if ticker in cache:
        return cache[ticker]
    name = None
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
        )
        if r.ok:
            meta = (r.json().get("chart", {}).get("result") or [{}])[0].get("meta", {})
            name = meta.get("longName") or meta.get("shortName")
    except Exception:
        return None          # network trouble must never break a run
    cache[ticker] = name
    return name


def suggest_ticker(company: str) -> str | None:
    """Ask Yahoo which symbol a company name belongs to."""
    try:
        r = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": company, "quotesCount": 5, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
        )
        if not r.ok:
            return None
        for q in r.json().get("quotes", []):
            # US listings only — the same company lists in a dozen places
            if q.get("quoteType") == "EQUITY" and q.get("exchange") in {
                "NYQ", "NMS", "NGM", "NCM", "ASE", "PCX", "BTS", "NYS"
            }:
                return q.get("symbol")
    except Exception:
        pass
    return None


def validate_analysis_tickers(analysis: dict, suggest: bool = True) -> list[dict]:
    """Check every (ticker, company) the model produced against Yahoo.

    Returns one dict per suspicious pair. Never raises and never edits the
    analysis — a bad network day should cost us a warning, not an episode.
    """
    cache = {}
    if TICKER_NAME_CACHE.exists():
        try:
            cache = json.loads(TICKER_NAME_CACHE.read_text())
        except Exception:
            cache = {}

    flags = []
    for stock in analysis.get("stocks", []):
        ticker = (stock.get("ticker") or "").upper()
        company = stock.get("company") or ""
        if not ticker or not company or is_unknown_ticker(ticker):
            continue
        if ticker in PRIVATE_COMPANIES:
            continue                     # deliberately not on Yahoo
        actual = _yahoo_ticker_name(ticker, cache)
        if actual is None:
            flags.append({"ticker": ticker, "company": company,
                          "actual": None, "suggested": suggest_ticker(company) if suggest else None,
                          "reason": "ticker not found on Yahoo"})
        elif not names_agree(company, actual):
            flags.append({"ticker": ticker, "company": company,
                          "actual": actual,
                          "suggested": suggest_ticker(company) if suggest else None,
                          "reason": "ticker belongs to a different company"})

    try:
        TICKER_NAME_CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
    except Exception:
        pass
    return flags


def report_ticker_flags(flags: list[dict], date_str: str) -> None:
    """Print flagged tickers so they're visible in the nightly run's output."""
    if not flags:
        print("  Ticker check: all tickers match their company names")
        return
    print(f"\n  {'!' * 60}")
    print(f"  !! {len(flags)} suspicious ticker(s) in the {date_str} analysis:")
    for f in flags:
        actual = f["actual"] or "— no such symbol —"
        line = f"  !!   {f['ticker']:<8} stored as {f['company'][:32]!r}, but {f['ticker']} is {actual!r}"
        print(line)
        if f["suggested"] and f["suggested"] != f["ticker"]:
            print(f"  !!   {'':<8} Yahoo says {f['company'][:32]!r} is {f['suggested']}")
    print(f"  !! Review with: python3 code/pipeline.py --check-ticker-names")
    print(f"  {'!' * 60}\n")


def build_name_mismatch_report(write: bool = True) -> list[dict]:
    """Regenerate notes/ticker-name-mismatches.md from the whole DB.

    Same shape as the unknown-ticker queue: always derived from current data, so a
    row that gets resolved simply stops appearing. Manual — the nightly run checks
    only the episode it just analyzed.
    """
    from db import get_connection

    cache = {}
    if TICKER_NAME_CACHE.exists():
        try:
            cache = json.loads(TICKER_NAME_CACHE.read_text())
        except Exception:
            cache = {}

    # Read names from the DB, not stock_sentiments.json. The JSON is a *tracked,
    # main-owned* file, so each worktree carries its own copy and a feature branch's
    # is stale the moment main rebuilds — running this there reported 100 rows against
    # main's 78, purely from a week-old company list. The DB is a single shared file
    # (symlinked into the cron worktree), so sourcing names from it makes this command
    # give the same answer wherever it runs.
    conn = get_connection()
    stocks = {r["ticker"]: {"company": r["company"]}
              for r in conn.execute("SELECT ticker, company FROM stocks WHERE company != ''")}
    counts = {r["ticker"]: (r["n"], r["lo"], r["hi"]) for r in conn.execute(
        "SELECT ticker, COUNT(*) n, MIN(date) lo, MAX(date) hi FROM mentions GROUP BY ticker")}
    conn.close()
    # Only tickers that still have mentions are worth reviewing.
    stocks = {t: v for t, v in stocks.items() if t in counts}

    rows, checked = [], 0
    for ticker, entry in sorted(stocks.items()):
        company = entry.get("company") or ""
        if not company or is_unknown_ticker(ticker) or ticker in PRIVATE_COMPANIES:
            continue
        # A company stored as its own symbol is unnamed, not mis-named.
        if company.strip().upper() == ticker:
            continue
        actual = _yahoo_ticker_name(ticker, cache)
        # Yahoo sometimes answers with a bare number instead of a name; that is not
        # evidence of anything.
        if actual and actual.strip().isdigit():
            actual = None
        checked += 1
        if actual and not names_agree(company, actual):
            n, lo, hi = counts.get(ticker, (0, "", ""))
            rows.append({"ticker": ticker, "company": company, "actual": actual,
                         "n": n, "lo": lo, "hi": hi})
    try:
        TICKER_NAME_CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
    except Exception:
        pass

    rows.sort(key=lambda r: (-r["n"], r["ticker"]))
    if write:
        out = [
            "# Ticker / Company Name Mismatches — Review Queue\n",
            f"**{len(rows)} ticker(s)** hold a company that Yahoo Finance says belongs to a",
            "*different* company. Each is a likely mis-ticker: the call is probably about the",
            "company in the last column, filed under the wrong symbol — where it silently",
            "inherits that symbol's real price history.\n",
            "> **Generated file — do not edit by hand.**",
            ">",
            "> ```bash",
            "> python3 code/pipeline.py --check-ticker-names",
            "> ```",
            ">",
            "> **Manual — the nightly pipeline does not run this.** The nightly run checks only",
            "> the episode it just analyzed and prints any flags in its output; this rebuilds the",
            "> full picture across every ticker. Re-run it to pick up new episodes and to drop",
            "> rows you have resolved.\n",
            "Confirm against the transcript first, then retarget the mention (or delete it if it",
            "duplicates a correct row):\n",
            "```bash",
            "sqlite3 data/mad_money.db \\",
            "  \"UPDATE mentions SET ticker='CORRECT', closing_price=NULL WHERE ticker='WRONG';\"",
            "python3 code/pipeline.py --rebuild-shards",
            "python3 code/pipeline.py --backfill-prices --tickers CORRECT",
            "```\n",
            "| Ticker | Mentions | Dates | Yahoo says the symbol is | We stored it as |",
            "|--------|---------:|-------|--------------------------|-----------------|",
        ]
        for r in rows:
            span = r["lo"] if r["lo"] == r["hi"] else f"{r['lo']} … {r['hi']}"
            out.append(f"| `{r['ticker']}` | {r['n']} | {span} | {r['actual']} | **{r['company']}** |")
        out.append("")
        out.append(f"_Checked {checked} tickers with a stored company name. Tickers Yahoo does not")
        out.append("recognise at all (hallucinated, private, OTC) are not listed here — see the")
        out.append("'Hallucinated tickers' note in CLAUDE.md._\n")
        out.append("_This list intentionally over-flags. A shared single word is not treated as a")
        out.append("match, so `Chipotle` vs `Chipotle Mexican Grill` appears even though it is fine —")
        out.append("the same rule is what keeps `Marriott Vacations Worldwide` from matching")
        out.append("`Marriott International`. Missing a real mis-ticker costs a corrupted price")
        out.append("history; a false positive costs one glance._")
        NAME_MISMATCH_DOC.write_text("\n".join(out) + "\n")
        print(f"  {len(rows)} name mismatch(es) out of {checked} checked → {NAME_MISMATCH_DOC}")
    return rows


# ── Unknown-ticker report ─────────────────────────────────────────────────────

UNKNOWN_TICKER = "????"
UNKNOWN_TICKERS_DOC = ROOT / "notes" / "unknown-tickers.md"


def is_unknown_ticker(ticker: str | None) -> bool:
    """True for Haiku's placeholder when it heard a company but not its symbol.

    Matches any all-'?' ticker: both '????' and the '???' variant occur in the DB.
    These must never reach the site — every unidentified company collapses into one
    entry that renders under whichever company name happened to be stored last (the
    '????' entry was showing 22 unrelated companies as "OpenAI").
    """
    t = (ticker or "").strip()
    return bool(t) and set(t) == {"?"}


def _section_index(date_str: str) -> dict[str, list[tuple[str, int]]]:
    """Map segment -> [(section title, start_seconds)] for one episode date.

    start_seconds lives nowhere in the DB, so recover it from generated artifacts. The
    archived summary HTML is the better source: it carries every section as
    `<h3><a href="...?t=SECS">▶ Name [M:SS]</a></h3>` and exists for every episode back to
    January. Redirect pages are the fallback — they only start in June.
    """
    out: dict[str, list[tuple[str, int]]] = {}

    def _add(title: str, secs: int) -> None:
        for seg in _section_segments(title):
            out.setdefault(seg, []).append((title, secs))

    summary = SUMMARIES_DIR / f"{date_str}_summary.html"
    if summary.exists():
        html = summary.read_text(errors="replace")
        for href, label in re.findall(r"<h3><a href=\"([^\"]+)\">(.*?)</a></h3>", html, re.S):
            m = re.search(r"[?&]t=(\d+)", href)
            if not m:
                continue
            # "▶ In-Depth: Costco (COST) [29:31]" -> "In-Depth: Costco (COST)"
            title = re.sub(r"\s*\[[\d:]+\]\s*$", "", label.replace("▶", "")).strip()
            _add(re.sub(r"\s+", " ", title), int(m.group(1)))
        if out:
            return out

    d = DOCS_DIR / "redirect" / date_str
    if not d.is_dir():
        return out

    for page in sorted(d.glob("*.html")):
        page_html = page.read_text(errors="replace")
        title_m = re.search(r"<h1>(.*?)</h1>", page_html, re.S)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else page.stem

        # Two link shapes: overcast.fm/+ID/M:SS (or H:MM:SS) and overcast://...&t=SECONDS
        secs = None
        if (m := re.search(r"[?&]t=(\d+)", page_html)):
            secs = int(m.group(1))
        elif (m := re.search(r"overcast\.fm/\+[\w-]+/([\d:]+)", page_html)):
            secs = 0
            for p in (int(x) for x in m.group(1).split(":")):
                secs = secs * 60 + p
        if secs is not None:
            _add(title, secs)

    return out


def build_unknown_ticker_report(write: bool = True) -> str:
    """Regenerate the manual-review list of mentions stored under a placeholder ticker.

    Derived from the DB every time rather than hand-maintained. The previous hand-written
    table in notes/bugs.md silently rotted: reanalysing an episode calls
    _clear_mentions_for_date(), which rewrites every mention for that date, so rows in a
    transcribed list stop corresponding to anything. By 2026-07-21 only 6 of its 18 rows
    still existed while 16 undocumented ones had accumulated.

    Deliberately NOT wired into the nightly run: commit_and_push() only stages docs/ and
    data/, so a nightly-written notes/ file would sit dirty on main forever. Automating it
    would mean adding this path to both commit_and_push()'s staged paths and the
    .githooks/pre-commit blocked list. Run it by hand when working the queue.
    """
    from db import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT m.ticker, m.date, m.segment, m.sentiment, m.note, e.video_id
        FROM mentions m
        JOIN episodes e ON e.id = m.episode_id
        WHERE m.ticker GLOB '*[?]*'
        ORDER BY m.date, m.segment
        """
    ).fetchall()
    rows = [r for r in rows if is_unknown_ticker(r["ticker"])]

    lines = [
        "# Unknown Tickers — Manual Review Queue",
        "",
        f"**{len(rows)} mention(s)** are stored under a placeholder ticker "
        f"(`????` / `???`) — Haiku heard a company but could not identify its symbol. "
        "These are excluded from the website until they are resolved.",
        "",
        "> **Generated file — do not edit by hand.**",
        ">",
        "> ```bash",
        "> python3 code/pipeline.py --list-unknown-tickers",
        "> ```",
        ">",
        "> This is **manual — the nightly pipeline does not run it**, so this file does not",
        "> update itself as new episodes land. Re-run the command to pick up new placeholders",
        "> (and to drop rows you have already resolved).",
        "",
        "Each row needs someone to open the episode at the timestamp and identify the",
        "company. Once you know it:",
        "",
        "```bash",
        "sqlite3 data/mad_money.db \\",
        '  "UPDATE mentions SET ticker=\'CORRECT\' '
        "WHERE ticker='????' AND date='YYYY-MM-DD' AND segment='SEGMENT';\"",
        "python3 code/pipeline.py --backfill-prices --tickers CORRECT",
        "python3 code/pipeline.py --rebuild-shards",
        "```",
        "",
        "Re-run the generator afterwards and the row disappears on its own.",
        "",
        "| Date | Placeholder | Segment | Time | Call | Cramer's description | Episode |",
        "|------|-------------|---------|------|------|----------------------|---------|",
    ]

    idx_cache: dict[str, dict] = {}
    unresolved = 0

    for r in rows:
        date_str, seg = r["date"], r["segment"] or ""
        if date_str not in idx_cache:
            idx_cache[date_str] = _section_index(date_str)
        cands = idx_cache[date_str].get(_norm_segment(seg), [])

        vid = r["video_id"] or ""
        if cands:
            # Ambiguous only when a date has two sections of the same kind (e.g. two
            # interviews); list every candidate rather than silently guessing one.
            stamps, links = [], []
            for title, secs in sorted(cands, key=lambda c: c[1]):
                stamps.append(_fmt_seconds(secs))
                label = title if len(cands) > 1 else "watch"
                links.append(f"[{label}](https://youtu.be/{vid}?t={secs})" if vid else label)
            time_cell, link_cell = " / ".join(stamps), " · ".join(links)
        else:
            unresolved += 1
            time_cell = "—"
            link_cell = f"[episode](https://youtu.be/{vid})" if vid else "—"

        note = re.sub(r"\s+", " ", (r["note"] or "")).replace("|", "\\|").strip()
        lines.append(
            f"| {date_str} | `{r['ticker']}` | {seg} | {time_cell} | "
            f"{r['sentiment'] or ''} | {note} | {link_cell} |"
        )

    if unresolved:
        lines += [
            "",
            f"_{unresolved} row(s) show no timestamp — that episode has no redirect pages "
            "on disk (they are only generated when an Overcast ID or audio URL is found), "
            "so the link points at the start of the episode._",
        ]
    lines.append("")

    md = "\n".join(lines)
    if write:
        UNKNOWN_TICKERS_DOC.parent.mkdir(parents=True, exist_ok=True)
        UNKNOWN_TICKERS_DOC.write_text(md)
        print(f"  {len(rows)} unknown-ticker mention(s) → {UNKNOWN_TICKERS_DOC}")
        if unresolved:
            print(f"  {unresolved} without a resolvable timestamp (no redirect pages on disk)")
    return md


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
    parser.add_argument("--max-episodes", type=int, default=5,
                        help="Max new episodes to process (default: 5) — each gets its own separate email")
    parser.add_argument("--email-mode", choices=["smtp", "mcp"], default="smtp",
                        help="Email delivery mode (default: smtp)")
    parser.add_argument("--backend", choices=["api", "claude-code"], default="claude-code",
                        help="Analysis backend: 'claude-code' shells out to the claude CLI and "
                             "uses your subscription (default); 'api' spends Haiku API credits")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze and format but do not send email")
    parser.add_argument("--fix-redirects", metavar="DATE",
                        help="Re-generate existing redirect pages for DATE (YYYY-MM-DD) "
                             "with correct Overcast universal links")
    parser.add_argument("--list-unknown-tickers", action="store_true",
                        help="Regenerate notes/unknown-tickers.md — the manual-review queue of "
                             "mentions stored under a placeholder ticker (???? / ???). "
                             "Run by hand; the nightly pipeline does not do this for you")
    parser.add_argument("--check-ticker-names", action="store_true",
                        help="Regenerate notes/ticker-name-mismatches.md — every ticker whose stored "
                             "company disagrees with Yahoo Finance. Run by hand; the nightly pipeline "
                             "checks only the episode it just analyzed")
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
    parser.add_argument("--mark-fundamentals", metavar="DATE[,DATE,...]",
                        help="Mark one or more episode dates as fundamentals (comma-separated YYYY-MM-DD). "
                             "Their mentions will be excluded from shards and analytics after --rebuild-shards.")
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

    if args.list_unknown_tickers:
        build_unknown_ticker_report()
        return

    if args.check_ticker_names:
        build_name_mismatch_report()
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

    if args.mark_fundamentals:
        dates = [d.strip() for d in args.mark_fundamentals.split(",")]
        from db import get_connection as _get_conn
        conn = _get_conn()
        updated = 0
        for date in dates:
            result = conn.execute(
                "UPDATE episodes SET is_fundamentals=1 WHERE date=?", (date,)
            )
            if result.rowcount:
                print(f"  Marked {date} as fundamentals.")
                updated += 1
            else:
                print(f"  WARNING: no episode found for {date} — skipping.")
        conn.commit()
        conn.close()
        if updated:
            print(f"\n{updated} episode(s) marked. Run --rebuild-shards to update the site.")
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

    analyze_fn = analyze_with_claude_code if args.backend == "claude-code" else analyze_with_haiku
    backend_label = "Claude Code session" if args.backend == "claude-code" else "Claude Haiku"

    for ep in episodes:
        video_id = ep["id"]
        print(f"\n── Processing {video_id} ──")

        try:
            print("  Fetching transcript...")
            date_str, snippets, transcript_text = fetch_transcript(
                video_id, ep.get("upload_date", "")
            )
            print(f"  Date: {date_str}  Lines: {len(snippets)}")

            if args.backend == "claude-code":
                print("  Analyzing with claude CLI (Claude Code subscription)...")
                analysis = analyze_with_claude_code(date_str, transcript_text)
            else:
                print("  Analyzing with Claude Haiku...")
                analysis = analyze_with_haiku(date_str, transcript_text)
            n_stocks = len(analysis.get("stocks", []))
            n_sections = len(analysis.get("sections", []))
            print(f"  Sections: {n_sections}  Stocks: {n_stocks}")

            # A real episode always names stocks. Sections-but-no-stocks means the model
            # returned a structurally valid but empty result (this happened on 2026-07-17,
            # which then sent a "0 stocks" email and marked itself processed, so it never
            # retried). Treat it as a failure so the next run picks it up again.
            if n_sections and not n_stocks:
                raise RuntimeError(
                    f"analysis returned {n_sections} sections but 0 stocks — "
                    "treating as a failed analysis so it retries next run"
                )

            # Catch mis-tickered calls at the moment they enter the DB, while the
            # transcript is right there to check against. Advisory only — a flagged
            # call is still stored, because the model is more often right than not
            # and silently dropping calls would be worse than a noisy warning.
            print("  Checking tickers against Yahoo...")
            report_ticker_flags(validate_analysis_tickers(analysis), date_str)

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
        except Exception as e:
            # Don't let one bad episode (e.g. captions not ready yet) block the
            # rest of the queue — skip it and leave it unprocessed for next run.
            print(f"  Skipping {video_id}: {e}")
            continue

    if not summaries:
        print("\nNo episodes processed successfully — nothing to email.")
        if not args.dry_run:
            save_processed(processed)
        return

    dates = [s["date_str"] for s in summaries]

    # Push redirect pages to GitHub Pages (needed before email so links are live)
    if not args.dry_run:
        print("\nPushing redirect pages to GitHub...")
        commit_and_push(dates)

    # Archive one HTML summary per episode date (no holdings highlighting, no charts needed)
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    for ep_summary in summaries:
        ep_html, _ = build_email_html([ep_summary], highlight_tickers=set())
        arc = SUMMARIES_DIR / f"{ep_summary['date_str']}_summary.html"
        arc.write_text(ep_html)
        print(f"  Archived summary → {arc.name}")

    # One email per episode — if we fell behind a day or two, this sends several
    # separate emails in one run rather than bundling multiple episodes together.
    for ep_summary in summaries:
        date_str = ep_summary["date_str"]
        n_stocks = len(ep_summary["analysis"].get("stocks", []))
        dt = datetime.fromisoformat(date_str)
        subject = f"Mad Money — {dt.strftime('%a %b %-d')} · {n_stocks} stocks"

        ep_tickers = {s.get("ticker", "").upper() for s in ep_summary["analysis"].get("stocks", [])}
        brother_hits = ep_tickers & BROTHER_TICKERS

        if args.dry_run:
            # base64 so the standalone preview file is viewable in a browser
            html, _ = build_email_html([ep_summary], embed_charts="base64")
            EMAIL_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            out = EMAIL_PREVIEW_DIR / f"{date_str}_email_preview.html"
            out.write_text(html)
            print(f"\nDry run — email preview saved to {out}")
            if brother_hits:
                bro_html, _ = build_email_html([ep_summary], highlight_tickers=BROTHER_TICKERS, embed_charts="base64")
                bro_out = EMAIL_PREVIEW_DIR / f"{date_str}_email_preview_brother.html"
                bro_out.write_text(bro_html)
                print(f"Brother preview saved to {bro_out} (hits: {', '.join(sorted(brother_hits))})")
        else:
            # cid: attachments render more reliably than inline base64 in most email clients
            html, chart_attachments = build_email_html([ep_summary], embed_charts="cid")
            print(f"\nSending email: {subject}")
            send_email(html, subject, mode=args.email_mode, chart_attachments=chart_attachments)
            if brother_hits:
                print(f"  Brother's tickers mentioned: {', '.join(sorted(brother_hits))} — sending copy to {BROTHER_TO}")
                bro_html, bro_charts = build_email_html([ep_summary], highlight_tickers=BROTHER_TICKERS, embed_charts="cid")
                send_email(bro_html, subject, mode=args.email_mode, recipient=BROTHER_TO, chart_attachments=bro_charts)

    # Dry runs must not mark episodes as processed — no email was actually sent,
    # so a real run later should still discover and send for these dates.
    if not args.dry_run:
        save_processed(processed)
    print("\nDone.")


if __name__ == "__main__":
    main()
