"""
SQLite database module for Mad Money pipeline.
Manages schema, migrations, and provides ORM-like functions for data access.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

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
            WHERE m.closing_price IS NOT NULL AND m.closing_price > 0
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
        SELECT fr.*
        FROM forward_returns fr
        WHERE fr.mention_date = (
            SELECT MAX(mention_date) FROM forward_returns fr2
            WHERE fr2.ticker = fr.ticker
        )
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
                   summary_html: str = None, overcast_episode_id: str = None) -> int:
    """Insert or update an episode row. Returns the episode id."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO episodes (date, video_id, transcript_text, summary_html,
                              overcast_episode_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            video_id           = excluded.video_id,
            transcript_text    = COALESCE(excluded.transcript_text, transcript_text),
            summary_html       = COALESCE(excluded.summary_html, summary_html),
            overcast_episode_id= COALESCE(excluded.overcast_episode_id, overcast_episode_id),
            updated_at         = excluded.updated_at
    """, (date, video_id, transcript_text, summary_html, overcast_episode_id, now, now))
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


def _median(values: list) -> float | None:
    """Return median of a list, ignoring Nones."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2 == 1:
        return round(vals[mid], 2)
    return round((vals[mid - 1] + vals[mid]) / 2, 2)


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

    # ── Segment performance ───────────────────────────────────────────────────
    c.execute("""
        SELECT segment,
               COUNT(*)                                          AS n_mentions,
               COUNT(return_30d)                                 AS n_with_30d,
               COUNT(return_90d)                                 AS n_with_90d,
               ROUND(AVG(return_30d),  2)                        AS avg_return_30d,
               ROUND(AVG(return_90d),  2)                        AS avg_return_90d,
               ROUND(AVG(return_since_mention), 2)               AS avg_return_since_mention,
               ROUND(100.0 * SUM(CASE WHEN return_30d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)    AS win_rate_30d,
               ROUND(100.0 * SUM(CASE WHEN return_90d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_90d), 0), 1)    AS win_rate_90d
        FROM forward_returns
        WHERE segment IS NOT NULL AND segment != ''
        GROUP BY segment
        HAVING n_mentions >= 5
        ORDER BY avg_return_30d DESC
    """)
    segment_perf = [dict(r) for r in c.fetchall()]

    # ── Market cap performance ────────────────────────────────────────────────
    cap_order = {'mega': 1, 'large': 2, 'mid': 3, 'small': 4, 'micro': 5, 'nano': 6}
    c.execute("""
        SELECT market_cap_category,
               COUNT(*)                                          AS n_mentions,
               COUNT(return_30d)                                 AS n_with_30d,
               COUNT(return_90d)                                 AS n_with_90d,
               ROUND(AVG(return_30d),  2)                        AS avg_return_30d,
               ROUND(AVG(return_90d),  2)                        AS avg_return_90d,
               ROUND(AVG(return_since_mention), 2)               AS avg_return_since_mention,
               ROUND(100.0 * SUM(CASE WHEN return_30d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)    AS win_rate_30d
        FROM forward_returns
        WHERE market_cap_category IS NOT NULL AND market_cap_category != ''
        GROUP BY market_cap_category
        HAVING n_mentions >= 5
        ORDER BY avg_return_30d DESC
    """)
    mktcap_perf = sorted([dict(r) for r in c.fetchall()],
                         key=lambda r: cap_order.get(r['market_cap_category'], 99))

    # ── Sector performance ────────────────────────────────────────────────────
    c.execute("""
        SELECT sector,
               COUNT(*)                                          AS n_mentions,
               COUNT(DISTINCT ticker)                            AS n_tickers,
               COUNT(return_30d)                                 AS n_with_30d,
               ROUND(AVG(return_30d),  2)                        AS avg_return_30d,
               ROUND(AVG(return_90d),  2)                        AS avg_return_90d,
               ROUND(AVG(return_since_mention), 2)               AS avg_return_since_mention,
               ROUND(100.0 * SUM(CASE WHEN return_30d  > 0 THEN 1 ELSE 0 END)
                           / NULLIF(COUNT(return_30d), 0), 1)    AS win_rate_30d
        FROM forward_returns
        WHERE sector IS NOT NULL AND sector != ''
        GROUP BY sector
        HAVING n_mentions >= 5
        ORDER BY n_mentions DESC
    """)
    sector_perf = [dict(r) for r in c.fetchall()]

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

    # ── Top winners / losers (all time, by return_since_mention) ─────────────
    c.execute("""
        SELECT ticker, company, mention_date, sentiment,
               price_at_mention, price_latest, return_since_mention, days_since_mention,
               sector, market_cap_category
        FROM latest_mention_performance
        WHERE return_since_mention IS NOT NULL AND days_since_mention >= 1
        ORDER BY return_since_mention DESC
        LIMIT 10
    """)
    top_winners = [dict(r) for r in c.fetchall()]

    c.execute("""
        SELECT ticker, company, mention_date, sentiment,
               price_at_mention, price_latest, return_since_mention, days_since_mention,
               sector, market_cap_category
        FROM latest_mention_performance
        WHERE return_since_mention IS NOT NULL AND days_since_mention >= 1
        ORDER BY return_since_mention ASC
        LIMIT 10
    """)
    top_losers = [dict(r) for r in c.fetchall()]

    conn.close()

    payload = {
        "generated_at":      datetime.utcnow().isoformat(),
        "sentiment_perf":    sentiment_perf,
        "segment_perf":      segment_perf,
        "mktcap_perf":       mktcap_perf,
        "sector_perf":       sector_perf,
        "latest_calls":      latest_calls,
        "top_winners":       top_winners,
        "top_losers":        top_losers,
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
