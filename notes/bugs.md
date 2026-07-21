# Mad Money Site — Bug Tracker

Bugs discovered during development, with root cause and fix status.

---

## Fixed

### BUG-001 — Wrong closing price stored after ticker correction
**Discovered:** 2026-06-28  
**Symptom:** LITE (Lumentum) showed a ~9,000% return since mention. Multiple other renamed tickers had similarly bogus return values.  
**Root cause:** When Haiku outputs a wrong ticker (e.g., `CWEB` instead of `CRWV`), the pipeline fetches and stores the closing price for the *wrong* ticker. After a manual ticker correction in the DB, the old price stays in place. `--backfill-prices` skipped mentions that already had a price, so there was no easy way to fix them after the fact.  
**Affected mentions:** 19 mentions across 12 tickers (LITE ×8, CRWV ×7, AZN ×1, APP ×2, AEM ×1, CARR ×1, CMG ×1, GLW ×1, DHI ×1, DD ×1, PANW ×2, STRL ×1).  
**Fix:** Added `--tickers TICKER1,TICKER2` option to `--backfill-prices`. When tickers are specified, prices are re-fetched even if a value already exists, and both `stock_sentiments.json` and the DB are updated. All 19 affected mentions were corrected manually.  
**Usage going forward:**
```bash
python3 code/pipeline.py --backfill-prices --tickers LITE,CRWV
```

---

### BUG-002 — Manual DB corrections not reflected in ticker shards after `--rebuild-shards`
**Discovered:** 2026-06-28  
**Symptom:** After renaming tickers in the DB (e.g., LUMN→LITE, CWEB→CRWV), running `--rebuild-shards` produced shards with 0 mentions for the corrected tickers (e.g., LITE.json showed 1 mention instead of 10). Same issue with newly created ticker entries (AVEX, etc.).  
**Root cause:** `rebuild_ticker_shards()` read mention data exclusively from `stock_sentiments.json`. Manual DB corrections (ticker renames, deletions, price fixes) are invisible to it unless `stock_sentiments.json` is also hand-edited. The DB and JSON had diverged, and the JSON was treated as authoritative even though the DB was more up to date.  
**Fix:** `rebuild_ticker_shards()` now calls `_sync_mentions_from_db()` before writing shards. This function pulls all mentions from the DB and overwrites the in-memory mention lists, then persists the result back to `stock_sentiments.json`. The DB is now the authoritative source for mention data; `stock_sentiments.json` is authoritative only for ticker metadata (company name, sector, style). After any manual DB correction, `--rebuild-shards` alone is sufficient.

---

### BUG-003 — `--fetch-sectors` overwrites good sector data with blank on rate limit
**Discovered:** 2026-06-28  
**Symptom:** After running `--fetch-sectors`, many legitimate tickers (MPC, CSX, CAKE, etc.) still show no sector in Analytics, even though yfinance knows their sector. Running `--fetch-sectors` a second time returns 0 updates despite 500+ tickers still missing sector.  
**Root cause:** Two problems: (1) `fetch_all_sectors()` fetched all 1,156 tickers on every run, even ones that already had sector data. This caused Yahoo Finance to rate-limit the batch partway through. (2) When rate-limited, yfinance raises an exception caught silently, returning empty strings for sector/style. The old code then _overwrote_ any existing good sector data with those empty strings.  
**Fix:** `fetch_all_sectors()` now only targets tickers with no sector yet (skipping those already populated), and only writes new data if `meta["sector"]` is non-empty — rate-limit misses are silently skipped rather than overwriting. Safe to re-run repeatedly.

---

### BUG-005 — Hallucinated ticker variants creating duplicate company entries in Search
**Discovered:** 2026-06-29  
**Symptom:** Search tab showed two "Apple" entries (AAPL and APPL), two "Anthropic" entries (ANTH and ANTHROPIC), "Broadcom" appearing as 8 different tickers (AVGO, BRCM, BROADCOM, BRCD, etc.), and similar duplicates across 30+ companies. The wrong-ticker entries had no price history and didn't link to the correct company chart.  
**Root cause:** Haiku occasionally outputs wrong ticker symbols — typos (APPL→AAPL), spelled-out names (BROADCOM→AVGO, OPENAI→OPAI), or legacy tickers (ARMH→ARM). Each unique ticker gets its own row in `stocks` and its own shard file, so duplicates appear as separate companies on the site. A secondary issue: five tickers (BLK, CDNS, LUMN, BEN, AU) had correct tickers but wrong company names in the `stocks` table (e.g., BLK labeled "Blackstone" — it's BlackRock).  
**Fix:** Bulk SQL cleanup — `UPDATE mentions SET ticker=CORRECT WHERE ticker=WRONG` for 31 merge operations. Where the correct ticker already had a mention in the same `(episode_id, segment)`, the duplicate was deleted instead. Also updated company names for the 5 misattributed tickers. Removed 46 stale shard files.  
**Scope:** 27 mentions updated, 44 duplicates deleted, 46 stale shards removed, 5 company names corrected. Net ticker count reduced from ~1,150 to ~1,104.  
**Going forward:** After any future manual ticker correction, run:
```bash
python3 code/pipeline.py --rebuild-shards
```

---

## Open

### BUG-007 — Nightly `git push` can fail silently, leaving episodes committed locally but not on origin
**Discovered:** 2026-07-20  
**Symptom:** The 2026-07-15 and 2026-07-16 episodes had been committed to local `main` by the cron but were never pushed — `main` sat 2 commits ahead of `origin/main` for days, so the redirect pages and site data for those nights were **not live** even though the run "succeeded" and the email went out. Found by chance while merging a feature branch up.  
**Root cause:** `commit_and_push()` does `git commit` then `git push` as separate steps. If the commit succeeds but the push fails (transient network/auth/DNS blip, or GitHub being briefly unreachable at ~10 PM PT), the exception is caught and logged as `Git push failed: …` to `/tmp/mad_money_cron.log`, but the run otherwise completes normally and the email still sends. There is **no retry and no alert** — the commit just sits locally until the next successful push happens to carry it along (or someone notices). The single stuck commit is invisible unless you check `git log origin/main..main`.  
**Not yet fixed — deliberately left as-is** (a push retry was offered and declined). The failure is self-healing in practice: the next night's successful `git push` pushes all accumulated local commits, so a stuck episode goes live within ~24h as long as pushes don't fail on consecutive nights.  
**How to detect / recover manually:**
```bash
# From the cron worktree — are there local main commits not on origin?
git -C ~/Documents/DS/yt-words-cron log --oneline origin/main..main
# If so, just push them (fast-forward, safe):
git -C ~/Documents/DS/yt-words-cron push origin main
```
**Watch for:** a `Git push failed:` line in `/tmp/mad_money_cron.log`. If it starts recurring on consecutive nights (i.e. it stops self-healing), revisit adding a bounded push retry (e.g. 3 attempts with backoff) in `commit_and_push()`, and/or surfacing the failure in the email rather than only the log.

---

### BUG-004 — 18 tickers in Cramer's Calls pool have no sector (ETFs, crypto, or wrong symbols)
**Discovered:** 2026-06-28  
**Status:** These tickers will never resolve via `--fetch-sectors`. Two categories:

**Category A — ETFs / crypto (no Yahoo Finance sector by design, may want to delete):**

| Ticker | Date | Segment | Note |
|--------|------|---------|------|
| BTC | multiple (2026-02-06 through 2026-06-10) | various | Bitcoin — crypto, not a stock |
| GLD | multiple (2026-01-23 through 2026-06-22) | various | SPDR Gold ETF |
| SLV | multiple (2026-01-23 through 2026-03-06) | various | iShares Silver Trust ETF |
| AGQ | 2026-01-20 | in_depth_analysis | ProShares Ultra Silver (2× leveraged ETF) |
| VTI | 2026-06-23 | closing_commentary | Vanguard Total Stock Market ETF |
| FREL | 2026-06-10 | opening_commentary | iShares US Real Estate ETF |
| CORN | 2026-03-09 | opening_commentary | Teucrium Corn Fund ETF |
| SIJ | 2026-06-02 | interview | ProShares UltraShort Industrials ETF |

**Category B — Likely wrong ticker from Haiku (needs human verification):**

| Ticker | Date | Segment | Timestamp | Cramer's description | YouTube |
|--------|------|---------|-----------|----------------------|---------|
| USO | 2026-02-25 | lightning_round | 35:10 | "Brad Jacobs's company. Don't bet against Brad. Roofing/building materials." — USO is the oil ETF; probably QXO or XPO | [link](https://youtu.be/EkHR3syFwHc?t=2110) |
| BWX | 2026-01-15 | in_depth_analysis | 19:57 | "Nuclear/defense supplier, 80% government/Navy; commercial nuclear up 122%" — probably BWXT (BWX Technologies) | [link](https://youtu.be/-dnfldqfazA?t=1197) |
| BWX | 2026-05-15 | interview | 13:11 | "Legacy 160-year-old power equipment maker thriving on data center power" — probably BWXT | [link](https://youtu.be/JIQheuNzaAI?t=791) |
| ETP | 2026-06-12 | closing_commentary | 54:40 | "MLP yielding ~7%; cleaned up past debt" — ETP is delisted; probably ET (Energy Transfer) | [link](https://youtu.be/ECuFlhGtUsg?t=3280) |
| ETP | 2026-06-12 | caller_qa | 37:31 | "MLP yielding ~7%; cleaned up past debt" — ETP is delisted; probably ET (Energy Transfer) | [link](https://youtu.be/ECuFlhGtUsg?t=2251) |
| FLAG | 2026-04-29 | lightning_round | 35:00 | "Generic bank without edge, small dividend" — unknown small bank ticker | [link](https://youtu.be/5-rWrj-ZgK8?t=2100) |
| FLOW | 2026-01-30 | lightning_round | 34:10 | "Analog chipmaker similar to Roper of old (pipes and valves); great quarter" — unknown | [link](https://youtu.be/LmFPOWVLnwo?t=2050) |
| HF | 2026-04-21 | lightning_round | 1:00:21 | "Data center play in booming sector; Cramer called it 'mini burden' (strong buy signal)" — unknown | [link](https://youtu.be/BOPCHZNJZiU?t=3621) |
| PSI | 2026-06-01 | lightning_round | 36:24 | "Missed quarter badly and cut guidance; cut losses immediately" — unknown | [link](https://youtu.be/oHrBBaAh4Jc?t=2184) |
| RDCT | 2026-05-28 | opening_commentary | 0:17 | "Manufactures tactical drones for US Army; fan favorite with proven execution" — possibly RCAT (Red Cat Holdings) or AVAV | [link](https://youtu.be/G_nPvcsM8LA?t=17) |
| TSCM | 2026-06-08 | lightning_round | 36:26 | "Numbers are bad. Possibly end of COVID-era urban-to-rural trade." — unknown | [link](https://youtu.be/JIu6vZ3sLlQ?t=2186) |

**To fix Category B:** Listen to the linked episodes at the timestamps in the segments, identify the real ticker, then:
```bash
# In SQLite: UPDATE mentions SET ticker='CORRECT' WHERE ticker='WRONG' AND date='YYYY-MM-DD';
python3 code/pipeline.py --backfill-prices --tickers CORRECT
python3 code/pipeline.py --rebuild-shards
```

---

### BUG-006 — mentions stored under a placeholder ticker (`????` / `???`)
**Discovered:** 2026-06-29 · **Reworked:** 2026-07-21

**Symptom:** when Haiku hears a company name but cannot identify its symbol it emits a
placeholder ticker. Every such mention piles up under the same key, so the site showed one
Search entry holding 23 unrelated companies, labelled with whichever company name happened
to be stored last (it was rendering as "OpenAI").

**Fixed on 2026-07-21:**
- Placeholder tickers are now excluded from `index.json`, `recent.json` and the per-ticker
  shards, so they never reach the website. `is_unknown_ticker()` in `pipeline.py` matches
  any all-`?` ticker (both `????` and `???` occur).
- The review queue is **generated from the DB**, not hand-maintained:

  ```bash
  python3 code/pipeline.py --list-unknown-tickers   # → notes/unknown-tickers.md
  ```

  This is **run manually — the nightly pipeline does not regenerate it**, so the queue does
  not grow on its own as new episodes land. Re-run the command to pick up new placeholders
  and to drop rows you have resolved. (It is deliberately not automated: `commit_and_push()`
  only stages `docs/` + `data/`, so a nightly-written `notes/` file would sit dirty on main
  forever. Automating it would mean adding the path to both `commit_and_push()` and the
  `.githooks/pre-commit` blocked list.)

**Why the old hand-written table was removed:** it listed 18 rows captured on 2026-06-29 and
silently rotted. Reanalysing an episode calls `_clear_mentions_for_date()`, which rewrites
every mention for that date, so transcribed rows stop corresponding to anything. By
2026-07-21 only **6 of its 18 rows still existed**, 12 had vanished, and 16 undocumented
ones had accumulated. Deriving the list on demand removes that failure mode entirely.

**Status:** Open as data work (the companies still need identifying), but no longer a
website defect. See `notes/unknown-tickers.md` for the current queue.



---

## BUG-007 — Silent git push failure (RESOLVED 2026-07-21)

**Status:** Fixed.

**Root cause:** `origin` was an HTTPS remote with `credential.helper = osxkeychain`.
Under cron there is no GUI session and the login keychain is unavailable, so git could
not read credentials and every nightly push died with:

```
fatal: could not read Username for 'https://github.com': Device not configured
```

Interactive pushes kept succeeding, which masked the problem — the backlog only surfaced
when a manual push happened to sweep the stranded commits along.

**Fix:**
1. Remote switched to SSH (`git@github.com:jf-silverman/yt-words.git`). The existing
   `~/.ssh/id_ed25519` is already registered with GitHub and has **no passphrase**, so it
   works headless. One `git remote set-url` covers both worktrees (shared `.git`).
2. `commit_and_push()` now prints a loud `!!!!` banner on push failure, including the
   unpushed-commit count and the exact recovery command, instead of a single quiet line.

---

## BUG-008 — Episode analysis truncated at max_tokens (RESOLVED 2026-07-21)

**Status:** Fixed.

The 2026-07-20 episode was skipped with `Unterminated string starting at: line 527
column 15 (char 28896)`. `analyze_with_haiku()` used `max_tokens=8192`; a stock-heavy
episode emits ~30k chars of JSON, so the response was cut off mid-string and `json.loads`
failed. Raised to `ANALYSIS_MAX_TOKENS = 32000`.

---

## BUG-009 — "0 stocks" analyses marked processed and never retried (RESOLVED 2026-07-21)

**Status:** Fixed.

The 2026-07-17 run logged `Sections: 6  Stocks: 0`, wrote a stub summary, emailed
"0 stocks", and recorded the video in `processed_episodes.json` — so it would never retry
on its own. A structurally valid but empty analysis was indistinguishable from success.

**Fix:** the pipeline now raises when an analysis returns sections but zero stocks, so the
episode is skipped, left out of `processed_episodes.json`, and picked up on the next run.

---

## BUG-010 — Re-processing a date layered duplicate mentions instead of replacing them (RESOLVED 2026-07-21)

**Status:** Code fixed. Data partially cleaned — see the review queue below.

`_clear_mentions_for_date()` lived in `backfill.py` and was only called by
`--reanalyze`. Every other write path — a plain pipeline re-run on an existing date,
`backfill.py` without the flag — went straight to `update_stock_sentiments()`, which
only ever *appended*.

`UNIQUE(episode_id, ticker, segment)` hides this most of the time: a call reproduced
identically just updates the existing row. It only leaks when the second analysis
disagrees with the first — a call assigned to a different segment, or the same company
named under a different ticker. Then both rows survive and neither looks wrong in
isolation. **18 episodes** were written in more than one batch this way.

Concrete damage found:

| Date | Bad row | Reality |
|------|---------|---------|
| 2026-07-08 | `????` in_depth | duplicate of the correct `DPC` row |
| 2026-07-08 | `SK` opening | duplicate of `SKHY` (same $29B raise) |
| 2026-07-09 | `SNPS` | "an analyst raised his price target for **Sanders**" = SanDisk; `SNDK` had the same note |
| 2026-07-09 | `WHW` | "The company is **Wirehouser**, sir" = Weyerhaeuser; `WY` had the same call |
| 2026-07-09 | `SKHX` | SK Hynix again ("dominates HBM, 56% share") |
| 2026-01-23 / 01-27 | `NWR`, `NWL` | "**Newor**" / "**New Coror**" = Nucor (CEO Leon Topalian); `NUE` had both calls |
| 2026-01-30 | `FRMA`, `FIRN` | "**a firm** … CEO **Max Lechin** … buy now pay later kingpin" = Affirm |
| 2026-01-30 | `ABBY` | "**Abby** reports" = AbbVie; `ABBV` had the same call |
| 2026-01-20 | `NUSCALE POWER` | company name stored as a ticker; `SMR` is the same call |
| 2026-01-23 | `SANDISK` | company name as ticker; `SNDK` had the same call. A second `SANDISK` row (2026-05-04) was retargeted, not deleted |
| 2026-07-14 | `HYNX` | SK Hynix a third time; carried a **$38.77** close from an unrelated ticker |

Worst of these was `SK`: six SK Hynix calls under a ticker whose 2026-07-16 row carried
a **$23.14** close belonging to an unrelated company. All six now sit under `SKHY`.

**Fix:** `_clear_mentions_for_date()` moved into `pipeline.py` and is now called by
`update_stock_sentiments()` itself, so *every* write path is idempotent. It is guarded on
a non-empty analysis so a degraded result can't wipe good data, and it returns the tickers
it cleared so their shards are rewritten even when the new analysis drops them entirely.
`backfill.py`'s own copy was removed.

### Why the rest wasn't bulk-deleted

The tempting rule — "the newest analysis wins, delete everything older" — was tested and
**rejected**. Two traps:

1. `created_at` does not identify the run. `upsert_mention()` *updates* rows the new
   analysis reproduced, so they keep their original `created_at` and only `updated_at`
   moves. Splitting by `created_at` misreads a full re-analysis as a partial one.
2. Splitting by `updated_at` instead would have deleted **508 rows**, including the
   verified-correct `DPC` row and the whole of 2026-06-24's opening commentary. The later
   pass was not a faithful superset — the two runs genuinely disagree, and neither is
   authoritative.

So the remaining suspects need a transcript check each, the same way the table above was
built. Candidates surfaced by comparing note similarity across runs within an episode:

- 2026-01-20: `RISH` vs `RSHN` (Hong Kong TikTok play), `SMR` vs `SIRI` (satellite
  broadband — *both* notes look mis-tickered), `ALGT` vs `ALLE` (electronic security
  = Allegion), `CORZ` vs `CRWV`
- 2026-01-30: `CHIP` vs `CMG`
- 2026-07-09: `LMS`, `AUIV` (lightning round, no obvious counterpart)
- Same-ticker-two-segments pairs across 2026-01-15…01-30, 04-30, 06-16…06-18 — these may
  be genuine (Cramer previews in the opening, then does the deep dive), so they need
  listening, not a rule.

Re-run the detector with the note-similarity script in the BUG-010 discussion, or just
diff each episode's segments against its transcript.
