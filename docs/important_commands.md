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

## Mac Wake Schedule (Local Automation)

The pipeline runs locally on Mac rather than via GitHub Actions. Mac must be awake at run time.

Mad Money airs at 6 PM ET = 3 PM PT. Wake at 7:05 PM local works year-round (no DST adjustment
needed — 2:05 AM UTC in summer, 3:05 AM UTC in winter, both well after the episode is available).

```bash
# Schedule Mac to wake Mon–Fri at 7:05 PM local time
sudo pmset repeat wake MTWRF 19:05:00

# Add the cron job (paste this whole block — no editor needed):
(crontab -l 2>/dev/null; echo "10 19 * * 1-5 cd /Users/jfs-m3/Documents/DS/yt-words && caffeinate -i python3 code/pipeline.py --email-mode smtp >> /tmp/mad_money_cron.log 2>&1") | crontab -

# Confirm it was added:
crontab -l
```

`caffeinate -i` keeps the Mac awake for the duration of the pipeline run, then releases it.
Cron output (including errors) goes to `/tmp/mad_money_cron.log`.

```bash
# Verify / remove the wake schedule
pmset -g sched            # show scheduled wake times
sudo pmset repeat cancel  # remove the repeating wake schedule

# Manage cron jobs
crontab -l   # list current cron jobs
crontab -r   # remove all cron jobs (careful — no undo)

# Check last night's cron output
cat /tmp/mad_money_cron.log
```

## Transcript Timing Log

Each time a new transcript is downloaded, the pipeline logs the YouTube upload time and pipeline
fetch time to `data/transcript_timing.csv`. Use this to understand how long after air time
CNBC uploads to YouTube and whether the 7:10 PM run has enough buffer.

```bash
# View the timing log
column -t -s, data/transcript_timing.csv

# Check the last few entries
tail -5 data/transcript_timing.csv
```

Columns: `episode_date`, `video_id`, `yt_upload_utc`, `pipeline_fetch_utc`

---

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
