# Ticker / Company Name Mismatches — Review Queue

**64 ticker(s)** hold a company name that Yahoo Finance says belongs to
a different company. These are not all the same problem — some are wrong data,
most are a name we wrote informally — so they are split by **what can actually be
proved**, not by what they look like.

The test is the question in reverse: ignoring the symbol we filed it under, what
symbol does Yahoo return for the company name we stored? A different symbol back
means the call is sitting on the wrong company; the same symbol means our name is
merely informal.

That settles **10 of 64**. It cannot settle the other
**54**, because Yahoo's search only matches *current legal* names — it
returns nothing for "Snapchat", "Burlington Coat Factory" or "D-Wave Systems"
exactly as it returns nothing for a caption garble. Those need the transcript.

> **Generated file — do not edit by hand.**
>
> ```bash
> python3 code/pipeline.py --check-ticker-names
> ```
>
> **Manual — the nightly pipeline does not run this.** The nightly run checks only
> the episode it just analyzed and prints any flags in its output; this rebuilds the
> full picture across every ticker. Re-run it to pick up new episodes and to drop
> rows you have resolved.

Confirm against the transcript first, then retarget the mention (or delete it if it
duplicates a correct row):

```bash
sqlite3 data/mad_money.db \
  "UPDATE mentions SET ticker='CORRECT', closing_price=NULL WHERE ticker='WRONG';"
python3 code/pipeline.py --rebuild-shards
python3 code/pipeline.py --backfill-prices --tickers CORRECT
```


## 1. Likely mis-tickers — 5 ticker(s), the data is wrong

**This is the section that matters.** Yahoo maps our stored company name to a
*different* symbol than the one we filed the call under, so the call is most
likely attached to an unrelated company and has inherited its price history.
Every return, chart and backtest for both tickers is affected.

The suggested symbol is advisory — Yahoo's search picks the first US listing and
can be wrong, and the *company* half of the pair may be the mistaken one.
Confirm against the transcript before changing anything.

| Ticker | Mentions | Dates | We stored it as | That name is probably | But this symbol is |
|--------|---------:|-------|-----------------|----------------------|--------------------|
| `AVX` | 1 | 2026-04-17 | **Aeva Technologies** | `AEVA` | Avax One Technology Ltd. |
| `AX` | 1 | 2026-07-21 | **Axiom (Defense Technology)** | `AXIN` | Axos Financial, Inc. |
| `BDN` | 1 | 2026-03-03 | **Blue (implied Blackstone or similar; context suggests private credit entity)** | `OBDC` | Brandywine Realty Trust |
| `CPK` | 1 | 2026-03-12 | **Campbell Soup Company** | `CPB` | Chesapeake Utilities Corporation |
| `USA` | 1 | 2026-05-05 | **USA Rare Earth** | `USAR` | Liberty All-Star Equity Fund |


## 2. Undecidable without the transcript — 54 ticker(s)

Yahoo's search recognises neither name, so there is no evidence either way. This
bucket genuinely mixes both problems: harmless old names ("Burlington Coat
Factory", "Snapchat") sit next to real mis-tickers ("Kagra" filed on Kinross
Gold, "Verdiv" on a Vanguard ETF). Read the transcript.

**`Similar?` is a weak triage hint, not a verdict.** `no` means the two names
share nothing and is worth looking at first; `~` means they resemble each other
and is worth looking at last. No string rule does better than this — "Inspira
Technologies" vs "Inspire Medical" are different companies but score like
"Snapchat" vs "Snap Inc", and "Eagle Gold" vs "Eagle Cement" share a word
exactly the way "D-Wave Systems" vs "D-Wave Quantum" do. Sorted hint-first.

| Ticker | Mentions | Dates | We stored it as | Yahoo's name | Similar? |
|--------|---------:|-------|-----------------|--------------|----------|
| `BWX` | 2 | 2026-01-15 | **Babcock and Wilcox Enterprises** | State Street SPDR Bloomberg Int | **no** |
| `ABX` | 1 | 2026-01-28 | **Barrick Gold** | Abacus Global Management, Inc. | **no** |
| `ACOM` | 1 | 2026-03-06 | **Acorn Realty Trust** | Harbor Active Commodity ETF | **no** |
| `AHCO` | 1 | 2026-04-27 | **Acuity Electronics** | AdaptHealth Corp. | **no** |
| `ATEN` | 1 | 2026-05-05 | **Aten International** | A10 Networks, Inc. | **no** |
| `BCTX` | 1 | 2026-04-27 | **Billion to One** | BriaCell Therapeutics Corp. | **no** |
| `BITO` | 1 | 2026-05-14 | **Billion to One** | ProShares Bitcoin ETF | **no** |
| `BK` | 1 | 2026-06-23 | **Bob Evans Farms** | Bank of New York Mellon Corp | **no** |
| `EQST` | 1 | 2026-01-26 | **Equipment Share** | Energy Quest, Inc | **no** |
| `FG` | 1 | 2026-01-20 | **Figure Technologies** | F&G Annuities & Life, Inc. | **no** |
| `IMRX` | 1 | 2026-06-16 | **Immunity Bio** | Immuneering Corporation | **no** |
| `IMTX` | 1 | 2026-04-17 | **Immunity Bio** | Immatics N.V. | **no** |
| `INSP` | 1 | 2026-04-20 | **Inspira Technologies** | Inspire Medical Systems, Inc. | **no** |
| `KD` | 1 | 2026-02-24 | **Kendrell** | Kyndryl Holdings, Inc. | **no** |
| `KGC` | 1 | 2026-03-27 | **Kagra** | Kinross Gold Corporation | **no** |
| `KMG` | 1 | 2026-03-26 | **Kimcor** | KMG Chemicals, Inc. | **no** |
| `MDLM` | 1 | 2026-01-16 | **Medline Industries** | MEDLEY MANAGEMENT INC | **no** |
| `MIND` | 1 | 2026-04-20 | **Biphenium Therapeutics** | MIND Technology, Inc. | **no** |
| `NU` | 1 | 2026-01-23 | **Nubank** | Nu Holdings Ltd. | **no** |
| `PBR` | 1 | 2026-04-02 | **Polarcoin Beverage / Polar Bear (PBR stock ticker context unclear)** | Petroleo Brasileiro S.A. Petrob | **no** |
| `PCG` | 1 | 2026-04-23 | **PG&E Corporation** | Pacific Gas & Electric Co. | **no** |
| `PDYN` | 1 | 2026-03-24 | **Paladin** | Palladyne AI Corp. | **no** |
| `PLC` | 1 | 2026-07-06 | **Power & Light Company** | Principal U.S. Large-Cap Multi-Factor ETF | **no** |
| `QTEC` | 1 | 2026-03-25 | **Quantee Electronics** | First Trust NASDAQ-100-Technolo | **no** |
| `QTUM` | 1 | 2026-06-04 | **Quantinium** | Defiance Quantum ETF | **no** |
| `RAN` | 1 | 2026-01-27 | **Ramco Resources** | RanMarine Technology B.V. | **no** |
| `SLS` | 1 | 2026-05-28 | **Selecta Biosciences** | SELLAS Life Sciences Group, Inc | **no** |
| `SPRL` | 1 | 2026-05-12 | **Unknown (SPRL)** | STRAT PETROLEUM LTD | **no** |
| `THO` | 1 | 2026-06-23 | **Tenneco (Thomas Oil)** | THOR Industries, Inc. | **no** |
| `TMPO` | 1 | 2026-03-27 | **Tempest AI** | Tempo Automation Holdings, Inc. | **no** |
| `URG` | 1 | 2026-01-20 | **US Anamoney (United States Rare Earth & Critical Materials)** | Ur Energy Inc | **no** |
| `VDV` | 1 | 2026-03-27 | **Verdiv** | Vanguard Developed Markets ex-U | **no** |
| `PAYX` | 4 | 2026-03-25 … 2026-06-30 | **Paychecks** | Paychex, Inc. | ~ |
| `SNAP` | 3 | 2026-04-01 … 2026-06-16 | **Snapchat** | Snap Inc. | ~ |
| `BTC` | 2 | 2026-03-02 … 2026-04-24 | **Bitcoin** | Grayscale Bitcoin Mini Trust (B | ~ |
| `HBAN` | 2 | 2026-01-16 … 2026-04-10 | **Huntington Bancorp** | Huntington Bancshares Incorpora | ~ |
| `VCX` | 2 | 2026-03-24 … 2026-07-08 | **Fundrise Innovation Fund** | Fundrise Growth Tech Fund, LLC | ~ |
| `AEIS` | 1 | 2026-03-05 | **Array Electronic Industries (Ametek/AEI Systems)** | Advanced Energy Industries, Inc | ~ |
| `AUTR` | 1 | 2026-03-27 | **Auterion** | Autris | ~ |
| `BURL` | 1 | 2026-04-07 | **Burlington Coat Factory** | Burlington Stores, Inc. | ~ |
| `DECK` | 1 | 2026-01-05 | **Deckers Brands** | Deckers Outdoor Corporation | ~ |
| `EAGLE` | 1 | 2026-01-28 | **Eagle Gold Mining** | Eagle Cement Corp | ~ |
| `EQPT` | 1 | 2026-03-24 | **Equipment Shares** | EquipmentShare.com Inc | ~ |
| `FWONK` | 1 | 2026-03-06 | **Liberty Media Formula One** | Liberty Media Corporation - Ser | ~ |
| `KRMN` | 1 | 2026-01-05 | **Karman Space & Defense** | Karman Holdings Inc. | ~ |
| `NRGV` | 1 | 2026-05-15 | **Energy Storage Company** | Energy Vault Holdings, Inc. | ~ |
| `PRIM` | 1 | 2026-03-10 | **Primary Energy Holdings (infrastructure services)** | Primoris Services Corporation | ~ |
| `QBTS` | 1 | 2026-06-01 | **D-Wave Systems** | D-Wave Quantum Inc. | ~ |
| `RAL` | 1 | 2026-06-05 | **Reliant** | Ralliant Corporation | ~ |
| `SATL` | 1 | 2026-01-28 | **Satalogic Inc.** | Satellogic Inc. | ~ |
| `SGHC` | 1 | 2026-04-13 | **Supergroup** | Super Group (SGHC) Limited | ~ |
| `TEM` | 1 | 2026-02-06 | **Tempest AI** | Tempus AI, Inc. | ~ |
| `TKR` | 1 | 2026-06-04 | **Timkin** | Timken Company (The) | ~ |
| `UAMY` | 1 | 2026-03-12 | **U.S. Antimony Corporation** | United States Antimony Corporation | ~ |


## 3. Name variants — 5 ticker(s), cosmetic only

Yahoo maps our stored name back to the *same* symbol, so the ticker is correct
and no price history is affected. Our name is just informal ("Snapchat"),
shortened ("Petco"), dated ("Burlington Coat Factory"), or a caption
misspelling. Safe to leave alone; fix only if the wording bothers you on the
site. For a genuine rename, prefer `New Name (formerly Old Name)` — see the
renamed-companies note in CLAUDE.md.

| Ticker | Mentions | Dates | We stored it as | Yahoo's name |
|--------|---------:|-------|-----------------|--------------|
| `ELAN` | 2 | 2026-02-24 … 2026-06-02 | **Elanco** | Elanco Animal Health Incorporat |
| `DD` | 1 | 2026-02-06 | **DuPont** | DuPont de Nemours, Inc. |
| `FDS` | 1 | 2026-02-23 | **FactSet** | FactSet Research Systems Inc. |
| `PHM` | 1 | 2026-05-26 | **Pulte Homes** | PulteGroup, Inc. |
| `WOOF` | 1 | 2026-06-05 | **Petco** | Petco Health and Wellness Compa |


_Checked 810 tickers with a stored company name. Tickers Yahoo does not
recognise at all (hallucinated, private, OTC) are not listed here — see the
'Hallucinated tickers' note in CLAUDE.md._

_This list intentionally over-flags. A shared single word is not treated as a
match, so `Chipotle` vs `Chipotle Mexican Grill` appears even though it is fine —
the same rule is what keeps `Marriott Vacations Worldwide` from matching
`Marriott International`. Missing a real mis-ticker costs a corrupted price
history; a false positive costs one glance._
