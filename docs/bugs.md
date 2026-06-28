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

## Open

*(none)*
