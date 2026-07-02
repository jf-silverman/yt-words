#!/usr/bin/env python3
"""
Download missing transcript .txt files from YouTube for all DB episodes.
Runs in batches of 10 so stalls are easy to spot. Does NOT run Haiku analysis.

Usage:
    python3 code/fetch_transcripts.py                    # all missing from Jan 1 2026
    python3 code/fetch_transcripts.py --start 2026-06-01 # on or after date
    python3 code/fetch_transcripts.py --batch-size 5     # override batch size
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import get_connection
from pipeline import OUTPUT_DIR, fetch_transcript


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01", help="Only fetch episodes on or after this date")
    ap.add_argument("--end", default=None, help="Only fetch episodes on or before this date")
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--delay", type=float, default=70.0, help="Seconds to wait between fetches (default 70)")
    args = ap.parse_args()

    conn = get_connection()
    query = "SELECT date, video_id FROM episodes WHERE date >= ?"
    params: list = [args.start]
    if args.end:
        query += " AND date <= ?"
        params.append(args.end)
    query += " ORDER BY date"
    episodes = conn.execute(query, params).fetchall()
    conn.close()

    missing = [
        (row["date"], row["video_id"])
        for row in episodes
        if not (OUTPUT_DIR / f"{row['date']}_transcript.txt").exists()
    ]

    print(f"Episodes in DB from {args.start}: {len(episodes)}")
    print(f"Already have transcripts: {len(episodes) - len(missing)}")
    print(f"Need to download: {len(missing)}")
    print()

    if not missing:
        print("Nothing to do.")
        return

    ok = 0
    fail = 0
    bs = args.batch_size
    for i in range(0, len(missing), bs):
        batch = missing[i : i + bs]
        batch_num = i // bs + 1
        total_batches = (len(missing) + bs - 1) // bs
        print(f"--- Batch {batch_num}/{total_batches} (episodes {i+1}–{min(i+bs, len(missing))} of {len(missing)}) ---")
        for i_ep, (date, vid) in enumerate(batch):
            try:
                fetch_transcript(vid, date)
                print(f"  ✓ {date}  ({vid})")
                ok += 1
            except Exception as e:
                print(f"  ✗ {date}  ({vid}): {e}")
                fail += 1
            if args.delay > 0 and i_ep < len(batch) - 1:
                delay = random.uniform(63, 91)
                time.sleep(delay)
        print(f"  Batch done — running total: {ok} ok, {fail} failed")
        if i + bs < len(missing):
            print(f"  Pausing 10 minutes before next batch…\n")
            time.sleep(600)
        else:
            print()

    print(f"Finished. {ok} downloaded, {fail} failed.")


if __name__ == "__main__":
    main()
