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
            style TEXT,
            ipo_date TEXT,
            is_private INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

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

    # Create indices for common queries
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_episode ON mentions(episode_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_ticker ON mentions(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_date ON mentions(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mentions_sentiment ON mentions(sentiment)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker ON daily_prices(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date)")

    conn.commit()
    conn.close()


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
            (ticker, company, sector, style, ipo_date, is_private, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            entry.get("company", ""),
            entry.get("sector"),
            entry.get("style"),
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


def upsert_stock(ticker: str, company: str, sector: str = None, style: str = None,
                 ipo_date: str = None, is_private: bool = False) -> None:
    """Insert or update a stock row."""
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO stocks (ticker, company, sector, style, ipo_date, is_private, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            company    = excluded.company,
            sector     = COALESCE(excluded.sector, sector),
            style      = COALESCE(excluded.style, style),
            ipo_date   = COALESCE(excluded.ipo_date, ipo_date),
            is_private = excluded.is_private,
            updated_at = excluded.updated_at
    """, (ticker, company, sector, style, ipo_date, 1 if is_private else 0, now, now))
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
