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

---

### BUG-003 — `--fetch-sectors` overwrites good sector data with blank on rate limit
**Discovered:** 2026-06-28  
**Symptom:** After running `--fetch-sectors`, many legitimate tickers (MPC, CSX, CAKE, etc.) still show no sector in Analytics, even though yfinance knows their sector. Running `--fetch-sectors` a second time returns 0 updates despite 500+ tickers still missing sector.  
**Root cause:** Two problems: (1) `fetch_all_sectors()` fetched all 1,156 tickers on every run, even ones that already had sector data. This caused Yahoo Finance to rate-limit the batch partway through. (2) When rate-limited, yfinance raises an exception that is caught silently, returning empty strings for sector/style. The old code then _overwrote_ any existing good sector data with those empty strings, erasing previously correct values.  
**Fix:** `fetch_all_sectors()` now only targets tickers with no sector yet (skipping those already populated), and only writes new data if `meta["sector"]` is non-empty — rate-limit misses are silently skipped rather than overwriting. Safe to re-run repeatedly; each run fills in whatever yfinance returns until all real tickers are covered.  
**Residual:** ~350 tickers in the DB are hallucinated/private/OTC and will never get sector data from yfinance. These show as blank sector in Analytics permanently. The remaining ~200 real-but-missing tickers need `--fetch-sectors` re-run after the Yahoo Finance rate limit clears (~15–30 minutes).

---

## Open

*(none)*
