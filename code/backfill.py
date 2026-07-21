from __future__ import annotations

"""
Backfill Mad Money episodes for a date range into stock_sentiments.json.

Normal mode: scans the CNBC YouTube channel, finds episodes within the
requested range, skips any already in processed_episodes.json, and analyzes
the rest with Claude Haiku. No email is sent.

Reanalyze mode (--reanalyze): re-runs analysis on already-downloaded
transcripts using the current prompt. Does NOT re-download from YouTube.
Clears existing mentions for each date before writing fresh ones, so there
are no duplicates. Also regenerates data/summaries/{date}_summary.html.

Usage:
    python code/backfill.py --start 2026-05-01 --end 2026-05-31
    python code/backfill.py --start 2026-04-01 --end 2026-04-30 --max-scan 5000
    python code/backfill.py --reanalyze                          # all dates with transcripts
    python code/backfill.py --reanalyze --start 2026-06-01      # on or after date
    python code/backfill.py --reanalyze --end 2026-05-31        # on or before date
    python code/backfill.py --reanalyze --backend claude-code   # use this Claude Code session
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yt_dlp
from pipeline import (
    CNBC_CHANNEL_ID,
    DATA_DIR,
    OUTPUT_DIR,
    RULES_FILE,
    SENTIMENTS_FILE,
    SUMMARIES_DIR,
    _claude_bin,
    analyze_with_haiku,
    build_email_html,
    fetch_overcast_episode_id,
    fetch_transcript,
    generate_redirect_pages,
    load_processed,
    save_processed,
    update_stock_sentiments,
)
from db import get_connection


def _date_from_title(title: str) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})", title)
    if m:
        mo, dy, yr = m.groups()
        return f"20{yr}-{mo}-{dy}"
    return ""


def analyze_with_claude_code(date_str: str, transcript_text: str) -> dict:
    """Run analysis via the claude CLI (uses Claude Code subscription, not API credits).

    Forces Haiku explicitly — without --model this silently inherits whatever the
    session's default model is (e.g. Sonnet), which costs ~4x more per episode for
    no speed benefit. Also strips tools/settings/MCP/hooks since this is a pure
    text-in JSON-out call that needs none of them.
    """
    system_prompt = RULES_FILE.read_text()
    user_msg = f"Episode date: {date_str}\n\nTranscript:\n{transcript_text}"

    # Remove ANTHROPIC_API_KEY from subprocess env so claude CLI uses claude.ai login
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)

    result = subprocess.run(
        [
            _claude_bin(), "-p", user_msg,
            "--system-prompt", system_prompt,
            "--model", "claude-haiku-4-5-20251001",
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--output-format", "json",
        ],
        capture_output=True, text=True, timeout=450,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error (rc={result.returncode}): {result.stderr[:500]}")

    outer = json.loads(result.stdout.strip())
    if outer.get("is_error"):
        raise RuntimeError(f"claude CLI reported error (subtype={outer.get('subtype')}): {outer.get('result', '')[:500]}")

    raw = outer["result"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


def _merge_analyses(part1: dict, part2: dict) -> dict:
    """Merge two partial analyses from a split long transcript into a unified result."""
    merged = {
        "episode_date": part1.get("episode_date"),
        "episode_type": part1.get("episode_type"),
        "market_headline": part1.get("market_headline") or part2.get("market_headline"),
        "market_bullets": part1.get("market_bullets", []) or part2.get("market_bullets", []),
        "sections": part1.get("sections", []) + part2.get("sections", []),
        "stocks": [],
    }

    # Dedupe stocks by (ticker, segment, note) to avoid duplicates from overlap region
    seen = set()
    for stock in part1.get("stocks", []) + part2.get("stocks", []):
        key = (
            stock.get("ticker"),
            stock.get("segment"),
            stock.get("note", "")[:100],
        )
        if key not in seen:
            seen.add(key)
            merged["stocks"].append(stock)

    return merged


def analyze_long_transcript_split(date_str: str, transcript_text: str,
                                  backend: str = "claude-code") -> dict:
    """
    For transcripts >59k chars, split into two parts with overlap,
    analyze each separately, then merge results.
    """
    analyze_fn = analyze_with_claude_code if backend == "claude-code" else None
    if not analyze_fn:
        raise ValueError("Only claude-code backend supported for split analysis")

    total_len = len(transcript_text)
    if total_len <= 59000:
        return analyze_fn(date_str, transcript_text)

    # Split at 50% with 10k-char overlap
    midpoint = total_len // 2
    overlap = 10000

    part1_end = midpoint + overlap
    part1_text = transcript_text[:part1_end]
    part2_text = transcript_text[midpoint:]

    print(f"  Transcript is {total_len:,} chars — splitting into two parts with {overlap:,}-char overlap")
    print(f"    Part 1: 0–{part1_end:,}")
    print(f"    Part 2: {midpoint:,}–{total_len:,}")

    print(f"  Analyzing Part 1…")
    analysis1 = analyze_fn(date_str, part1_text)

    print(f"  Analyzing Part 2…")
    analysis2 = analyze_fn(date_str, part2_text)

    print(f"  Merging results…")
    merged = _merge_analyses(analysis1, analysis2)

    return merged


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


def _clear_mentions_for_date(date_str: str) -> None:
    """Remove all mentions for a given episode date from stock_sentiments.json and SQLite."""
    if SENTIMENTS_FILE.exists():
        db = json.loads(SENTIMENTS_FILE.read_text())
        stocks = db.get("stocks", {})
        for entry in stocks.values():
            entry["mentions"] = [
                m for m in entry.get("mentions", [])
                if m.get("date") != date_str
            ]
        SENTIMENTS_FILE.write_text(json.dumps(db, indent=2))

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        DELETE FROM mentions
        WHERE episode_id IN (SELECT id FROM episodes WHERE date = ?)
    """, (date_str,))
    conn.commit()
    conn.close()


def reanalyze_from_transcripts(
    start: str | None,
    end: str | None,
    backend: str = "claude-code",
) -> None:
    """Re-run analysis on existing local transcripts. No YouTube calls."""
    transcript_files = sorted(OUTPUT_DIR.glob("*_transcript.txt"))
    if not transcript_files:
        print(f"No transcript files found in {OUTPUT_DIR}")
        return

    analyze_fn = analyze_with_claude_code if backend == "claude-code" else analyze_with_haiku
    backend_label = "Claude Code session" if backend == "claude-code" else "Haiku API"

    # Build date → video_id map from processed_episodes.json
    processed = load_processed()
    date_to_vid = {ep["date"]: ep["video_id"] for ep in processed}

    # Load overcast cache for summary links
    overcast_cache_file = DATA_DIR / "overcast_episode_ids.json"
    overcast_cache = {}
    if overcast_cache_file.exists():
        overcast_cache = json.loads(overcast_cache_file.read_text())

    # Filter to requested date range
    episodes = []
    for f in transcript_files:
        date_str = f.name.replace("_transcript.txt", "")
        if start and date_str < start:
            continue
        if end and date_str > end:
            continue
        video_id = date_to_vid.get(date_str, "")
        episodes.append({"date": date_str, "path": f, "video_id": video_id})

    episodes.sort(key=lambda e: e["date"])
    print(f"Found {len(episodes)} transcript(s) to reanalyze via {backend_label}.")

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    done = errors = 0

    for ep in episodes:
        date_str = ep["date"]
        transcript_path = ep["path"]
        video_id = ep["video_id"]

        print(f"\n── {date_str} ──")
        try:
            transcript_text = transcript_path.read_text(encoding="utf-8")
            if not transcript_text.strip():
                print(f"  SKIP: transcript is empty")
                continue

            print(f"  Analyzing via {backend_label}… ({len(transcript_text):,} chars)")
            analysis = None

            # For very long transcripts (>59k chars), use split-and-merge approach
            if backend == "claude-code" and len(transcript_text) > 59000:
                try:
                    analysis = analyze_long_transcript_split(date_str, transcript_text, backend="claude-code")
                except Exception as err:
                    print(f"  Split-and-merge failed ({err}), falling back to truncation…")

            # Fallback: truncation with retries (or direct attempt if short transcript)
            if analysis is None:
                for attempt, limit in enumerate([None, 40_000, 25_000]):
                    try:
                        text = transcript_text if limit is None else transcript_text[:limit]
                        if backend == "claude-code":
                            analysis = analyze_with_claude_code(date_str, text)
                        else:
                            analysis = analyze_with_haiku(date_str, text)
                        break
                    except Exception as err:
                        if attempt < 2:
                            print(f"  Attempt {attempt+1} failed ({err}), retrying with {[40_000,25_000][attempt]:,} chars…")
                        else:
                            raise RuntimeError(f"All attempts failed: {err}") from err

            n_sec = len(analysis.get("sections", []))
            n_stk = len(analysis.get("stocks", []))
            print(f"  Sections: {n_sec}  Stocks: {n_stk}")

            # Clear old mentions AFTER successful analysis so bad transcripts don't wipe data
            print(f"  Clearing old mentions for {date_str}…")
            _clear_mentions_for_date(date_str)

            # Write fresh mentions to JSON + SQLite
            update_stock_sentiments(analysis, video_id=video_id)

            # Regenerate summary HTML
            overcast_episode_id = overcast_cache.get(date_str)
            summary_dict = {
                "date_str":            date_str,
                "analysis":            analysis,
                "audio_url":           None,
                "video_id":            video_id,
                "redirect_pages":      {},
                "overcast_episode_id": overcast_episode_id,
            }
            ep_html, _ = build_email_html([summary_dict])
            arc = SUMMARIES_DIR / f"{date_str}_summary.html"
            arc.write_text(ep_html)
            print(f"  Summary regenerated → {arc.name}")

            done += 1
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()
            errors += 1

    print(f"\nDone. Reanalyzed: {done}  Errors: {errors}")
    print("Run 'python code/pipeline.py --rebuild-shards' then commit + push to publish.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", metavar="YYYY-MM-DD",
                        help="Start date inclusive (required for normal mode)")
    parser.add_argument("--end", metavar="YYYY-MM-DD",
                        help="End date inclusive (required for normal mode)")
    parser.add_argument("--reanalyze", action="store_true",
                        help="Re-run analysis on existing local transcripts; no YouTube download")
    parser.add_argument("--backend", choices=["api", "claude-code"], default="claude-code",
                        help="Analysis backend: 'claude-code' shells out to the claude CLI and "
                             "uses your subscription (default); 'api' spends Haiku API credits")
    parser.add_argument("--max-scan", type=int, default=3000, metavar="N",
                        help="Max channel entries to scan in normal mode (default: 3000)")
    args = parser.parse_args()

    if args.reanalyze:
        reanalyze_from_transcripts(args.start, args.end, backend=args.backend)
        return

    if not args.start or not args.end:
        parser.error("--start and --end are required in normal (non-reanalyze) mode")

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
