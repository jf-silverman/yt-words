"""
SQLite database module for Mad Money pipeline.
Manages schema, migrations, and provides ORM-like functions for data access.
"""

import json
import sqlite3
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None

DB_PATH = Path(__file__).parent.parent / "data" / "mad_money.db"


def get_connection():
    """Get a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            video_id TEXT UNIQUE NOT NULL,
            transcript_text TEXT,
            summary_html TEXT,
            overcast_episode_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            ticker TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            sector TEXT,
            industry TEXT,
            style TEXT,
            pe_ratio REAL,
            market_cap REAL,
            market_cap_category TEXT,
            ipo_date TEXT,
            is_private INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # Add new columns to existing DBs (idempotent — ALTER TABLE IF NOT EXISTS column
    # isn't supported in SQLite, so we catch the error if the column already exists)
    for col, typedef in [
        ("industry",           "TEXT"),
        ("pe_ratio",           "REAL"),
        ("market_cap",         "REAL"),
        ("market_cap_category","TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE stocks ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Fundamentals flag — evergreen/philosophy episodes whose stock mentions should
    # be excluded from analytics and shards (they're examples, not current calls)
    try:
        c.execute("ALTER TABLE episodes ADD COLUMN is_fundamentals INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists

    c.execute("""
        CREATE TABLE IF NOT EXISTS mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            sentiment TEXT,
            segment TEXT,
            closing_price REAL,
            note TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episodes(id),
            FOREIGN KEY (ticker) REFERENCES stocks(ticker),
            UNIQUE(episode_id, ticker, segment)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL NOT NULL,
            PRIMARY KEY (ticker, date),
            FOREIGN KEY (ticker) REFERENCES stocks(ticker)
        )
    """)

    # Indices for common queries
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_episode ON mentions(episode_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_ticker ON mentions(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_date ON mentions(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_sentiment ON mentions(sentiment)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker ON daily_prices(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date)")
    # Composite index speeds up the forward-return subqueries
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker_date
        ON daily_prices(ticker, date)
    """)

    _create_views(c)

    conn.commit()
    conn.close()


def _create_views(c):
    """Create or replace analytical views. Called from init_db()."""

    # forward_returns —————————————————————————————————————————————————————————
    # One row per mention that has a closing price.
    # Returns are NULL when price data doesn't reach that far out yet.
    # Search windows cap at 1.5× the target to avoid accidentally grabbing
    # prices from a much later period (e.g. after a delisting/relisting).
    #
    # Columns:
    #   return_7d / 30d / 90d / 180d  — % gain from mention close to ~N trading days later
    #   return_since_mention           — % gain from mention close to the latest price in DB
    #   days_since_mention             — how many calendar days ago this mention was
    #   price_latest / price_latest_date — most recent price we have for this ticker
    c.execute("DROP VIEW IF EXISTS forward_returns")
    c.execute("""
        CREATE VIEW forward_returns AS
        WITH base AS (
            SELECT
                m.id           AS mention_id,
                m.episode_id,
                m.ticker,
                m.date         AS mention_date,
                m.sentiment,
                m.segment,
                m.closing_price AS price_at_mention,
                m.note,
                s.company,
                s.sector,
                s.industry,
                s.style,
                s.pe_ratio,
                s.market_cap,
                s.market_cap_category
            FROM mentions m
            JOIN stocks s ON s.ticker = m.ticker
            JOIN episodes ep ON ep.id = m.episode_id
            WHERE ep.is_fundamentals = 0
              AND m.closing_price IS NOT NULL AND m.closing_price > 0
        )
        SELECT
            b.*,

            -- Forward prices (nearest trading day at/after target, capped to avoid stale data)
            p7.close   AS price_7d,
            p30.close  AS price_30d,
            p90.close  AS price_90d,
            p180.close AS price_180d,

            -- Latest available price for this ticker
            p_latest.close AS price_latest,
            p_latest.date  AS price_latest_date,

            -- Calendar days since the mention (always available once there's a latest price)
            CAST(JULIANDAY(p_latest.date) - JULIANDAY(b.mention_date) AS INTEGER)
                AS days_since_mention,

            -- Forward returns (NULL when we don't have price data that far out yet)
            ROUND((p7.close   - b.price_at_mention) / b.price_at_mention * 100, 2) AS return_7d,
            ROUND((p30.close  - b.price_at_mention) / b.price_at_mention * 100, 2) AS return_30d,
            ROUND((p90.close  - b.price_at_mention) / b.price_at_mention * 100, 2) AS return_90d,
            ROUND((p180.close - b.price_at_mention) / b.price_at_mention * 100, 2) AS return_180d,

            -- Return from mention price to today (always computed when latest price exists)
            ROUND((p_latest.close - b.price_at_mention) / b.price_at_mention * 100, 2)
                AS return_since_mention

        FROM base b

        -- 7-day: nearest trading day in [mention+7, mention+14]
        LEFT JOIN daily_prices p7 ON p7.ticker = b.ticker
            AND p7.date = (
                SELECT MIN(date) FROM daily_prices
                WHERE ticker = b.ticker
                  AND date >= DATE(b.mention_date, '+7 days')
                  AND date <= DATE(b.mention_date, '+14 days')
            )

        -- 30-day: nearest trading day in [mention+30, mention+45]
        LEFT JOIN daily_prices p30 ON p30.ticker = b.ticker
            AND p30.date = (
                SELECT MIN(date) FROM daily_prices
                WHERE ticker = b.ticker
                  AND date >= DATE(b.mention_date, '+30 days')
                  AND date <= DATE(b.mention_date, '+45 days')
            )

        -- 90-day: nearest trading day in [mention+90, mention+120]
        LEFT JOIN daily_prices p90 ON p90.ticker = b.ticker
            AND p90.date = (
                SELECT MIN(date) FROM daily_prices
                WHERE ticker = b.ticker
                  AND date >= DATE(b.mention_date, '+90 days')
                  AND date <= DATE(b.mention_date, '+120 days')
            )

        -- 180-day: nearest trading day in [mention+180, mention+210]
        LEFT JOIN daily_prices p180 ON p180.ticker = b.ticker
            AND p180.date = (
                SELECT MIN(date) FROM daily_prices
                WHERE ticker = b.ticker
                  AND date >= DATE(b.mention_date, '+180 days')
                  AND date <= DATE(b.mention_date, '+210 days')
            )

        -- Latest price (for return_since_mention and days_since_mention)
        LEFT JOIN daily_prices p_latest ON p_latest.ticker = b.ticker
            AND p_latest.date = (
                SELECT MAX(date) FROM daily_prices WHERE ticker = b.ticker
            )
    """)

    # sentiment_performance ———————————————————————————————————————————————————
    # Aggregates forward_returns by sentiment level.
    # n_with_Xd counts only mentions where that window's price exists.
    # Note: medians are computed in Python in build_analytics_json (SQLite has no MEDIAN).
    c.execute("DROP VIEW IF EXISTS sentiment_performance")
    c.execute("""
        CREATE VIEW sentiment_performance AS
        SELECT
            sentiment,
            COUNT(*)                                                AS n_mentions,
            COUNT(return_7d)                                        AS n_with_7d,
            COUNT(return_30d)                                       AS n_with_30d,
            COUNT(return_90d)                                       AS n_with_90d,
            COUNT(return_180d)                                      AS n_with_180d,
            ROUND(AVG(return_7d),   2)                              AS avg_return_7d,
            ROUND(AVG(return_30d),  2)                              AS avg_return_30d,
            ROUND(AVG(return_90d),  2)                              AS avg_return_90d,
            ROUND(AVG(return_180d), 2)                              AS avg_return_180d,
            ROUND(AVG(return_since_mention), 2)                     AS avg_return_since_mention,
            ROUND(100.0 * SUM(CASE WHEN return_7d   > 0 THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(return_7d),   0), 1)         AS win_rate_7d,
            ROUND(100.0 * SUM(CASE WHEN return_30d  > 0 THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(return_30d),  0), 1)         AS win_rate_30d,
            ROUND(100.0 * SUM(CASE WHEN return_90d  > 0 THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(return_90d),  0), 1)         AS win_rate_90d,
            ROUND(100.0 * SUM(CASE WHEN return_180d > 0 THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(return_180d), 0), 1)         AS win_rate_180d
        FROM forward_returns
        GROUP BY sentiment
        ORDER BY avg_return_30d DESC
    """)

    # latest_mention_performance ——————————————————————————————————————————————
    # For each ticker, only the most recent mention — with its return since then.
    # Useful for a live "how are Cramer's recent calls doing?" dashboard.
    c.execute("DROP VIEW IF EXISTS latest_mention_performance")
    c.execute("""
        CREATE VIEW latest_mention_performance AS
        WITH ranked AS (
            SELECT fr.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY fr.ticker
                       ORDER BY fr.mention_date DESC, fr.mention_id DESC
                   ) AS rn
            FROM forward_returns fr
        )
        SELECT * FROM ranked WHERE rn = 1
        ORDER BY return_since_mention DESC
    """)


def migrate_from_json(stock_sentiments_path, processed_episodes_path, daily_prices_dir):
    """
    Migrate data from JSON files to SQLite.

    Args:
        stock_sentiments_path: path to data/stock_sentiments.json
        processed_episodes_path: path to data/processed_episodes.json
        daily_prices_dir: path to data/daily_prices/
    """
    init_db()
    conn = get_connection()
    c = conn.cursor()

    now = datetime.utcnow().isoformat()
    data_dir = Path(stock_sentiments_path).parent

    # Load stock_sentiments.json
    with open(stock_sentiments_path) as f:
        data = json.load(f)
    stocks = data.get("stocks", {})

    # Build date -> video_id map from processed_episodes.json
    with open(processed_episodes_path) as f:
        processed = json.load(f)
    date_to_video_id = {ep["date"]: ep["video_id"] for ep in processed}

    # Load overcast episode IDs
    overcast_path = data_dir / "overcast_episode_ids.json"
    date_to_overcast = {}
    if overcast_path.exists():
        with open(overcast_path) as f:
            date_to_overcast = json.load(f)

    # Insert stocks
    print("  Inserting stocks...")
    for ticker, entry in stocks.items():
        ipo_date = entry.get("ipo_date")
        is_private = 1 if entry.get("is_private") else 0
        c.execute("""
            INSERT OR REPLACE INTO stocks
            (ticker, company, sector, industry, style, pe_ratio,
             market_cap, market_cap_category, ipo_date, is_private, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            entry.get("company", ""),
            entry.get("sector"),
            entry.get("industry"),
            entry.get("style"),
            entry.get("pe_ratio"),
            entry.get("market_cap"),
            entry.get("market_cap_category"),
            ipo_date,
            is_private,
            now, now,
        ))
    print(f"    {len(stocks)} stocks inserted.")

    # Insert episodes (one per unique date from processed_episodes.json)
    print("  Inserting episodes...")
    ep_count = 0
    for ep in processed:
        date = ep["date"]
        video_id = ep["video_id"]

        transcript_text = None
        transcript_path = data_dir / "transcripts" / f"{date}_transcript.txt"
        if transcript_path.exists():
            transcript_text = transcript_path.read_text(encoding="utf-8")

        summary_html = None
        summary_path = data_dir / "summaries" / f"{date}_summary.html"
        if summary_path.exists():
            summary_html = summary_path.read_text(encoding="utf-8")

        overcast_id = date_to_overcast.get(date)

        c.execute("""
            INSERT OR IGNORE INTO episodes
            (date, video_id, transcript_text, summary_html, overcast_episode_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date, video_id, transcript_text, summary_html, overcast_id, now, now))
        ep_count += 1
    print(f"    {ep_count} episodes inserted.")

    # Build date -> episode_id map for mention insertion
    c.execute("SELECT id, date FROM episodes")
    date_to_episode_id = {row["date"]: row["id"] for row in c.fetchall()}

    # Insert mentions
    print("  Inserting mentions...")
    mention_count = skipped = 0
    for ticker, entry in stocks.items():
        for mention in entry.get("mentions", []):
            date = mention.get("date", "")
            episode_id = date_to_episode_id.get(date)
            if not episode_id:
                skipped += 1
                continue
            try:
                c.execute("""
                    INSERT INTO mentions
                    (episode_id, ticker, sentiment, segment, closing_price, note, date, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    episode_id, ticker,
                    mention.get("sentiment"),
                    mention.get("segment"),
                    mention.get("closing_price"),
                    mention.get("note"),
                    date, now, now,
                ))
                mention_count += 1
            except sqlite3.IntegrityError:
                skipped += 1
    print(f"    {mention_count} mentions inserted, {skipped} skipped.")

    # Load daily prices from archive
    print("  Inserting daily prices...")
    daily_prices_path = Path(daily_prices_dir)
    price_count = 0
    if daily_prices_path.exists():
        for ticker_file in daily_prices_path.glob("*.json"):
            ticker = ticker_file.stem
            try:
                with open(ticker_file) as f:
                    prices = json.load(f)
                for price_entry in prices:
                    c.execute("""
                        INSERT OR REPLACE INTO daily_prices (ticker, date, close)
                        VALUES (?, ?, ?)
                    """, (ticker, price_entry["date"], price_entry["close"]))
                    price_count += 1
            except Exception as e:
                print(f"    Warning: could not load {ticker_file.name}: {e}")
    print(f"    {price_count} daily price rows inserted.")

    conn.commit()
    conn.close()
    print(f"\nMigration complete. Database: {DB_PATH}")


# Write helpers — called by pipeline.py during normal processing

def upsert_episode(date: str, video_id: str, transcript_text: str = None,
                   summary_html: str = None, overcast_episode_id: str = None,
                   is_fundamentals: int = 0) -> int:
    """Insert or update an episode row. Returns the episode id."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO episodes (date, video_id, transcript_text, summary_html,
                              overcast_episode_id, is_fundamentals, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            video_id           = excluded.video_id,
            transcript_text    = COALESCE(excluded.transcript_text, transcript_text),
            summary_html       = COALESCE(excluded.summary_html, summary_html),
            overcast_episode_id= COALESCE(excluded.overcast_episode_id, overcast_episode_id),
            is_fundamentals    = MAX(excluded.is_fundamentals, is_fundamentals),
            updated_at         = excluded.updated_at
    """, (date, video_id, transcript_text, summary_html, overcast_episode_id, is_fundamentals, now, now))
    c.execute("SELECT id FROM episodes WHERE date = ?", (date,))
    episode_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return episode_id


def upsert_stock(ticker: str, company: str, sector: str = None, industry: str = None,
                 style: str = None, pe_ratio: float = None, market_cap: float = None,
                 market_cap_category: str = None, ipo_date: str = None,
                 is_private: bool = False) -> None:
    """Insert or update a stock row."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO stocks (ticker, company, sector, industry, style, pe_ratio,
                            market_cap, market_cap_category, ipo_date, is_private,
                            created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            company              = excluded.company,
            sector               = COALESCE(excluded.sector,               sector),
            industry             = COALESCE(excluded.industry,             industry),
            style                = COALESCE(excluded.style,                style),
            pe_ratio             = COALESCE(excluded.pe_ratio,             pe_ratio),
            market_cap           = COALESCE(excluded.market_cap,           market_cap),
            market_cap_category  = COALESCE(excluded.market_cap_category,  market_cap_category),
            ipo_date             = COALESCE(excluded.ipo_date,             ipo_date),
            is_private           = excluded.is_private,
            updated_at           = excluded.updated_at
    """, (ticker, company, sector, industry, style, pe_ratio, market_cap,
          market_cap_category, ipo_date, 1 if is_private else 0, now, now))
    conn.commit()
    conn.close()


def upsert_mention(episode_id: int, ticker: str, sentiment: str, segment: str,
                   closing_price: float = None, note: str = None, date: str = "") -> None:
    """Insert or update a mention row."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO mentions
            (episode_id, ticker, sentiment, segment, closing_price, note, date, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(episode_id, ticker, segment) DO UPDATE SET
            sentiment     = excluded.sentiment,
            closing_price = COALESCE(excluded.closing_price, closing_price),
            note          = COALESCE(excluded.note, note),
            updated_at    = excluded.updated_at
    """, (episode_id, ticker, sentiment, segment, closing_price, note, date, now, now))
    conn.commit()
    conn.close()


def upsert_daily_prices(ticker: str, prices: list) -> None:
    """Insert or replace daily price rows for a ticker. prices = [{date, close}, ...]"""
    conn = get_connection()
    c = conn.cursor()
    c.executemany("""
        INSERT OR REPLACE INTO daily_prices (ticker, date, close)
        VALUES (?, ?, ?)
    """, [(ticker, p["date"], p["close"]) for p in prices])
    conn.commit()
    conn.close()


# Query helpers

def get_stock(ticker: str):
    """Get stock info by ticker."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker.upper(),))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_mentions(ticker: str = None, sentiment: str = None, days: int = None):
    """Get mentions with optional filters."""
    conn = get_connection()
    c = conn.cursor()

    query = "SELECT * FROM mentions WHERE 1=1"
    params = []

    if ticker:
        query += " AND ticker = ?"
        params.append(ticker.upper())

    if sentiment:
        query += " AND sentiment = ?"
        params.append(sentiment.lower())

    if days:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        query += " AND date >= ?"
        params.append(cutoff)

    query += " ORDER BY date DESC"

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_daily_prices(ticker: str, days: int = None):
    """Get daily prices for a ticker."""
    conn = get_connection()
    c = conn.cursor()

    if days:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        c.execute("""
            SELECT * FROM daily_prices
            WHERE ticker = ? AND date >= ?
            ORDER BY date ASC
        """, (ticker.upper(), cutoff))
    else:
        c.execute("""
            SELECT * FROM daily_prices
            WHERE ticker = ?
            ORDER BY date ASC
        """, (ticker.upper(),))

    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


BUY_SENTIMENTS  = ('strong_buy', 'buy', 'mild_buy', 'buy_on_pullback')
BEAR_SENTIMENTS = ('caution_concern', 'sell_avoid')

# The "AI complex" — an industry string containing any of these substrings. Deliberately
# industry-level (not sector), because "Technology" sweeps in software/consumer names that
# had nothing to do with the 2026 AI-hardware run.
AI_INDUSTRY_KEYWORDS = ("Semiconductor", "Computer Hardware", "Information Technology Services",
                        "Electrical Equipment & Parts", "Software - Infrastructure")


def _is_ai_industry(industry: str | None) -> bool:
    return any(k in (industry or '') for k in AI_INDUSTRY_KEYWORDS)


def _buy_backtest_rows(conn, voo_prices: dict, qqq_prices: dict | None = None,
                       window_days: int = 60, sentiments: tuple | None = BUY_SENTIMENTS) -> list:
    """One row per qualifying call — the shared basis for the site-wide backtest panel,
    the per-ticker stats on each search card, and the "Where His Edge Came From" panel.

    `sentiments` filters which calls qualify (None = every sentiment). `qqq_prices` may be
    None, in which case rows carry no 'qqq' key and QQQ stats are omitted downstream.

    Two return variants per row, both free of lookahead bias:
      hold  — buy at the call-day close, hold the full window no matter what.
      exit  — same, but sell at the close on the day Cramer downgrades the ticker to
              caution/sell, if that happens inside the window. Executable in real time.

    (Deliberately NOT offered: dropping calls he later downgraded. That uses knowledge
    you wouldn't have had on the call day.)

    Only calls with a full window of forward prices are counted, and each call is
    benchmarked against VOO/QQQ over its own identical date range, so a call made in a
    hot month is compared to that same hot month.
    """
    import bisect
    from datetime import date as _date, timedelta as _td

    EXIT_SENTS = set(BEAR_SENTIMENTS)
    c = conn.cursor()

    c.execute("""
        SELECT m.ticker, m.date, m.sentiment, m.closing_price, s.industry
        FROM mentions m JOIN episodes e ON e.id = m.episode_id
        LEFT JOIN stocks s ON s.ticker = m.ticker
        WHERE m.closing_price IS NOT NULL AND m.closing_price > 0
        ORDER BY m.date
    """)
    mentions = [dict(r) for r in c.fetchall()]

    c.execute("SELECT ticker, date, close FROM daily_prices ORDER BY ticker, date")
    daily: dict = {}
    for r in c.fetchall():
        daily.setdefault(r['ticker'], {})[r['date']] = r['close']
    dates_by = {t: sorted(d) for t, d in daily.items()}

    by_ticker: dict = {}
    for m in mentions:
        by_ticker.setdefault(m['ticker'], []).append(m)

    benches = {k: v for k, v in (('spy', voo_prices), ('qqq', qqq_prices)) if v}
    bench_dates = {k: sorted(v) for k, v in benches.items()}

    def _at_or_after(dts, series, target, max_gap=5):
        i = bisect.bisect_left(dts, target)
        if i >= len(dts):
            return None
        if (_date.fromisoformat(dts[i]) - _date.fromisoformat(target)).days > max_gap:
            return None
        return series[dts[i]]

    def _at_or_before(dts, series, target):
        i = bisect.bisect_right(dts, target) - 1
        return series[dts[i]] if i >= 0 else None

    rows = []
    for m in mentions:
        if sentiments is not None and m['sentiment'] not in sentiments:
            continue
        t, cd, p0 = m['ticker'], m['date'], m['closing_price']
        dts, ser = dates_by.get(t, []), daily.get(t, {})
        if not dts:
            continue
        end = (_date.fromisoformat(cd) + _td(days=window_days)).isoformat()
        p_end = _at_or_after(dts, ser, end)
        if p_end is None:
            continue  # require a full forward window — no partial-window calls

        b = {}
        for k, series in benches.items():
            bd = bench_dates[k]
            b0 = _at_or_before(bd, series, cd)
            b1 = _at_or_after(bd, series, end)
            if b0 is None or b1 is None or not b0:
                b = None
                break
            b[k] = (b1 - b0) / b0 * 100
        if b is None:
            continue

        downgrade = next((x['date'] for x in by_ticker[t]
                          if cd < x['date'] <= end and x['sentiment'] in EXIT_SENTS), None)
        ret_hold = (p_end - p0) / p0 * 100
        if downgrade:
            p_exit = _at_or_before(dts, ser, downgrade)
            ret_exit = (p_exit - p0) / p0 * 100 if p_exit else ret_hold
        else:
            ret_exit = ret_hold

        rows.append({'ticker': t, 'date': cd, 'sentiment': m['sentiment'],
                     'hold': ret_hold, 'exit': ret_exit, 'downgraded': bool(downgrade),
                     'industry': m['industry'], 'ai': _is_ai_industry(m['industry']),
                     **b})

    return rows


def _backtest_stats(rs, key):
    """Aggregate a list of backtest rows on one return variant ('hold' or 'exit')."""
    if not rs:
        return None
    r = sorted(x[key] for x in rs)
    spy = [x['spy'] for x in rs]
    ex_spy = [x[key] - x['spy'] for x in rs]
    n = len(rs)
    top_n = max(1, n // 20)
    top5 = r[-top_n:]
    rest = r[:-top_n]
    qqq_stats = {}
    if all('qqq' in x for x in rs):
        qqq = [x['qqq'] for x in rs]
        ex_qqq = [x[key] - x['qqq'] for x in rs]
        qqq_stats = {
            'qqq_mean': round(statistics.mean(qqq), 2),
            'qqq_median': round(statistics.median(qqq), 2),
            'excess_qqq_mean': round(statistics.mean(ex_qqq), 2),
            'excess_qqq_median': round(statistics.median(ex_qqq), 2),
            'beat_qqq_pct': round(sum(1 for x in ex_qqq if x > 0) / n * 100, 1),
        }
    return {
        'n': n,
        **qqq_stats,
        'mean': round(statistics.mean(r), 2),
        'median': round(statistics.median(r), 2),
        'win_rate': round(sum(1 for x in r if x > 0) / n * 100, 1),
        'spy_mean': round(statistics.mean(spy), 2),
        'spy_median': round(statistics.median(spy), 2),
        'excess_spy_mean': round(statistics.mean(ex_spy), 2),
        'excess_spy_median': round(statistics.median(ex_spy), 2),
        'beat_spy_pct': round(sum(1 for x in ex_spy if x > 0) / n * 100, 1),
        # skew: the mean is carried by a thin right tail — quantify it
        'top5pct_n': top_n,
        'top5pct_mean': round(statistics.mean(top5), 2),
        'rest_mean': round(statistics.mean(rest), 2) if rest else None,
        'rest_median': round(statistics.median(rest), 2) if rest else None,
    }


def build_buy_backtest_by_ticker(rows: list, min_calls: int = 3) -> dict:
    """Per-ticker version of the buy-call backtest, for the search-card stat strip.

    Only tickers with at least `min_calls` qualifying buy calls are included — below
    that a median is meaningless. Samples here are small by nature (most qualifying
    tickers have 3-10 calls), so the UI flags them accordingly.
    """
    by: dict = {}
    for r in rows:
        by.setdefault(r['ticker'], []).append(r)

    def _slim(rs, key):
        s = _backtest_stats(rs, key)
        return {
            'n': s['n'],
            'median': s['median'],
            'mean': s['mean'],
            'win_rate': s['win_rate'],
            'spy_median': s['spy_median'],
            'qqq_median': s['qqq_median'],
            'excess_spy_median': s['excess_spy_median'],
            'excess_qqq_median': s['excess_qqq_median'],
            'beat_spy_pct': s['beat_spy_pct'],
            'beat_qqq_pct': s['beat_qqq_pct'],
            'best': round(max(x[key] for x in rs), 1),
            'worst': round(min(x[key] for x in rs), 1),
        }

    out = {}
    for t, rs in by.items():
        if len(rs) < min_calls:
            continue
        # Both variants, because for names Cramer later soured on they diverge hugely
        # (e.g. CRWD: +54.5% median holding through, -3.2% if you sold on his downgrade)
        # and showing only 'hold' would imply his calls worked when following him didn't.
        out[t] = {
            'n': len(rs),
            'n_downgraded': sum(1 for r in rs if r['downgraded']),
            'hold': _slim(rs, 'hold'),
            'exit': _slim(rs, 'exit'),
        }
    return out


def _extreme_buy_calls(rows: list, key: str, n: int = 8) -> dict:
    """Best and worst individual buy calls to have followed, for one return variant.

    Both tails, always — a winners-only list is cherry-picking, and here it would also
    hide the point: the mean is dragged up by a thin tail of AI moonshots, so showing
    that tail without the losing one flatters the record.

    Deduped on ticker+date+sentiment so a stock Cramer mentioned in two segments of the
    same episode doesn't occupy two rows (the aggregates still count every mention).
    """
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda x: -x[key]):
        k = (r['ticker'], r['date'], r['sentiment'])
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    def _call(r):
        return {'ticker': r['ticker'], 'date': r['date'], 'sentiment': r['sentiment'],
                'return_pct': round(r[key], 1), 'spy_pct': round(r['spy'], 1),
                'excess_pct': round(r[key] - r['spy'], 1),
                'downgraded': r['downgraded']}

    return {
        'best':  [_call(r) for r in uniq[:n]],
        'worst': [_call(r) for r in uniq[-n:][::-1]],
    }


def build_edge_source(conn, voo_prices: dict, window_days: int = 60) -> dict:
    """Where His Edge Came From — performance split by AI complex vs. everything else.

    Same machinery as the buy-call backtest (`_buy_backtest_rows`): each call is bought at
    the episode close, held `window_days` calendar days, and benchmarked against VOO over
    its *own* identical window. Only calls with a full forward window count.

    Every excess figure here is the PAIRED excess — the median of (call return − that call's
    own index return), never "median return" minus "median index return". Different calls
    land in different market windows, so subtracting the two medians is not the typical edge.
    `_backtest_stats` already does this correctly via `excess_spy_median`.

    Three cuts:
      bullish  — his buy calls. Nearly all the alpha is in the AI complex.
      bearish  — his caution/sell calls. He's right only if the stock FELL. Well calibrated
                 everywhere EXCEPT AI, where the names he turned cautious on kept ripping.
      mix      — conviction mix (share of each group's calls), showing he was MORE bullish
                 on AI, not less, and hedged with "buy on pullback" far more often there.
    """
    rows = _buy_backtest_rows(conn, voo_prices, None, window_days, sentiments=None)

    def _split(rs):
        return {
            'all':   _backtest_stats(rs, 'hold'),
            'ai':    _backtest_stats([r for r in rs if r['ai']], 'hold'),
            'other': _backtest_stats([r for r in rs if not r['ai']], 'hold'),
        }

    bull = [r for r in rows if r['sentiment'] in BUY_SENTIMENTS]
    bear = [r for r in rows if r['sentiment'] in BEAR_SENTIMENTS]

    n_ai    = sum(1 for r in rows if r['ai'])
    n_other = len(rows) - n_ai
    mix = {}
    for s in ('strong_buy', 'buy', 'mild_buy', 'buy_on_pullback',
              'wait_hold_neutral', 'caution_concern', 'sell_avoid'):
        c_ai = sum(1 for r in rows if r['ai'] and r['sentiment'] == s)
        c_ot = sum(1 for r in rows if not r['ai'] and r['sentiment'] == s)
        mix[s] = {
            'ai_n': c_ai, 'other_n': c_ot,
            'ai_pct':    round(c_ai / n_ai * 100, 1) if n_ai else None,
            'other_pct': round(c_ot / n_other * 100, 1) if n_other else None,
        }

    # Best/worst calls to FOLLOW — both drawn from the same pool of Caution/Sell calls,
    # deliberately NOT pre-filtered to AI. Showing only the worst outcomes would be
    # cherry-picking: any distribution has an ugly tail, so a one-sided table always
    # indicts. Presenting both tails is fairer AND makes the AI point more convincingly,
    # since AI names dominate the "cost you" tail without being hand-picked into it.
    # (Aggregates keep every mention; these display tables dedupe on ticker+date+sentiment
    # so an episode that mentioned a name in two segments doesn't render twice.)
    _seen, uniq = set(), []
    for r in sorted(bear, key=lambda x: -x['hold']):
        k = (r['ticker'], r['date'], r['sentiment'])
        if k not in _seen:
            _seen.add(k)
            uniq.append(r)

    def _call(r):
        return {'ticker': r['ticker'], 'date': r['date'], 'sentiment': r['sentiment'],
                'return_pct': round(r['hold'], 1), 'spy_pct': round(r['spy'], 1),
                'excess_pct': round(r['hold'] - r['spy'], 1), 'ai': r['ai']}

    worst = [_call(r) for r in uniq[:10]]                    # rose the most -> warning cost you
    best  = [_call(r) for r in sorted(uniq, key=lambda x: x['hold'])[:10]]  # fell most -> saved you
    n_u = len(uniq)
    n_fell = sum(1 for r in uniq if r['hold'] < 0)

    return {
        'window_days': window_days,
        'n_calls': len(rows),
        'n_ai': n_ai,
        'n_other': n_other,
        'ai_industries': list(AI_INDUSTRY_KEYWORDS),
        'bullish': _split(bull),
        'bearish': _split(bear),
        'conviction_mix': mix,
        'follow_calls': {
            'n': n_u,
            'n_fell': n_fell,
            'pct_fell': round(n_fell / n_u * 100, 1) if n_u else None,
            'n_rose': n_u - n_fell,
            'pct_rose': round((n_u - n_fell) / n_u * 100, 1) if n_u else None,
            'best': best,
            'worst': worst,
            'ai_in_best': sum(1 for r in best if r['ai']),
            'ai_in_worst': sum(1 for r in worst if r['ai']),
        },
    }


def _fetch_benchmark_prices(ticker: str) -> dict:
    """Fetch daily closes for a benchmark ticker from Yahoo Finance. Returns {date_str: close}."""
    if not _requests:
        return {}
    end_ts   = int(time.time())
    start_ts = end_ts - 6 * 365 * 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&period1={start_ts}&period2={end_ts}")
    try:
        r = _requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        result = r.json()['chart']['result'][0]
        prices = {}
        for ts, close in zip(result['timestamp'], result['indicators']['quote'][0]['close']):
            if close is not None:
                prices[datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')] = round(close, 2)
        return prices
    except Exception as e:
        print(f"  Warning: could not fetch {ticker} prices: {e}")
        return {}


def _nearest_price(prices: dict, date_str: str) -> float | None:
    """Return the closest price at or before date_str (looks up to 7 days back)."""
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    for offset in range(8):
        key = (d - timedelta(days=offset)).strftime('%Y-%m-%d')
        if key in prices:
            return prices[key]
    return None


def _median(values: list) -> float | None:
    """Return median of a list, ignoring Nones."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2 == 1:
        return round(vals[mid], 2)
    return round((vals[mid - 1] + vals[mid]) / 2, 2)


def _generate_heroes(sentiment_perf, sector_by_type, segment_by_type):
    """Build hero text for every analytics panel from computed stats."""

    BUY_SENTS  = {'strong_buy', 'buy', 'mild_buy', 'buy_on_pullback'}
    SELL_SENTS = {'caution_concern', 'sell_avoid'}
    SEG_LABELS = {
        'opening_commentary': 'Opening Commentary',
        'lightning_round':    'Lightning Round',
        'closing_commentary': 'Closing Commentary',
        'in_depth_analysis':  'In-Depth Analysis',
        'interview':          'Interview',
        'caller_qa':          'Caller Q&A',
        'mag7_analysis':      'Mag 7 Analysis',
    }

    def _r(v):
        if v is None: return '—'
        return ('+' if v > 0 else '') + f'{v:.1f}%'

    def _w(v):
        return f'{v:.0f}%' if v is not None else '—'

    def _wmean(rows, key, wt='n_mentions'):
        total = sum(r[wt] for r in rows if r.get(key) is not None)
        if not total:
            return None
        return sum(r[key] * r[wt] for r in rows if r.get(key) is not None) / total

    # ── Sentiment heroes (4 variants: spy/qqq × 30d/90d) ────────────────────
    buy_rows  = [r for r in sentiment_perf if r['sentiment'] in BUY_SENTS]
    sell_rows = [r for r in sentiment_perf if r['sentiment'] in SELL_SENTS]

    sentiment_heroes = {}
    for bench in ('spy', 'qqq'):
        for period in ('30d', '90d'):
            rk, wk, bk = f'median_return_{period}', f'win_rate_{period}', f'median_{bench}_{period}'
            label    = 'S&P 500' if bench == 'spy' else 'Nasdaq'
            pd_label = '30 days' if period == '30d' else '90 days'
            buy_win   = _wmean(buy_rows,  wk)
            buy_ret   = _wmean(buy_rows,  rk)
            buy_bench = _wmean(buy_rows,  bk)
            sell_wr   = _wmean(sell_rows, wk)
            sell_bench= _wmean(sell_rows, bk)
            if buy_win is None:
                continue
            direction = 'more than half' if buy_win >= 50 else 'less than half'
            h = (f"Cramer's buy calls were right {direction} the time ({_w(buy_win)}) "
                 f"and returned a median {_r(buy_ret)} over {pd_label}")
            if buy_bench is not None:
                beat = (buy_ret or 0) - buy_bench
                if abs(beat) > 0.3:
                    h += f", {'beating' if beat > 0 else 'trailing'} the {label} by {abs(beat):.1f}pp"
            h += '.'
            if sell_wr is not None:
                sell_acc = 100 - sell_wr
                h += f" His caution/sell calls were right {sell_acc:.0f}% of the time"
                if sell_bench is not None and buy_bench is not None:
                    h += (f" (those stocks returned a median {_r(sell_bench)} "
                          f"vs the {label}'s {_r(buy_bench)})")
                h += '.'
            sentiment_heroes[f'{bench}+{period}'] = h

    # ── Sector overall heroes (buy / sell) ───────────────────────────────────
    sbt = {}
    for row in sector_by_type:
        sbt.setdefault(row['sector'], {})[row['call_type']] = row

    sector_heroes = {}
    for ct in ('buy', 'sell'):
        elig = [(s, d[ct]) for s, d in sbt.items()
                if ct in d and d[ct]['n_mentions'] >= 30]
        if not elig:
            continue
        elig.sort(key=lambda x: x[1]['win_rate_30d'] or 0, reverse=(ct == 'buy'))
        best_s, best_r   = elig[0]
        worst_s, worst_r = elig[-1]
        if ct == 'buy':
            above50 = sum(1 for _, r in elig if (r['win_rate_30d'] or 0) >= 50)
            sector_heroes[ct] = (
                f"{best_s} is Cramer's best sector — {_w(best_r['win_rate_30d'])} win rate "
                f"at 30 days, median {_r(best_r['median_return_30d'])}, {best_r['n_mentions']} mentions. "
                f"{above50} of {len(elig)} sectors with 30+ mentions beat the 50% threshold. "
                f"{worst_s} is the weakest: {_w(worst_r['win_rate_30d'])}, "
                f"median {_r(worst_r['median_return_30d'])}. "
                f"Sectors greyed out have fewer than 30 mentions."
            )
        else:
            best_acc  = 100 - (best_r['win_rate_30d']  or 0)
            worst_acc = 100 - (worst_r['win_rate_30d'] or 0)
            sector_heroes[ct] = (
                f"{best_s} is Cramer's most accurate sell sector — stocks fell after {best_acc:.0f}% "
                f"of caution calls at 30 days ({best_r['n_mentions']} mentions). "
                f"{worst_s} is the weakest: stocks fell only {worst_acc:.0f}% of the time after his caution calls. "
                f"Sectors greyed out have fewer than 30 mentions."
            )

    # ── Sector detail heroes (per sector × call_type) ────────────────────────
    buy_elig  = sorted([(s, d['buy'])  for s, d in sbt.items()
                        if 'buy'  in d and d['buy']['n_mentions']  >= 30],
                       key=lambda x: x[1]['win_rate_30d'] or 0, reverse=True)
    sell_elig = sorted([(s, d['sell']) for s, d in sbt.items()
                        if 'sell' in d and d['sell']['n_mentions'] >= 30],
                       key=lambda x: x[1]['win_rate_30d'] or 0)

    avg_buy_win  = (sum(r['win_rate_30d'] for _, r in buy_elig  if r['win_rate_30d'])
                    / len(buy_elig))  if buy_elig  else None
    avg_sell_acc = (sum(100 - r['win_rate_30d'] for _, r in sell_elig if r['win_rate_30d'])
                    / len(sell_elig)) if sell_elig else None

    sector_detail = {}
    for sector, ct_dict in sbt.items():
        for ct in ('buy', 'sell'):
            if ct not in ct_dict:
                continue
            r   = ct_dict[ct]
            n   = r['n_mentions']
            win = r['win_rate_30d']
            ret = r['median_return_30d']
            ret90 = r['median_return_90d']
            if win is None:
                continue

            if ct == 'buy':
                if n < 30:
                    h = (f"{sector}: {n} buy mentions — small sample, treat stats with caution. "
                         f"Preliminary win rate {_w(win)} at 30 days, median {_r(ret)}.")
                else:
                    rank = next((i + 1 for i, (s, _) in enumerate(buy_elig) if s == sector), None)
                    of   = len(buy_elig)
                    avg  = avg_buy_win
                    diff = (win - avg) if avg else 0
                    if rank == 1:
                        comp = f"best of {of} sectors with 30+ mentions"
                    elif rank == of:
                        comp = f"weakest of {of} sectors with 30+ mentions"
                    elif diff > 4:
                        comp = f"above the {avg:.0f}% cross-sector average"
                    elif diff < -4:
                        comp = f"below the {avg:.0f}% cross-sector average"
                    else:
                        comp = f"near the {avg:.0f}% cross-sector average"
                    h = (f"{sector}: {_w(win)} of {n} buy calls were right at 30 days — {comp}. "
                         f"Median return {_r(ret)} at 30 days, {_r(ret90)} at 90 days. "
                         f"{r['n_tickers']} distinct tickers covered.")
            else:
                acc = 100 - win
                if n < 30:
                    h = (f"{sector}: {n} caution/sell mentions — small sample. "
                         f"Stocks fell after {acc:.0f}% of calls at 30 days.")
                else:
                    rank = next((i + 1 for i, (s, _) in enumerate(sell_elig) if s == sector), None)
                    of   = len(sell_elig)
                    avg  = avg_sell_acc
                    diff = (acc - avg) if avg else 0
                    if rank == 1:
                        comp = f"most accurate sell sector of {of} with 30+ mentions"
                    elif rank == of:
                        comp = f"weakest sell sector — stocks rose most often after caution calls"
                    elif diff > 4:
                        comp = f"above-average sell accuracy (avg: {avg:.0f}%)"
                    elif diff < -4:
                        comp = f"below-average sell accuracy (avg: {avg:.0f}%)"
                    else:
                        comp = "near-average sell accuracy"
                    h = (f"{sector}: stocks fell after {acc:.0f}% of {n} caution/sell calls "
                         f"at 30 days — {comp}. Median price change {_r(ret)} at 30 days, "
                         f"{_r(ret90)} at 90 days. {r['n_tickers']} distinct tickers.")
            sector_detail[f'{sector}:{ct}'] = h

    # ── Segment overall heroes (buy / sell) ──────────────────────────────────
    sgt = {}
    for row in segment_by_type:
        sgt.setdefault(row['segment'], {})[row['call_type']] = row

    segment_heroes = {}
    for ct in ('buy', 'sell'):
        elig = [(seg, d[ct]) for seg, d in sgt.items()
                if ct in d and d[ct]['n_mentions'] >= 30]
        if not elig:
            continue
        elig.sort(key=lambda x: (x[1]['win_rate_30d'] or 0) if ct == 'buy'
                  else 100 - (x[1]['win_rate_30d'] or 0), reverse=True)
        best_seg, best_r   = elig[0]
        worst_seg, worst_r = elig[-1]
        if ct == 'buy':
            segment_heroes[ct] = (
                f"{SEG_LABELS.get(best_seg, best_seg)} is Cramer's strongest buy segment — "
                f"{_w(best_r['win_rate_30d'])} right at 30 days, "
                f"median {_r(best_r['median_return_30d'])}, {best_r['n_mentions']} mentions. "
                f"{SEG_LABELS.get(worst_seg, worst_seg)} is the weakest: "
                f"{_w(worst_r['win_rate_30d'])} right, median {_r(worst_r['median_return_30d'])}."
            )
        else:
            best_acc  = 100 - (best_r['win_rate_30d']  or 0)
            worst_acc = 100 - (worst_r['win_rate_30d'] or 0)
            segment_heroes[ct] = (
                f"{SEG_LABELS.get(best_seg, best_seg)} has the sharpest sell accuracy — "
                f"stocks fell after {best_acc:.0f}% of caution calls at 30 days "
                f"({best_r['n_mentions']} mentions). "
                f"{SEG_LABELS.get(worst_seg, worst_seg)} is the weakest: "
                f"stocks fell only {worst_acc:.0f}% of the time."
            )

    # ── Segment detail heroes (per segment × call_type) ──────────────────────
    buy_seg_elig = [(seg, d['buy']) for seg, d in sgt.items()
                    if 'buy' in d and d['buy']['n_mentions'] >= 30]
    avg_seg_buy  = (sum(r['win_rate_30d'] for _, r in buy_seg_elig if r['win_rate_30d'])
                    / len(buy_seg_elig)) if buy_seg_elig else None

    segment_detail = {}
    for seg, ct_dict in sgt.items():
        for ct in ('buy', 'sell'):
            if ct not in ct_dict:
                continue
            r     = ct_dict[ct]
            n     = r['n_mentions']
            win   = r['win_rate_30d']
            win90 = r['win_rate_90d']
            ret   = r['median_return_30d']
            ret90 = r['median_return_90d']
            label = SEG_LABELS.get(seg, seg)
            if win is None:
                continue

            if ct == 'buy':
                if n < 30:
                    h = (f"{label}: {_w(win)} right at 30 days across {n} buy mentions "
                         f"— small sample, treat with caution.")
                else:
                    avg  = avg_seg_buy
                    diff = (win - avg) if avg else 0
                    comp = (f"above the segment average of {avg:.0f}%" if diff > 3
                            else f"below the segment average of {avg:.0f}%" if diff < -3
                            else "near the segment average")
                    trend = ''
                    if win90 is not None:
                        if win90 > win + 3:
                            trend = f" Performance improves over time — {_w(win90)} right at 90 days."
                        elif win90 < win - 3:
                            trend = f" Performance fades — {_w(win90)} right at 90 days."
                        else:
                            trend = f" Holds steady at {_w(win90)} right at 90 days."
                    h = (f"{label}: {_w(win)} of {n} buy calls were right at 30 days ({comp}), "
                         f"median {_r(ret)}.{trend}")
            else:
                acc   = 100 - win
                acc90 = (100 - win90) if win90 is not None else None
                h = (f"{label}: stocks fell after {acc:.0f}% of {n} caution/sell calls "
                     f"at 30 days, median {_r(ret)}.")
                if acc90 is not None:
                    trend = ('improves' if acc90 > acc + 3
                             else 'fades' if acc90 < acc - 3
                             else 'holds steady')
                    h += f" Accuracy {trend} to {acc90:.0f}% right at 90 days."
            segment_detail[f'{seg}:{ct}'] = h

    return {
        'sentiment':      sentiment_heroes,
        'sector':         sector_heroes,
        'sector_detail':  sector_detail,
        'segment':        segment_heroes,
        'segment_detail': segment_detail,
    }


def build_analytics_json(out_path: str) -> None:
    """Query the DB and write docs/data/analytics.json for the Analytics tab."""
    conn = get_connection()
    c = conn.cursor()

    # ── Sentiment performance ─────────────────────────────────────────────────
    # Fetch aggregate counts/win-rates from view, then compute medians from raw rows.
    c.execute("""
        SELECT sentiment,
               n_mentions, n_with_7d, n_with_30d, n_with_90d, n_with_180d,
               avg_return_7d, avg_return_30d, avg_return_90d, avg_return_180d,
               avg_return_since_mention,
               win_rate_7d, win_rate_30d, win_rate_90d, win_rate_180d
        FROM sentiment_performance
        WHERE n_mentions >= 10
    """)
    sentiment_perf = [dict(r) for r in c.fetchall()]

    # Compute medians per sentiment from raw forward_returns rows
    c.execute("""
        SELECT sentiment, return_7d, return_30d, return_90d, return_since_mention
        FROM forward_returns
    """)
    from collections import defaultdict
    sent_buckets = defaultdict(lambda: {'r7': [], 'r30': [], 'r90': [], 'rs': []})
    for row in c.fetchall():
        b = sent_buckets[row['sentiment']]
        b['r7'].append(row['return_7d'])
        b['r30'].append(row['return_30d'])
        b['r90'].append(row['return_90d'])
        b['rs'].append(row['return_since_mention'])

    for row in sentiment_perf:
        b = sent_buckets[row['sentiment']]
        row['median_return_7d']           = _median(b['r7'])
        row['median_return_30d']          = _median(b['r30'])
        row['median_return_90d']          = _median(b['r90'])
        row['median_return_since_mention'] = _median(b['rs'])

    # ── S&P 500 (VOO) and Nasdaq (QQQ) benchmark per sentiment ───────────────
    print("  Fetching VOO + QQQ prices for benchmark comparison…")
    voo_prices = _fetch_benchmark_prices('VOO')
    qqq_prices = _fetch_benchmark_prices('QQQ')

    c.execute("""
        SELECT sentiment, mention_date, price_latest_date
        FROM forward_returns
        WHERE return_since_mention IS NOT NULL OR return_30d IS NOT NULL OR return_90d IS NOT NULL
    """)
    from collections import defaultdict as _dd
    spy_30d_buckets  = _dd(list); spy_90d_buckets  = _dd(list)
    qqq_30d_buckets  = _dd(list); qqq_90d_buckets  = _dd(list)
    mention_rows = c.fetchall()

    for row in mention_rows:
        d = row['mention_date']
        try:
            base = datetime.strptime(d, '%Y-%m-%d')
        except (ValueError, TypeError):
            continue
        d30 = (base + timedelta(days=30)).strftime('%Y-%m-%d')
        d90 = (base + timedelta(days=90)).strftime('%Y-%m-%d')
        for prices, b30, b90 in [
            (voo_prices, spy_30d_buckets, spy_90d_buckets),
            (qqq_prices, qqq_30d_buckets, qqq_90d_buckets),
        ]:
            if not prices:
                continue
            at_mention = _nearest_price(prices, d)
            if not at_mention:
                continue
            p30 = _nearest_price(prices, d30)
            p90 = _nearest_price(prices, d90)
            if p30:
                b30[row['sentiment']].append(round((p30 - at_mention) / at_mention * 100, 2))
            if p90:
                b90[row['sentiment']].append(round((p90 - at_mention) / at_mention * 100, 2))

    for row in sentiment_perf:
        row['median_spy_30d'] = _median(spy_30d_buckets.get(row['sentiment'], []))
        row['median_spy_90d'] = _median(spy_90d_buckets.get(row['sentiment'], []))
        row['median_qqq_30d'] = _median(qqq_30d_buckets.get(row['sentiment'], []))
        row['median_qqq_90d'] = _median(qqq_90d_buckets.get(row['sentiment'], []))

    # Fetch all forward_returns rows once for median computation across all tables
    c.execute("""
        SELECT segment, market_cap_category, sector,
               return_30d, return_90d, return_since_mention
        FROM forward_returns
    """)
    from collections import defaultdict
    seg_buckets  = defaultdict(lambda: {'r30': [], 'r90': [], 'rs': []})
    cap_buckets  = defaultdict(lambda: {'r30': [], 'r90': [], 'rs': []})
    sect_buckets = defaultdict(lambda: {'r30': [], 'r90': [], 'rs': []})
    for row in c.fetchall():
        for key, buckets in [(row['segment'], seg_buckets),
                             (row['market_cap_category'], cap_buckets),
                             (row['sector'], sect_buckets)]:
            if key:
                buckets[key]['r30'].append(row['return_30d'])
                buckets[key]['r90'].append(row['return_90d'])
                buckets[key]['rs'].append(row['return_since_mention'])

    # ── Segment performance ───────────────────────────────────────────────────
    c.execute("""
        SELECT segment,
               COUNT(*)                                          AS n_mentions,
               COUNT(return_30d)                                 AS n_with_30d,
               COUNT(return_90d)                                 AS n_with_90d,
               ROUND(100.0 * SUM(CASE WHEN return_30d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)    AS win_rate_30d,
               ROUND(100.0 * SUM(CASE WHEN return_90d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_90d), 0), 1)    AS win_rate_90d
        FROM forward_returns
        WHERE segment IS NOT NULL AND segment != ''
        GROUP BY segment
        HAVING n_mentions >= 5
    """)
    segment_perf = [dict(r) for r in c.fetchall()]
    for row in segment_perf:
        b = seg_buckets[row['segment']]
        row['median_return_30d']          = _median(b['r30'])
        row['median_return_90d']          = _median(b['r90'])
        row['median_return_since_mention'] = _median(b['rs'])
    segment_perf.sort(key=lambda r: r['median_return_30d'] or 0, reverse=True)

    # ── Market cap performance ────────────────────────────────────────────────
    cap_order = {'mega': 1, 'large': 2, 'mid': 3, 'small': 4, 'micro': 5, 'nano': 6}
    c.execute("""
        SELECT market_cap_category,
               COUNT(*)                                          AS n_mentions,
               COUNT(return_30d)                                 AS n_with_30d,
               COUNT(return_90d)                                 AS n_with_90d,
               ROUND(100.0 * SUM(CASE WHEN return_30d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)    AS win_rate_30d
        FROM forward_returns
        WHERE market_cap_category IS NOT NULL AND market_cap_category != ''
        GROUP BY market_cap_category
        HAVING n_mentions >= 5
    """)
    mktcap_rows = [dict(r) for r in c.fetchall()]
    for row in mktcap_rows:
        b = cap_buckets[row['market_cap_category']]
        row['median_return_30d']          = _median(b['r30'])
        row['median_return_90d']          = _median(b['r90'])
        row['median_return_since_mention'] = _median(b['rs'])
    mktcap_perf = sorted(mktcap_rows, key=lambda r: cap_order.get(r['market_cap_category'], 99))

    # ── Sector performance by call type (buy vs sell, excluding neutral) ─────
    BUY_SENTS  = "('strong_buy','buy','mild_buy','buy_on_pullback')"
    SELL_SENTS = "('caution_concern','sell_avoid')"
    NON_NEUTRAL = "('strong_buy','buy','mild_buy','buy_on_pullback','caution_concern','sell_avoid')"

    c.execute(f"""
        SELECT sector,
               CASE WHEN sentiment IN {BUY_SENTS} THEN 'buy' ELSE 'sell' END AS call_type,
               return_30d, return_90d, return_since_mention
        FROM forward_returns
        WHERE sector IS NOT NULL AND sector != ''
          AND sentiment IN {NON_NEUTRAL}
    """)
    sbt_buckets = defaultdict(lambda: {'r30': [], 'r90': [], 'rs': []})
    for row in c.fetchall():
        key = (row[0], row[1])
        b = sbt_buckets[key]
        if row[2] is not None: b['r30'].append(row[2])
        if row[3] is not None: b['r90'].append(row[3])
        if row[4] is not None: b['rs'].append(row[4])

    c.execute(f"""
        SELECT sector,
               CASE WHEN sentiment IN {BUY_SENTS} THEN 'buy' ELSE 'sell' END AS call_type,
               COUNT(*)                                            AS n_mentions,
               COUNT(DISTINCT ticker)                              AS n_tickers,
               ROUND(100.0 * SUM(CASE WHEN return_30d > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)     AS win_rate_30d,
               ROUND(100.0 * SUM(CASE WHEN return_90d > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_90d), 0), 1)     AS win_rate_90d
        FROM forward_returns
        WHERE sector IS NOT NULL AND sector != ''
          AND sentiment IN {NON_NEUTRAL}
        GROUP BY sector, call_type
        HAVING n_mentions >= 3
        ORDER BY sector, call_type
    """)
    sector_by_type = [dict(r) for r in c.fetchall()]
    for row in sector_by_type:
        b = sbt_buckets[(row['sector'], row['call_type'])]
        row['median_return_30d']           = _median(b['r30'])
        row['median_return_90d']           = _median(b['r90'])
        row['median_return_since_mention'] = _median(b['rs'])

    # ── Segment by call type ──────────────────────────────────────────────────
    # Normalize variant segment names produced by Haiku before aggregating
    _SEG_NORM = """
        CASE segment
            WHEN 'investing_club_qa'  THEN 'caller_qa'
            WHEN 'mag_seven_analysis' THEN 'mag7_analysis'
            WHEN 'mag7_earnings'      THEN 'mag7_analysis'
            WHEN 'software_opportunities' THEN 'in_depth_analysis'
            ELSE segment
        END
    """
    c.execute(f"""
        SELECT ({_SEG_NORM}) AS segment,
               CASE WHEN sentiment IN {BUY_SENTS} THEN 'buy' ELSE 'sell' END AS call_type,
               return_30d, return_90d, return_since_mention
        FROM forward_returns
        WHERE segment IS NOT NULL AND segment != ''
          AND sentiment IN {NON_NEUTRAL}
    """)
    seg_type_buckets = defaultdict(lambda: {'r30': [], 'r90': [], 'rs': []})
    for row in c.fetchall():
        key = (row[0], row[1])
        b = seg_type_buckets[key]
        if row[2] is not None: b['r30'].append(row[2])
        if row[3] is not None: b['r90'].append(row[3])
        if row[4] is not None: b['rs'].append(row[4])

    c.execute(f"""
        SELECT ({_SEG_NORM}) AS segment,
               CASE WHEN sentiment IN {BUY_SENTS} THEN 'buy' ELSE 'sell' END AS call_type,
               COUNT(*)                                            AS n_mentions,
               COUNT(DISTINCT ticker)                             AS n_tickers,
               ROUND(100.0 * SUM(CASE WHEN return_30d > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)     AS win_rate_30d,
               ROUND(100.0 * SUM(CASE WHEN return_90d > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_90d), 0), 1)     AS win_rate_90d
        FROM forward_returns
        WHERE segment IS NOT NULL AND segment != ''
          AND sentiment IN {NON_NEUTRAL}
        GROUP BY 1, 2
        HAVING n_mentions >= 3
        ORDER BY 1, 2
    """)
    segment_by_type = [dict(r) for r in c.fetchall()]
    for row in segment_by_type:
        b = seg_type_buckets[(row['segment'], row['call_type'])]
        row['median_return_30d']           = _median(b['r30'])
        row['median_return_90d']           = _median(b['r90'])
        row['median_return_since_mention'] = _median(b['rs'])

    # ── Latest calls leaderboard ──────────────────────────────────────────────
    c.execute("""
        SELECT ticker, company, mention_date, sentiment, segment,
               sector, market_cap_category, style,
               price_at_mention, price_latest, price_latest_date,
               return_7d, return_30d, return_since_mention, days_since_mention
        FROM latest_mention_performance
        WHERE return_since_mention IS NOT NULL
        ORDER BY mention_date DESC, ticker
        LIMIT 100
    """)
    latest_calls = [dict(r) for r in c.fetchall()]

    BUY_TYPES  = "('strong_buy','buy','mild_buy','buy_on_pullback')"
    SELL_TYPES = "('wait_hold_neutral','caution_concern','sell_avoid')"

    # ── Call performance pools (all tickers, for unified calls table) ─────────
    c.execute(f"""
        SELECT ticker, company, mention_date, sentiment,
               price_at_mention, price_latest, return_7d, return_30d, return_90d,
               return_since_mention, days_since_mention,
               sector, market_cap_category
        FROM latest_mention_performance
        WHERE return_since_mention IS NOT NULL AND days_since_mention >= 1
          AND sentiment IN {BUY_TYPES}
        ORDER BY return_since_mention DESC
    """)
    buy_call_pool = [dict(r) for r in c.fetchall()]

    c.execute(f"""
        SELECT ticker, company, mention_date, sentiment,
               price_at_mention, price_latest, return_7d, return_30d, return_90d,
               return_since_mention, days_since_mention,
               sector, market_cap_category
        FROM latest_mention_performance
        WHERE return_since_mention IS NOT NULL AND days_since_mention >= 1
          AND sentiment IN {SELL_TYPES}
        ORDER BY return_since_mention DESC
    """)
    sell_call_pool = [dict(r) for r in c.fetchall()]

    # ── Top tickers by % Days Right ───────────────────────────────────────────
    import bisect as _bisect
    _BULL_DR = {'strong_buy', 'buy', 'mild_buy', 'buy_on_pullback'}
    _BEAR_DR = {'sell_avoid', 'caution_concern'}

    c.execute("""
        SELECT m.ticker, m.date, m.sentiment, m.closing_price
        FROM mentions m
        JOIN episodes e ON e.id = m.episode_id
        WHERE m.closing_price IS NOT NULL AND e.is_fundamentals = 0
        ORDER BY m.ticker, m.date
    """)
    _dr_m: dict = {}
    for r in c.fetchall():
        t, dt, s, cp = r['ticker'], r['date'], r['sentiment'], r['closing_price']
        _dr_m.setdefault(t, {}).setdefault(dt, {'price': cp, 'sents': set()})
        _dr_m[t][dt]['sents'].add(s)

    c.execute("SELECT ticker, date, close FROM daily_prices ORDER BY ticker, date")
    _dr_d: dict = {}
    for r in c.fetchall():
        _dr_d.setdefault(r['ticker'], {})[r['date']] = r['close']
    _dr_dates: dict = {t: sorted(dm.keys()) for t, dm in _dr_d.items()}

    c.execute("SELECT ticker, company, sector FROM stocks")
    _ticker_meta = {r['ticker']: {'company': r['company'] or '', 'sector': r['sector'] or ''}
                    for r in c.fetchall()}

    _top_dr = []
    for _t, _dm in _dr_m.items():
        _dates = _dr_dates.get(_t, [])
        _daily = _dr_d.get(_t, {})
        if not _dates:
            continue
        _last = _dates[-1]
        _mdates = sorted(_dm.keys())
        _total = _right = _ncalls = 0
        for _i, _dt in enumerate(_mdates):
            _e = _dm[_dt]
            _is_buy  = bool(_e['sents'] & _BULL_DR)
            _is_sell = bool(_e['sents'] & _BEAR_DR)
            if not _is_buy and not _is_sell:
                continue
            _ncalls += 1
            _cp = _e['price']
            _end = _mdates[_i + 1] if _i + 1 < len(_mdates) else _last
            _lo = _bisect.bisect_right(_dates, _dt)
            _hi = _bisect.bisect_right(_dates, _end)
            for _d in _dates[_lo:_hi]:
                _total += 1
                if _is_buy and _daily[_d] > _cp:
                    _right += 1
                elif _is_sell and _daily[_d] < _cp:
                    _right += 1
        if _total >= 20 and _ncalls >= 3:
            _meta = _ticker_meta.get(_t, {})
            _top_dr.append({
                'ticker':          _t,
                'company':         _meta['company'],
                'sector':          _meta['sector'],
                'pct_right_daily': round(_right / _total * 100, 1),
                'n_right_days':    _total,
                'n_calls':         _ncalls,
            })
    _top_dr.sort(key=lambda r: r['pct_right_daily'], reverse=True)
    top_days_right = _top_dr[:12]

    # ── Buy on Pullback analytics ────────────────────────────────────────────
    # Reuses the beta and ret_20d caches built by code/analyze_buy_on_pullback.py
    # (data/prototypes/) and the frozen model trained by code/never_trigger_model.py.
    # Caches are not refreshed here (no live yfinance calls during --rebuild-shards);
    # ret_20d for calls missing from the cache is computed from daily_prices in the DB.
    # Run those scripts manually to pick up new tickers / retrain.
    import analyze_buy_on_pullback
    import never_trigger_model
    _bop_beta_cache = analyze_buy_on_pullback.load_beta_cache()
    _bop_ret20_cache = analyze_buy_on_pullback.load_ret20_cache()
    _bop_model = never_trigger_model.load_model()
    _bop_calls, _bop_summary = analyze_buy_on_pullback.compute_analysis(
        conn, _bop_beta_cache, _bop_model, _bop_ret20_cache)
    buy_on_pullback = {
        "summary": _bop_summary,
        "calls": _bop_calls,
        "model": {
            "cv_auc": _bop_model["cv_auc"],
            "cv_accuracy": _bop_model["cv_accuracy"],
            "n_training": _bop_model["n_training"],
            "pullback_pct": _bop_model.get("pullback_pct", 5.0),
            "base_rate_never_pct": _bop_model.get("base_rate_never_pct"),
            "feature_names": _bop_model.get("feature_names", []),
        } if _bop_model else None,
    }

    # ── Buy-call backtest: follow his buy calls for 60d vs. buying the index ──
    # Rows are shared: the aggregate feeds the Analytics panel, the per-ticker
    # rollup feeds the stat strip on each search card (≥3 calls only).
    _bt_rows = _buy_backtest_rows(conn, voo_prices, qqq_prices, window_days=60)
    buy_backtest = {
        'window_days': 60,
        'n_calls': len(_bt_rows),
        'n_downgraded': sum(1 for r in _bt_rows if r['downgraded']),
        'n_tickers': len({r['ticker'] for r in _bt_rows}),
        'hold': _backtest_stats(_bt_rows, 'hold'),
        'exit': _backtest_stats(_bt_rows, 'exit'),
        # Best/worst individual calls per variant — which calls were worst depends on
        # whether you obeyed his downgrades, so both variants get their own tails.
        'extremes': {
            'hold': _extreme_buy_calls(_bt_rows, 'hold'),
            'exit': _extreme_buy_calls(_bt_rows, 'exit'),
        },
    }

    # ── Where his edge came from: AI complex vs. everything else ──
    edge_source = build_edge_source(conn, voo_prices, window_days=60)

    bt_by_ticker = build_buy_backtest_by_ticker(_bt_rows, min_calls=3)
    bt_path = Path(out_path).parent / "backtest_by_ticker.json"
    bt_path.write_text(json.dumps({'window_days': 60, 'min_calls': 3, 'tickers': bt_by_ticker},
                                  separators=(",", ":")))
    print(f"  backtest_by_ticker.json written ({len(bt_by_ticker)} tickers) → {bt_path}")

    conn.close()

    payload = {
        "generated_at":      datetime.utcnow().isoformat(),
        "sentiment_perf":    sentiment_perf,
        "segment_perf":      segment_perf,
        "mktcap_perf":       mktcap_perf,
        "sector_by_type":    sector_by_type,
        "segment_by_type":   segment_by_type,
        "latest_calls":      latest_calls,
        "buy_call_pool":     buy_call_pool,
        "sell_call_pool":    sell_call_pool,
        "top_days_right":    top_days_right,
        "heroes":            _generate_heroes(sentiment_perf, sector_by_type, segment_by_type),
        "buy_on_pullback":   buy_on_pullback,
        "buy_backtest":      buy_backtest,
        "edge_source":       edge_source,
    }

    Path(out_path).write_text(json.dumps(payload, separators=(",", ":")))
    print(f"  analytics.json written → {out_path}")


def list_tickers(min_mentions: int = 1):
    """List all tickers with mention count."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT ticker, COUNT(*) as mention_count, COUNT(DISTINCT date) as episode_count
        FROM mentions
        GROUP BY ticker
        HAVING mention_count >= ?
        ORDER BY mention_count DESC
    """, (min_mentions,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_db()
        print("Database initialized.")
    elif len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate_from_json(
            "data/stock_sentiments.json",
            "data/processed_episodes.json",
            "data/daily_prices"
        )
    else:
        print("Usage:")
        print("  python code/db.py init        - Initialize database")
        print("  python code/db.py migrate     - Migrate from JSON files")
