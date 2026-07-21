# Ticker / Company Name Mismatches — Review Queue

**105 ticker(s)** hold a company that Yahoo Finance says belongs to a
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
| `CMG` | 9 | 2026-01-27 … 2026-06-29 | Chipotle Mexican Grill, Inc. | **Chipotle** |
| `BLK` | 8 | 2026-01-09 … 2026-07-15 | BlackRock, Inc. | **Blackstone** |
| `LUMN` | 8 | 2026-03-27 … 2026-05-01 | Lumen Technologies, Inc. | **Lumentum** |
| `MSTR` | 7 | 2026-01-05 … 2026-05-01 | Strategy Inc | **MicroStrategy** |
| `APO` | 3 | 2026-03-02 … 2026-03-17 | Apollo Global Management, Inc.  | **Apollo** |
| `CWEB` | 3 | 2026-04-10 … 2026-07-06 | Direxion Daily CSI China Intern | **Coreweave** |
| `RH` | 3 | 2026-03-23 … 2026-04-08 | RH | **RH (Restoration Hardware)** |
| `BTC` | 2 | 2026-03-02 … 2026-04-24 | Grayscale Bitcoin Mini Trust (B | **Bitcoin** |
| `BWX` | 2 | 2026-01-15 | State Street SPDR Bloomberg Int | **Babcock and Wilcox Enterprises** |
| `CSL` | 2 | 2026-01-27 … 2026-05-18 | Carlisle Companies Incorporated | **Comfort Systems USA** |
| `NXT` | 2 | 2026-02-04 … 2026-07-06 | Nextpower Inc. | **NextPower (formerly NextTracker)** |
| `OBNK` | 2 | 2026-01-15 … 2026-03-17 | Osprey Bonk Trust | **Origin Bancorp** |
| `ROAD` | 2 | 2026-05-05 … 2026-07-15 | Construction Partners, Inc. | **Sterling Infrastructure** |
| `SIZ` | 2 | 2026-03-19 … 2026-05-29 | AGFiQ U.S. Market Neutral Size  | **Signet Jewelers** |
| `SRE` | 2 | 2026-03-18 … 2026-03-20 | DBA Sempra | **Sempra Energy** |
| `VCX` | 2 | 2026-03-24 … 2026-07-08 | Fundrise Growth Tech Fund, LLC | **Fundrise Innovation Fund** |
| `ABR` | 1 | 2026-01-21 | Arbor Realty Trust | **Barrick Gold** |
| `ABX` | 1 | 2026-01-28 | Abacus Global Management, Inc. | **Barrick Gold** |
| `ACOM` | 1 | 2026-03-06 | Harbor Active Commodity ETF | **Acoma Holdings** |
| `AEIS` | 1 | 2026-03-05 | Advanced Energy Industries, Inc | **AEI Systems Corp** |
| `AHCO` | 1 | 2026-04-27 | AdaptHealth Corp. | **Acuity Electronics** |
| `ALB` | 1 | 2026-01-09 | Albemarle Corporation | **Albamaro** |
| `ARCX` | 1 | 2026-01-16 | Tradr 2X Long ACHR Daily ETF | **Ares Capital** |
| `ATEN` | 1 | 2026-05-05 | A10 Networks, Inc. | **Aten International** |
| `AUTR` | 1 | 2026-03-27 | Autris | **Auterion** |
| `AVX` | 1 | 2026-04-17 | Avax One Technology Ltd. | **Aeva Technologies** |
| `BCS` | 1 | 2026-01-16 | Barclays PLC | **Banco Santander** |
| `BCTX` | 1 | 2026-04-27 | BriaCell Therapeutics Corp. | **Billion to One** |
| `BDN` | 1 | 2026-03-03 | Brandywine Realty Trust | **Blue (implied Blackstone or similar; context suggests private credit entity)** |
| `BET` | 1 | 2026-03-26 | Bethpage Capital Corp | **Canadian Natural Resources** |
| `BFIN` | 1 | 2026-04-02 | BankFinancial Corporation | **Bread Financial** |
| `BGC` | 1 | 2026-04-06 | BGC Group, Inc. | **Cantor Fitzgerald / BGC Partners** |
| `BITO` | 1 | 2026-05-14 | ProShares Bitcoin ETF | **Billion to One** |
| `BNDS` | 1 | 2026-07-13 | Infrastructure Capital Bond Income ETF | **Bending Spoons** |
| `BOFI` | 1 | 2026-04-28 | AXOS FINL INC | **Bank of America** |
| `BSCI` | 1 | 2026-07-14 | Invesco BulletShares 2018 Corp Bd ETF | **Boston Scientific** |
| `BURL` | 1 | 2026-04-07 | Burlington Stores, Inc. | **Burlington Coat Factory** |
| `BXP` | 1 | 2026-03-25 | BXP, Inc. | **BXP (Boston Properties)** |
| `CBT` | 1 | 2026-03-27 | Cabot Corporation | **Cabot Brands (Cut Brands lighting)** |
| `CIRC` | 1 | 2026-02-04 | Circle8 Group, Inc. | **Circle Internet** |
| `CIX` | 1 | 2026-05-05 | CompX International Inc. | **Celestica** |
| `CMS` | 1 | 2026-03-20 | CMS Energy Corporation | **Columbia Banking System** |
| `CORN` | 1 | 2026-07-16 | Teucrium Corn Fund | **Corning** |
| `CRF` | 1 | 2026-04-10 | Cornerstone Total Return Fund, Inc. | **Carpenter Technology** |
| `CRVW` | 1 | 2026-05-01 | Careview Communications, Inc. | **CoreWeave** |
| `DD` | 1 | 2026-02-06 | DuPont de Nemours, Inc. | **DuPont** |
| `DTIL` | 1 | 2026-05-14 | Precision BioSciences, Inc. | **Design Therapeutics** |
| `EAGLE` | 1 | 2026-01-28 | Eagle Cement Corp | **Eagle Gold Mining** |
| `EQPT` | 1 | 2026-03-24 | EquipmentShare.com Inc | **Equipment Shares** |
| `EQST` | 1 | 2026-01-26 | Energy Quest, Inc | **Equipment Share** |
| `EXE` | 1 | 2026-03-26 | Expand Energy Corporation | **Sempra Energy** |
| `FDS` | 1 | 2026-02-23 | FactSet Research Systems Inc. | **FactSet** |
| `FG` | 1 | 2026-01-20 | F&G Annuities & Life, Inc. | **Figure Technologies** |
| `FWONK` | 1 | 2026-03-06 | Liberty Media Corporation - Ser | **Liberty Media Formula One** |
| `IMRX` | 1 | 2026-06-16 | Immuneering Corporation | **Immunity Bio** |
| `IMTX` | 1 | 2026-04-17 | Immatics N.V. | **Immunity Bio** |
| `INMB` | 1 | 2026-03-19 | INmune Bio Inc. | **ImmunityBio** |
| `INSP` | 1 | 2026-04-20 | Inspire Medical Systems, Inc. | **Inspiration Semiconductors** |
| `JLS` | 1 | 2026-04-02 | Nuveen Mortgage Opportunity Ter | **Janus Living** |
| `KD` | 1 | 2026-02-24 | Kyndryl Holdings, Inc. | **Kendrell** |
| `KGC` | 1 | 2026-03-27 | Kinross Gold Corporation | **Kagra** |
| `KLAR` | 1 | 2026-02-06 | Klarna Group plc | **Klär** |
| `KMG` | 1 | 2026-03-26 | KMG Chemicals, Inc. | **Kimcor** |
| `KRMN` | 1 | 2026-01-05 | Karman Holdings Inc. | **Karman Space & Defense** |
| `MDLM` | 1 | 2026-01-16 | MEDLEY MANAGEMENT INC | **Medline Industries** |
| `MIND` | 1 | 2026-04-20 | MIND Technology, Inc. | **Biphenium Therapeutics** |
| `NCL` | 1 | 2026-04-07 | Northann Corp. | **Norwegian Cruise Line** |
| `NRGV` | 1 | 2026-05-15 | Energy Vault Holdings, Inc. | **Energy Storage Company** |
| `NU` | 1 | 2026-01-23 | Nu Holdings Ltd. | **Nubank** |
| `NVR` | 1 | 2026-04-28 | NVR, Inc. | **Novo Nordisk** |
| `OLD` | 1 | 2026-01-26 | The Long-Term Care ETF | **Old Republic International** |
| `ONEG` | 1 | 2026-05-08 | OneConstruction Group Limited | **One Holding** |
| `ONSM` | 1 | 2026-04-20 | Onstream Media Corporation | **ON Semiconductor** |
| `ORGN` | 1 | 2026-04-28 | Origin Materials, Inc. | **Organon** |
| `PBR` | 1 | 2026-04-02 | Petroleo Brasileiro S.A. Petrob | **Polarcoin** |
| `PCG` | 1 | 2026-04-23 | Pacific Gas & Electric Co. | **PG&E Corporation** |
| `PDYN` | 1 | 2026-03-24 | Palladyne AI Corp. | **Paladin** |
| `PLC` | 1 | 2026-07-06 | Principal U.S. Large-Cap Multi-Factor ETF | **Power & Light Company** |
| `PRIM` | 1 | 2026-03-10 | Primoris Services Corporation | **Primiritives (infrastructure services play)** |
| `PSI` | 1 | 2026-06-01 | Invesco Semiconductors ETF | **Power Solutions International** |
| `QBTS` | 1 | 2026-06-01 | D-Wave Quantum Inc. | **D-Wave Systems** |
| `QTEC` | 1 | 2026-03-25 | First Trust NASDAQ-100-Technolo | **Quantee Electronics** |
| `QTUM` | 1 | 2026-06-04 | Defiance Quantum ETF | **Quantinium** |
| `RAL` | 1 | 2026-06-05 | Ralliant Corporation | **Reliant** |
| `RAN` | 1 | 2026-01-27 | RanMarine Technology B.V. | **Ramco Resources** |
| `RKUNY` | 1 | 2026-03-11 | Rakuten Group Inc. | **Recursion Pharmaceuticals** |
| `RSHN` | 1 | 2026-01-20 | RushNet, Inc. | **Rich Sparkle Holdings** |
| `SATL` | 1 | 2026-01-28 | Satellogic Inc. | **Satalogic Inc.** |
| `SDOT` | 1 | 2026-01-15 | Sadot Group Inc. | **SanDisk** |
| `SGHC` | 1 | 2026-04-13 | Super Group (SGHC) Limited | **Supergroup** |
| `SLS` | 1 | 2026-05-28 | SELLAS Life Sciences Group, Inc | **Selecta Biosciences** |
| `SPOT` | 1 | 2026-01-20 | Spotify Technology S.A. | **One Holding** |
| `SPRL` | 1 | 2026-05-12 | STRAT PETROLEUM LTD | **Spirail (exact company uncertain)** |
| `STG` | 1 | 2026-04-29 | Sunlands Technology Group | **Seagate Technology** |
| `SVCO` | 1 | 2026-03-05 | Silvaco Group, Inc. | **ServiceTitan** |
| `TEM` | 1 | 2026-02-06 | Tempus AI, Inc. | **Tempest AI** |
| `TMPO` | 1 | 2026-03-27 | Tempo Automation Holdings, Inc. | **Tempest AI** |
| `URG` | 1 | 2026-01-20 | Ur Energy Inc | **US Anamoney (United States Rare Earth & Critical Materials)** |
| `USA` | 1 | 2026-05-05 | Liberty All-Star Equity Fund | **USA Rare Earths** |
| `VDV` | 1 | 2026-03-27 | Vanguard Developed Markets ex-U | **Verdiv** |
| `VS` | 1 | 2026-03-11 | Versus Systems Inc. | **Victoria's Secret** |
| `WINN` | 1 | 2026-05-28 | Harbor Long-Term Growers ETF | **Wynn Resorts** |
| `XLE` | 1 | 2026-07-15 | State Street Energy Select Sector SPDR ETF | **X Energy** |
| `XPO` | 1 | 2026-04-27 | XPO, Inc. | **XPO Logistics (formerly TopBuild acquisition vehicle)** |

_Checked 822 tickers with a stored company name. Tickers Yahoo does not
recognise at all (hallucinated, private, OTC) are not listed here — see the
'Hallucinated tickers' note in CLAUDE.md._

_This list intentionally over-flags. A shared single word is not treated as a
match, so `Chipotle` vs `Chipotle Mexican Grill` appears even though it is fine —
the same rule is what keeps `Marriott Vacations Worldwide` from matching
`Marriott International`. Missing a real mis-ticker costs a corrupted price
history; a false positive costs one glance._
