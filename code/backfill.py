"""
Backfill Mad Money episodes for a date range into stock_sentiments.json.

Scans the CNBC YouTube channel, finds episodes within the requested range,
skips any already in processed_episodes.json, and analyzes the rest with
Claude Haiku. No email is sent; run git push afterwards to update the website.

Usage:
    python code/backfill.py --start 2026-05-01 --end 2026-05-31
    python code/backfill.py --start 2026-04-01 --end 2026-04-30 --max-scan 5000
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yt_dlp
from pipeline import (
    CNBC_CHANNEL_ID,
    analyze_with_haiku,
    fetch_transcript,
    load_processed,
    save_processed,
    update_stock_sentiments,
)


def _date_from_title(title: str) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})", title)
    if m:
        mo, dy, yr = m.groups()
        return f"20{yr}-{mo}-{dy}"
    return ""


def discover_episodes_in_range(start: str, end: str, max_scan: int) -> list[dict]:
    """Scan CNBC channel and return Mad Money episodes within [start, end]."""
    print(f"Scanning up to {max_scan} channel entries for Mad Money episodes {start} to {end}…")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": max_scan,
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
        d = _date_from_title(title)
        if not d or d < start or d > end:
            continue
        episodes.append({"id": entry["id"], "title": title, "upload_date": d})

    episodes.sort(key=lambda e: e["upload_date"], reverse=True)
    return episodes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, metavar="YYYY-MM-DD",
                        help="Start date inclusive")
    parser.add_argument("--end", required=True, metavar="YYYY-MM-DD",
                        help="End date inclusive")
    parser.add_argument("--max-scan", type=int, default=3000, metavar="N",
                        help="Max channel entries to scan (default: 3000; increase for older dates)")
    args = parser.parse_args()

    episodes = discover_episodes_in_range(args.start, args.end, args.max_scan)
    print(f"Found {len(episodes)} Mad Money episode(s) in range.")
    if not episodes:
        print("Nothing to do.")
        return

    processed = load_processed()
    processed_ids = {r["video_id"] for r in processed}

    new_count = skipped = errors = 0
    for ep in episodes:
        vid, date = ep["id"], ep["upload_date"]
        if vid in processed_ids:
            print(f"  Skip (already done): {date}")
            skipped += 1
            continue

        print(f"\n── {date} ({vid}) ──")
        try:
            date_str, _, transcript_text = fetch_transcript(vid, date)
            analysis = analyze_with_haiku(date_str, transcript_text)
            n_sec = len(analysis.get("sections", []))
            n_stk = len(analysis.get("stocks", []))
            print(f"  Sections: {n_sec}  Stocks: {n_stk}")
            update_stock_sentiments(analysis)
            processed.append({"video_id": vid, "date": date_str})
            save_processed(processed)
            new_count += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

    print(f"\nDone. New: {new_count}  Skipped: {skipped}  Errors: {errors}")
    if new_count:
        print("Run 'git add data/ && git commit && git push' to publish to the website.")


if __name__ == "__main__":
    main()
