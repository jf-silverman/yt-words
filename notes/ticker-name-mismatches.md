# Ticker / Company Name Mismatches — Review Queue

**71 ticker(s)** hold a company that Yahoo Finance says belongs to a
*different* company. Each is a likely mis-ticker: the call is probably about the
company in the last column, filed under the wrong symbol — where it silently
inherits that symbol's real price history.

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

| Ticker | Mentions | Dates | Yahoo says the symbol is | We stored it as |
|--------|---------:|-------|--------------------------|-----------------|
| `MSTR` | 7 | 2026-01-05 … 2026-05-01 | Strategy Inc | **MicroStrategy** |
| `ABT` | 6 | 2026-01-16 … 2026-06-18 | Abbott Laboratories | **Abbott Labs** |
| `PAYX` | 4 | 2026-03-25 … 2026-06-30 | Paychex, Inc. | **Paychecks** |
| `RH` | 3 | 2026-03-23 … 2026-04-08 | RH | **RH (Restoration Hardware)** |
| `SNAP` | 3 | 2026-04-01 … 2026-06-16 | Snap Inc. | **Snapchat** |
| `BTC` | 2 | 2026-03-02 … 2026-04-24 | Grayscale Bitcoin Mini Trust (B | **Bitcoin** |
| `BWX` | 2 | 2026-01-15 | State Street SPDR Bloomberg Int | **Babcock and Wilcox Enterprises** |
| `ELAN` | 2 | 2026-02-24 … 2026-06-02 | Elanco Animal Health Incorporat | **Elanco** |
| `HBAN` | 2 | 2026-01-16 … 2026-04-10 | Huntington Bancshares Incorpora | **Huntington Bancorp** |
| `VCX` | 2 | 2026-03-24 … 2026-07-08 | Fundrise Growth Tech Fund, LLC | **Fundrise Innovation Fund** |
| `ABX` | 1 | 2026-01-28 | Abacus Global Management, Inc. | **Barrick Gold** |
| `ACOM` | 1 | 2026-03-06 | Harbor Active Commodity ETF | **Acorn Realty Trust** |
| `AEIS` | 1 | 2026-03-05 | Advanced Energy Industries, Inc | **Array Electronic Industries (Ametek/AEI Systems)** |
| `AHCO` | 1 | 2026-04-27 | AdaptHealth Corp. | **Acuity Electronics** |
| `ATEN` | 1 | 2026-05-05 | A10 Networks, Inc. | **Aten International** |
| `AUTR` | 1 | 2026-03-27 | Autris | **Auterion** |
| `AVX` | 1 | 2026-04-17 | Avax One Technology Ltd. | **Aeva Technologies** |
| `AX` | 1 | 2026-07-21 | Axos Financial, Inc. | **Axiom (Defense Technology)** |
| `BCTX` | 1 | 2026-04-27 | BriaCell Therapeutics Corp. | **Billion to One** |
| `BDN` | 1 | 2026-03-03 | Brandywine Realty Trust | **Blue (implied Blackstone or similar; context suggests private credit entity)** |
| `BITO` | 1 | 2026-05-14 | ProShares Bitcoin ETF | **Billion to One** |
| `BK` | 1 | 2026-06-23 | Bank of New York Mellon Corp | **Bob Evans Farms** |
| `BNAI` | 1 | 2026-03-06 | Brand Engagement Network Inc. | **Brand Engagement (formerly known)** |
| `BURL` | 1 | 2026-04-07 | Burlington Stores, Inc. | **Burlington Coat Factory** |
| `BXP` | 1 | 2026-03-25 | BXP, Inc. | **BXP (Boston Properties)** |
| `CBT` | 1 | 2026-03-27 | Cabot Corporation | **Cabot Brands (Cut Brands lighting)** |
| `CPK` | 1 | 2026-03-12 | Chesapeake Utilities Corporation | **Campbell Soup Company** |
| `DD` | 1 | 2026-02-06 | DuPont de Nemours, Inc. | **DuPont** |
| `DECK` | 1 | 2026-01-05 | Deckers Outdoor Corporation | **Deckers Brands** |
| `EAGLE` | 1 | 2026-01-28 | Eagle Cement Corp | **Eagle Gold Mining** |
| `EQPT` | 1 | 2026-03-24 | EquipmentShare.com Inc | **Equipment Shares** |
| `EQST` | 1 | 2026-01-26 | Energy Quest, Inc | **Equipment Share** |
| `FDS` | 1 | 2026-02-23 | FactSet Research Systems Inc. | **FactSet** |
| `FG` | 1 | 2026-01-20 | F&G Annuities & Life, Inc. | **Figure Technologies** |
| `FWONK` | 1 | 2026-03-06 | Liberty Media Corporation - Ser | **Liberty Media Formula One** |
| `IMRX` | 1 | 2026-06-16 | Immuneering Corporation | **Immunity Bio** |
| `IMTX` | 1 | 2026-04-17 | Immatics N.V. | **Immunity Bio** |
| `INSP` | 1 | 2026-04-20 | Inspire Medical Systems, Inc. | **Inspira Technologies** |
| `KD` | 1 | 2026-02-24 | Kyndryl Holdings, Inc. | **Kendrell** |
| `KGC` | 1 | 2026-03-27 | Kinross Gold Corporation | **Kagra** |
| `KMG` | 1 | 2026-03-26 | KMG Chemicals, Inc. | **Kimcor** |
| `KRMN` | 1 | 2026-01-05 | Karman Holdings Inc. | **Karman Space & Defense** |
| `MDLM` | 1 | 2026-01-16 | MEDLEY MANAGEMENT INC | **Medline Industries** |
| `MIND` | 1 | 2026-04-20 | MIND Technology, Inc. | **Biphenium Therapeutics** |
| `NRGV` | 1 | 2026-05-15 | Energy Vault Holdings, Inc. | **Energy Storage Company** |
| `NU` | 1 | 2026-01-23 | Nu Holdings Ltd. | **Nubank** |
| `PBR` | 1 | 2026-04-02 | Petroleo Brasileiro S.A. Petrob | **Polarcoin Beverage / Polar Bear (PBR stock ticker context unclear)** |
| `PCG` | 1 | 2026-04-23 | Pacific Gas & Electric Co. | **PG&E Corporation** |
| `PDYN` | 1 | 2026-03-24 | Palladyne AI Corp. | **Paladin** |
| `PHM` | 1 | 2026-05-26 | PulteGroup, Inc. | **Pulte Homes** |
| `PLC` | 1 | 2026-07-06 | Principal U.S. Large-Cap Multi-Factor ETF | **Power & Light Company** |
| `PRIM` | 1 | 2026-03-10 | Primoris Services Corporation | **Primary Energy Holdings (infrastructure services)** |
| `QBTS` | 1 | 2026-06-01 | D-Wave Quantum Inc. | **D-Wave Systems** |
| `QTEC` | 1 | 2026-03-25 | First Trust NASDAQ-100-Technolo | **Quantee Electronics** |
| `QTUM` | 1 | 2026-06-04 | Defiance Quantum ETF | **Quantinium** |
| `RAL` | 1 | 2026-06-05 | Ralliant Corporation | **Reliant** |
| `RAN` | 1 | 2026-01-27 | RanMarine Technology B.V. | **Ramco Resources** |
| `SATL` | 1 | 2026-01-28 | Satellogic Inc. | **Satalogic Inc.** |
| `SGHC` | 1 | 2026-04-13 | Super Group (SGHC) Limited | **Supergroup** |
| `SLS` | 1 | 2026-05-28 | SELLAS Life Sciences Group, Inc | **Selecta Biosciences** |
| `SPRL` | 1 | 2026-05-12 | STRAT PETROLEUM LTD | **Unknown (SPRL)** |
| `TEM` | 1 | 2026-02-06 | Tempus AI, Inc. | **Tempest AI** |
| `THO` | 1 | 2026-06-23 | THOR Industries, Inc. | **Tenneco (Thomas Oil)** |
| `TKR` | 1 | 2026-06-04 | Timken Company (The) | **Timkin** |
| `TMPO` | 1 | 2026-03-27 | Tempo Automation Holdings, Inc. | **Tempest AI** |
| `UAMY` | 1 | 2026-03-12 | United States Antimony Corporation | **U.S. Antimony Corporation** |
| `URG` | 1 | 2026-01-20 | Ur Energy Inc | **US Anamoney (United States Rare Earth & Critical Materials)** |
| `USA` | 1 | 2026-05-05 | Liberty All-Star Equity Fund | **USA Rare Earth** |
| `VDV` | 1 | 2026-03-27 | Vanguard Developed Markets ex-U | **Verdiv** |
| `WOOF` | 1 | 2026-06-05 | Petco Health and Wellness Compa | **Petco** |
| `XPO` | 1 | 2026-04-27 | XPO, Inc. | **XPO Logistics (formerly TopBuild acquisition vehicle)** |

_Checked 810 tickers with a stored company name. Tickers Yahoo does not
recognise at all (hallucinated, private, OTC) are not listed here — see the
'Hallucinated tickers' note in CLAUDE.md._

_This list intentionally over-flags. A shared single word is not treated as a
match, so `Chipotle` vs `Chipotle Mexican Grill` appears even though it is fine —
the same rule is what keeps `Marriott Vacations Worldwide` from matching
`Marriott International`. Missing a real mis-ticker costs a corrupted price
history; a false positive costs one glance._
