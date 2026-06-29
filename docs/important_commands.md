# Mad Money Pipeline — Important Commands

## Running the Pipeline

```bash
# Normal run — process 1 new episode, send email via SMTP (uses Haiku API)
python3 code/pipeline.py --email-mode smtp

# Run using Claude Code subscription instead of Haiku API (no API credits)
python3 code/pipeline.py --backend claude-code --email-mode smtp

# Process up to N new episodes in one run
python3 code/pipeline.py --max-episodes 3 --email-mode smtp

# Dry run — analyze and format but don't send email or push to GitHub
python3 code/pipeline.py --dry-run
```

## Backfill & Reprocessing

```bash
# Reprocess a date range (uses Haiku API by default)
python3 code/backfill.py --start 2026-05-01 --end 2026-05-31

# Reprocess using Claude Code subscription instead of API
python3 code/backfill.py --start 2026-05-01 --end 2026-05-31 --backend claude-code
```

## Data Maintenance

```bash
# Rebuild all website data shards from the database
# Run this after any manual DB correction or ticker fix
python3 code/pipeline.py --rebuild-shards

# Fill in missing closing prices for all mentions
python3 code/pipeline.py --backfill-prices

# Force-refresh closing prices for specific tickers (e.g. after a ticker correction)
python3 code/pipeline.py --backfill-prices --tickers LITE,CRWV

# Fetch sector/style metadata from Yahoo Finance for tickers that are missing it
# Safe to re-run; never overwrites existing data. If 0 updates, wait 15–30 min and retry.
python3 code/pipeline.py --fetch-sectors

# Rewrite redirect pages for a specific date (e.g. if Overcast ID was wrong)
python3 code/pipeline.py --fix-redirects 2026-06-26
```

## Database (SQLite)

```bash
# Open the database interactively
sqlite3 data/mad_money.db

# Correct a wrong ticker (then backfill prices and rebuild shards)
# UPDATE mentions SET ticker='CORRECT' WHERE ticker='WRONG' AND date='YYYY-MM-DD';

# Full correction sequence after any manual DB edit:
python3 code/pipeline.py --backfill-prices --tickers CORRECT
python3 code/pipeline.py --rebuild-shards
```

## YouTube Cookie Refresh

YouTube session cookies expire periodically. When the pipeline fails with bot-check errors:

```bash
# Re-export cookies from Chrome (yt-dlp reads them automatically on Mac)
yt-dlp --cookies-from-browser chrome -o /dev/null --skip-download https://www.youtube.com/

# For GitHub Actions: filter to youtube/google domains and update the YOUTUBE_COOKIES secret
grep -E '(youtube\.com|google\.com)' ~/Library/... > yt_cookies_filtered.txt
```

## GitHub Pages

```bash
# The pipeline pushes docs/ automatically. To push manually:
git add docs/
git commit -m "Manual site update"
git push
```
