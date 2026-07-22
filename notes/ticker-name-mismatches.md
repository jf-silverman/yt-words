# Ticker / Company Name Mismatches — Review Queue

**78 ticker(s)** hold a company that Yahoo Finance says belongs to a
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
| `SNDK` | 30 | 2026-01-05 … 2026-07-16 | Sandisk Corporation | **SanDisk (Western Digital subsidiary)** |
| `RTX` | 10 | 2026-01-20 … 2026-07-16 | RTX Corporation | **Raytheon Technologies** |
| `CMG` | 9 | 2026-01-27 … 2026-06-29 | Chipotle Mexican Grill, Inc. | **Chipotle** |
| `MSTR` | 7 | 2026-01-05 … 2026-05-01 | Strategy Inc | **MicroStrategy** |
| `SLB` | 5 | 2026-01-05 … 2026-06-17 | SLB Limited | **Schlumberger** |
| `APO` | 3 | 2026-03-02 … 2026-03-17 | Apollo Global Management, Inc.  | **Apollo** |
| `CDNS` | 3 | 2026-02-23 … 2026-05-29 | Cadence Design Systems, Inc. | **CoreWeave** |
| `RH` | 3 | 2026-03-23 … 2026-04-08 | RH | **Restoration Hardware** |
| `BTC` | 2 | 2026-03-02 … 2026-04-24 | Grayscale Bitcoin Mini Trust (B | **Bitcoin** |
| `BWX` | 2 | 2026-01-15 | State Street SPDR Bloomberg Int | **Babcock and Wilcox Enterprises** |
| `NXT` | 2 | 2026-02-04 … 2026-07-06 | Nextpower Inc. | **NextPower (formerly NextTracker)** |
| `SIRI` | 2 | 2026-01-13 … 2026-01-20 | SiriusXM Holdings Inc. | **Space Mobile** |
| `SLV` | 2 | 2026-01-23 … 2026-01-27 | iShares Silver Trust | **Silver (via ETF proxy)** |
| `SRE` | 2 | 2026-03-18 … 2026-03-20 | DBA Sempra | **Sempra Energy** |
| `SY` | 2 | 2026-01-30 | So-Young International Inc. - A | **Sysco (food distributor)** |
| `VCX` | 2 | 2026-03-24 … 2026-07-08 | Fundrise Growth Tech Fund, LLC | **Fundrise Innovation Fund** |
| `VIAV` | 2 | 2026-03-05 … 2026-03-23 | Viavi Solutions Inc. | **Viavi Systems** |
| `ABX` | 1 | 2026-01-28 | Abacus Global Management, Inc. | **Barrick Gold** |
| `ACM` | 1 | 2026-04-01 | AECOM | **Acuity Electronics** |
| `ACOM` | 1 | 2026-03-06 | Harbor Active Commodity ETF | **Acoma Holdings** |
| `AEIS` | 1 | 2026-03-05 | Advanced Energy Industries, Inc | **AEI Systems Corp** |
| `AHCO` | 1 | 2026-04-27 | AdaptHealth Corp. | **Acuity Electronics** |
| `ALB` | 1 | 2026-01-09 | Albemarle Corporation | **Albamaro** |
| `ATEN` | 1 | 2026-05-05 | A10 Networks, Inc. | **Aten International** |
| `AUTR` | 1 | 2026-03-27 | Autris | **Auterion** |
| `AVX` | 1 | 2026-04-17 | Avax One Technology Ltd. | **Aeva Technologies** |
| `AX` | 1 | 2026-07-21 | Axos Financial, Inc. | **Axiom (Defense Technology)** |
| `BCTX` | 1 | 2026-04-27 | BriaCell Therapeutics Corp. | **Billion to One** |
| `BDN` | 1 | 2026-03-03 | Brandywine Realty Trust | **Blue (implied Blackstone or similar; context suggests private credit entity)** |
| `BGC` | 1 | 2026-04-06 | BGC Group, Inc. | **Cantor Fitzgerald / BGC Partners** |
| `BITO` | 1 | 2026-05-14 | ProShares Bitcoin ETF | **Billion to One** |
| `BP` | 1 | 2026-04-06 | BP p.l.c. | **British Petroleum** |
| `BURL` | 1 | 2026-04-07 | Burlington Stores, Inc. | **Burlington Coat Factory** |
| `BXP` | 1 | 2026-03-25 | BXP, Inc. | **Boston Properties** |
| `CBT` | 1 | 2026-03-27 | Cabot Corporation | **Cabot Brands (Cut Brands lighting)** |
| `DD` | 1 | 2026-02-06 | DuPont de Nemours, Inc. | **DuPont** |
| `EAGLE` | 1 | 2026-01-28 | Eagle Cement Corp | **Eagle Gold Mining** |
| `EQPT` | 1 | 2026-03-24 | EquipmentShare.com Inc | **Equipment Shares** |
| `EQST` | 1 | 2026-01-26 | Energy Quest, Inc | **Equipment Share** |
| `EZPW` | 1 | 2026-02-23 | EZCORP, Inc. | **EZPW (pawn/credit)** |
| `FDS` | 1 | 2026-02-23 | FactSet Research Systems Inc. | **FactSet** |
| `FG` | 1 | 2026-01-20 | F&G Annuities & Life, Inc. | **Figure Technologies** |
| `FWONK` | 1 | 2026-03-06 | Liberty Media Corporation - Ser | **Liberty Formula One** |
| `IMRX` | 1 | 2026-06-16 | Immuneering Corporation | **Immunity Bio** |
| `IMTX` | 1 | 2026-04-17 | Immatics N.V. | **Immunity Bio** |
| `INSP` | 1 | 2026-04-20 | Inspire Medical Systems, Inc. | **Inspiration Semiconductors** |
| `KD` | 1 | 2026-02-24 | Kyndryl Holdings, Inc. | **Kindred Biosciences** |
| `KGC` | 1 | 2026-03-27 | Kinross Gold Corporation | **Kagra** |
| `KMG` | 1 | 2026-03-26 | KMG Chemicals, Inc. | **Kimcor** |
| `KRMN` | 1 | 2026-01-05 | Karman Holdings Inc. | **Karman Space & Defense** |
| `MDLM` | 1 | 2026-01-16 | MEDLEY MANAGEMENT INC | **Medline Industries** |
| `MIND` | 1 | 2026-04-20 | MIND Technology, Inc. | **Biphenium Therapeutics** |
| `NRGV` | 1 | 2026-05-15 | Energy Vault Holdings, Inc. | **NRG Energy (gravity storage variant or similar)** |
| `NU` | 1 | 2026-01-23 | Nu Holdings Ltd. | **Nubank** |
| `OLMA` | 1 | 2026-03-20 | Olema Pharmaceuticals, Inc. | **Olema Oncology** |
| `PBR` | 1 | 2026-04-02 | Petroleo Brasileiro S.A. Petrob | **Polarcoin** |
| `PCG` | 1 | 2026-04-23 | Pacific Gas & Electric Co. | **PG&E** |
| `PDYN` | 1 | 2026-03-24 | Palladyne AI Corp. | **Paladin** |
| `PLC` | 1 | 2026-07-06 | Principal U.S. Large-Cap Multi-Factor ETF | **Power & Light Company** |
| `PRIM` | 1 | 2026-03-10 | Primoris Services Corporation | **Primiritives (infrastructure services play)** |
| `QBTS` | 1 | 2026-06-01 | D-Wave Quantum Inc. | **D-Wave Systems** |
| `QTEC` | 1 | 2026-03-25 | First Trust NASDAQ-100-Technolo | **Quantee Electronics** |
| `QTUM` | 1 | 2026-06-04 | Defiance Quantum ETF | **Quantinium** |
| `QXO` | 1 | 2026-05-28 | QXO, Inc. | **Quotient Technology** |
| `RAL` | 1 | 2026-06-05 | Ralliant Corporation | **Reliant** |
| `RAN` | 1 | 2026-01-27 | RanMarine Technology B.V. | **Ramco Resources** |
| `SATL` | 1 | 2026-01-28 | Satellogic Inc. | **Satalogic Inc.** |
| `SGHC` | 1 | 2026-04-13 | Super Group (SGHC) Limited | **Supergroup** |
| `SLS` | 1 | 2026-05-28 | SELLAS Life Sciences Group, Inc | **Singular Genomics Systems** |
| `SPRL` | 1 | 2026-05-12 | STRAT PETROLEUM LTD | **Spirail (exact company uncertain)** |
| `TEM` | 1 | 2026-02-06 | Tempus AI, Inc. | **Tempest AI** |
| `TMPO` | 1 | 2026-03-27 | Tempo Automation Holdings, Inc. | **Tempest AI** |
| `URG` | 1 | 2026-01-20 | Ur Energy Inc | **US Anamoney (United States Rare Earth & Critical Materials)** |
| `USA` | 1 | 2026-05-05 | Liberty All-Star Equity Fund | **USA Rare Earths** |
| `VDV` | 1 | 2026-03-27 | Vanguard Developed Markets ex-U | **Verdiv** |
| `VRTX` | 1 | 2026-04-17 | Vertex Pharmaceuticals Incorpor | **Vertex Energy** |
| `XPO` | 1 | 2026-04-27 | XPO, Inc. | **XPO Logistics (formerly TopBuild acquisition vehicle)** |
| `XRAY` | 1 | 2026-01-05 | DENTSPLY SIRONA Inc. | **Densify** |

_Checked 805 tickers with a stored company name. Tickers Yahoo does not
recognise at all (hallucinated, private, OTC) are not listed here — see the
'Hallucinated tickers' note in CLAUDE.md._

_This list intentionally over-flags. A shared single word is not treated as a
match, so `Chipotle` vs `Chipotle Mexican Grill` appears even though it is fine —
the same rule is what keeps `Marriott Vacations Worldwide` from matching
`Marriott International`. Missing a real mis-ticker costs a corrupted price
history; a false positive costs one glance._
