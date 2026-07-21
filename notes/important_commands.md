# Mad Money Pipeline — Important Commands

## Running the Pipeline

```bash
# Normal run — process 1 new episode, send email via SMTP.
# Analysis uses the Claude Code subscription by default (no API credits spent).
python3 code/pipeline.py --email-mode smtp

# Opt in to the Haiku API instead (spends API credits — only when explicitly wanted)
python3 code/pipeline.py --backend api --email-mode smtp

# Process up to N new episodes in one run
python3 code/pipeline.py --max-episodes 3 --email-mode smtp

# Dry run — analyze and format but don't send email or push to GitHub
python3 code/pipeline.py --dry-run
```

## Backfill & Reprocessing

```bash
# Reprocess a date range (Claude Code subscription by default)
python3 code/backfill.py --start 2026-05-01 --end 2026-05-31

# Re-run analysis on transcripts already on disk (no YouTube calls) — fixes a bad episode
python3 code/backfill.py --reanalyze --start 2026-07-17 --end 2026-07-17

# Opt in to the Haiku API instead (spends API credits)
python3 code/backfill.py --start 2026-05-01 --end 2026-05-31 --backend api
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

# Regenerate the manual-review queue of unidentified tickers (???? / ???)
# Writes notes/unknown-tickers.md with a timestamped YouTube link per mention.
# Always derived from the DB — resolved rows drop off automatically.
python3 code/pipeline.py --list-unknown-tickers
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

# Add the cron job (paste this whole block — no editor needed).
# NOTE: runs from the dedicated main-pinned worktree, not the primary folder (see below):
(crontab -l 2>/dev/null; echo "58 21 * * 1-5 cd /Users/jfs-m3/Documents/DS/yt-words-cron && caffeinate -i /Users/jfs-m3/Documents/DS/yt-words/.venv/bin/python3 /Users/jfs-m3/Documents/DS/yt-words-cron/code/pipeline.py --email-mode smtp >> /tmp/mad_money_cron.log 2>&1") | crontab -

# Confirm it was added:
crontab -l
```

`caffeinate -i` keeps the Mac awake for the duration of the pipeline run, then releases it.
Cron output (including errors) goes to `/tmp/mad_money_cron.log`.

> ⚠️ `crontab <file>` / `crontab -` can hang when run from an automation context (macOS
> permission dialog that only appears for a real Terminal). Run it in your own Terminal, or
> it may complete in the background after a timeout.

### The cron runs from a git worktree pinned to `main`

GitHub Pages publishes from `main`, and `commit_and_push()` sweeps everything dirty under
`docs/` + `data/` onto main — so if the cron ran on a feature branch with uncommitted
`stocks.html` edits, it would publish that half-finished work to the live site. To avoid
that, the cron runs from a **dedicated worktree that's always on `main`**:

- `~/Documents/DS/yt-words`      → primary folder (develop on feature branches here)
- `~/Documents/DS/yt-words-cron` → main-pinned worktree the cron uses

Shared gitignored state (`.env`, `data/mad_money.db`, `data/transcripts`, `data/summaries`)
is symlinked from the worktree back to the primary folder, and those symlink names are added
to `.git/info/exclude` (local, uncommitted) so `git add data/` never commits them.

**Consequence:** git won't check out the same branch in two worktrees, so you can no longer
`git checkout main` in the primary folder — do main work and merges *into* main from the
`yt-words-cron` folder. To undo: `git worktree remove ../yt-words-cron` and repoint the cron.

```bash
git worktree list                         # show both working trees
cd ~/Documents/DS/yt-words-cron           # go here to work on main / merge into main
git -C ~/Documents/DS/yt-words-cron pull  # refresh the worktree's main
```

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
# Use --no-playlist to skip fetching recommended feed metadata
yt-dlp --cookies-from-browser chrome --no-playlist -o /dev/null --skip-download https://www.youtube.com/

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

## Generated artifacts are owned by `main` (pre-commit hook)

Pipeline-generated files — `docs/data/`, `docs/redirect/`, `data/daily_prices/`,
`data/stock_sentiments.json`, `data/processed_episodes.json`, `data/overcast_episode_ids.json`,
`data/transcript_timing.csv` — may only be committed on `main`. A `.githooks/pre-commit` hook
blocks committing them on any other branch (they'd cause 3-way merge conflicts / shard corruption
on `dev → main`). Source files (`docs/*.html`, `code/`, `prompts/`, `notes/`) are unaffected.

```bash
# One-time per clone (already set on this machine; shared across both worktrees):
git config core.hooksPath .githooks

# Previewing artifact changes on a feature branch is fine — just don't commit them:
python3 code/pipeline.py --rebuild-shards      # regenerates; leave uncommitted
git restore --staged docs/data/ docs/redirect/ data/   # if you accidentally staged them

# To PUBLISH artifact changes, regenerate on the main worktree (it owns them):
cd ~/Documents/DS/yt-words-cron && python3 code/pipeline.py --rebuild-shards

# Genuine exception only:
git commit --no-verify
```
