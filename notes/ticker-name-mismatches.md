# Ticker / Company Name Mismatches — Review Queue

**50 tickers** where the company we stored is a *different company* than the one
Yahoo Finance says that ticker belongs to. Each is a likely mis-ticker: the call is
probably about the company in the last column, filed under the wrong symbol.

> **Snapshot, not self-updating.** Produced by comparing `stock_sentiments.json` and the
> `stocks` table against `yfinance` `shortName` for all 885 tickers, then keeping only
> the cases where *neither* store matched. Generated 2026-07-21.
> Re-run the sweep described in BUG-011 to refresh it.

Same class as the `SK`/`HYNX`/`SANDISK` rows fixed in BUG-010: the label looks fine in
isolation, but the mention is attached to a real, unrelated company's ticker — so it
inherits that company's price history and pollutes its stats.

Resolve one by confirming against the transcript, then either retargeting the mention to
the correct ticker or deleting it if it duplicates an existing correct row:

```bash
sqlite3 data/mad_money.db \
  "UPDATE mentions SET ticker='CORRECT', closing_price=NULL WHERE ticker='WRONG' AND date='YYYY-MM-DD';"
python3 code/pipeline.py --rebuild-shards      # sync DB -> JSON first
python3 code/pipeline.py --backfill-prices --tickers CORRECT
```

| Ticker | Mentions | Dates | Yahoo says this ticker is | We stored it as |
|--------|---------:|-------|---------------------------|-----------------|
| `CWEB` | 3 | 2026-04-10 … 2026-07-06 | Direxion Daily CSI China Intern | **Coreweave** |
| `BWX` | 2 | 2026-01-15 | State Street SPDR Bloomberg Int | **Babcock and Wilcox Enterprises** |
| `CSL` | 2 | 2026-01-27 … 2026-05-18 | Carlisle Companies Incorporated | **Comfort Systems USA** |
| `OBNK` | 2 | 2026-01-15 … 2026-03-17 | Osprey Bonk Trust | **Origin Bancorp** |
| `SIZ` | 2 | 2026-03-19 … 2026-05-29 | AGFiQ U.S. Market Neutral Size  | **Signet Jewelers** |
| `ABR` | 1 | 2026-01-21 | Arbor Realty Trust | **Barrick Gold** |
| `ABX` | 1 | 2026-01-28 | Abacus Global Management, Inc. | **Barrick Gold** |
| `ACOM` | 1 | 2026-03-06 | Harbor Active Commodity ETF | **Acoma Holdings** |
| `AEIS` | 1 | 2026-03-05 | Advanced Energy Industries, Inc | **AEI Systems Corp** |
| `AHCO` | 1 | 2026-04-27 | AdaptHealth Corp. | **Acuity Electronics** |
| `ARCX` | 1 | 2026-01-16 | Tradr 2X Long ACHR Daily ETF | **Ares Capital** |
| `AVX` | 1 | 2026-04-17 | Avax One Technology Ltd. | **Aeva Technologies** |
| `BCS` | 1 | 2026-01-16 | Barclays PLC | **Banco Santander** |
| `BCTX` | 1 | 2026-04-27 | BriaCell Therapeutics Corp. | **Billion to One** |
| `BDN` | 1 | 2026-03-03 | Brandywine Realty Trust | **Blue (implied Blackstone or similar; context suggests private credit entity)** |
| `BET` | 1 | 2026-03-26 | Bethpage Capital Corp | **Canadian Natural Resources** |
| `BITO` | 1 | 2026-05-14 | ProShares Bitcoin ETF | **Billion to One** |
| `BOFI` | 1 | 2026-04-28 | AXOS FINL INC | **Bank of America** |
| `CMS` | 1 | 2026-03-20 | CMS Energy Corporation | **Columbia Banking System** |
| `CRVW` | 1 | 2026-05-01 | Careview Communications, Inc. | **CoreWeave** |
| `EAGLE` | 1 | 2026-01-28 | Eagle Cement Corp | **Eagle Gold Mining** |
| `EQST` | 1 | 2026-01-26 | Energy Quest, Inc | **Equipment Share** |
| `FG` | 1 | 2026-01-20 | F&G Annuities & Life, Inc. | **Figure Technologies** |
| `IMRX` | 1 | 2026-06-16 | Immuneering Corporation | **Immunity Bio** |
| `IMTX` | 1 | 2026-04-17 | Immatics N.V. | **Immunity Bio** |
| `INSP` | 1 | 2026-04-20 | Inspire Medical Systems, Inc. | **Inspiration Semiconductors** |
| `JLS` | 1 | 2026-04-02 | Nuveen Mortgage Opportunity Ter | **Janus Living** |
| `KGC` | 1 | 2026-03-27 | Kinross Gold Corporation | **Kagra** |
| `MANE` | 1 | 2026-04-13 | Veradermics, Incorporated | **Veru Dermic** |
| `MDLM` | 1 | 2026-01-16 | MEDLEY MANAGEMENT INC | **Medline Industries** |
| `MIND` | 1 | 2026-04-20 | MIND Technology, Inc. | **Biphenium Therapeutics** |
| `NCL` | 1 | 2026-04-07 | Northann Corp. | **Norwegian Cruise Line** |
| `NVR` | 1 | 2026-04-28 | NVR, Inc. | **Novo Nordisk** |
| `OLD` | 1 | 2026-01-26 | The Long-Term Care ETF | **Old Republic International** |
| `ORGN` | 1 | 2026-04-28 | Origin Materials, Inc. | **Organon** |
| `PBR` | 1 | 2026-04-02 | Petroleo Brasileiro S.A. Petrob | **Polarcoin** |
| `PSI` | 1 | 2026-06-01 | Invesco Semiconductors ETF | **Power Solutions International** |
| `QTEC` | 1 | 2026-03-25 | First Trust NASDAQ-100-Technolo | **Quantee Electronics** |
| `RAN` | 1 | 2026-01-27 | RanMarine Technology B.V. | **Ramco Resources** |
| `RKUNY` | 1 | 2026-03-11 | Rakuten Group Inc. | **Recursion Pharmaceuticals** |
| `RSHN` | 1 | 2026-01-20 | RushNet, Inc. | **Rich Sparkle Holdings** |
| `SDOT` | 1 | 2026-01-15 | Sadot Group Inc. | **SanDisk** |
| `SPOT` | 1 | 2026-01-20 | Spotify Technology S.A. | **One Holding** |
| `SPRL` | 1 | 2026-05-12 | STRAT PETROLEUM LTD | **Spirail (exact company uncertain)** |
| `STG` | 1 | 2026-04-29 | Sunlands Technology Group | **Seagate Technology** |
| `SVCO` | 1 | 2026-03-05 | Silvaco Group, Inc. | **ServiceTitan** |
| `URG` | 1 | 2026-01-20 | Ur Energy Inc | **US Anamoney (United States Rare Earth & Critical Materials)** |
| `USA` | 1 | 2026-05-05 | Liberty All-Star Equity Fund | **USA Rare Earths** |
| `VDV` | 1 | 2026-03-27 | Vanguard Developed Markets ex-U | **Verdiv** |
| `VS` | 1 | 2026-03-11 | Versus Systems Inc. | **Victoria's Secret** |

Note the reverse risk: a few tickers whose stored name was only the symbol have since
been given Yahoo's name (e.g. `ALGT` → Allegiant Travel). That makes the *label* match
the ticker, but does not confirm the mention belongs there — `ALGT`'s call describes an
electronic-security company, i.e. Allegion (`ALLE`). Treat those as unverified too.
