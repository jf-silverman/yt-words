# Ticker / Company Name Mismatches — Review Queue

**54 ticker(s)** hold a company name that Yahoo Finance says belongs to
a different company. These are not all the same problem — some are wrong data,
most are a name we wrote informally — so they are split by **what can actually be
proved**, not by what they look like.

The test is the question in reverse: ignoring the symbol we filed it under, what
symbol does Yahoo return for the company name we stored? A different symbol back
means the call is sitting on the wrong company; the same symbol means our name is
merely informal.

That settles **5 of 54**. It cannot settle the other
**49**, because Yahoo's search only matches *current legal* names — it
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

The **Where** column links each mention to its spot in the episode (`date · segment · timestamp`) so you can confirm the call by ear. A timestamp that resolves to the episode start means that section has no timing on disk yet — the same fallback the unknown-ticker queue uses.

**Said? sym/name** is two hints: did the **symbol** and did the **company name** each appear in the episode(s) it was mentioned in — `yes` / `✗` / `—` (no transcript). Read together they suggest where a bad row came from: `✗ / yes` = symbol inferred from a spoken name; `yes / ✗` = symbol was said but the name looks invented; `✗ / ✗` = neither was said (a caption garble, like Sterling's "STRL" heard as "SPRL"). **Weak hints, not verdicts.** They misfire in both directions: a correct pick spoken only as its ticker shows `yes / ✗` (the caller said "GDRX", never "GoodRx"), and a garble that became the stored name shows a false `yes` ("AEVEX" mis-heard as "Aeva"). A short symbol can also match a common word. And a handful of early-2026 episodes have a stale transcript in the DB, so their answer is unreliable. Worth a glance, nothing more.


## 1. Likely mis-tickers — 0 ticker(s), the data is wrong

**This is the section that matters.** Yahoo maps our stored company name to a
*different* symbol than the one we filed the call under, so the call is most
likely attached to an unrelated company and has inherited its price history.
Every return, chart and backtest for both tickers is affected.

The suggested symbol is advisory — Yahoo's search picks the first US listing and
can be wrong, and the *company* half of the pair may be the mistaken one.
Confirm against the transcript before changing anything.

_None._


## 2. Undecidable without the transcript — 49 ticker(s)

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

| Ticker | We stored it as | Yahoo's name | Similar? | Said? sym/name | Where — date · segment · time |
|--------|-----------------|--------------|----------|----------------|-------------------------------|
| `BWX` | **Babcock and Wilcox Enterprises** | State Street SPDR Bloomberg Int | **no** | yes / yes | 2026-01-15 · — · [episode](https://youtu.be/-dnfldqfazA)<br>2026-01-15 · in_depth_analysis · [episode](https://youtu.be/-dnfldqfazA) |
| `ABX` | **Barrick Gold** | Abacus Global Management, Inc. | **no** | **✗** / yes | 2026-01-28 · opening_commentary · [episode](https://youtu.be/UxsosXoIT9E) |
| `ACOM` | **Acorn Realty Trust** | Harbor Active Commodity ETF | **no** | yes / yes | 2026-03-06 · lightning_round · [35:07](https://youtu.be/OLHPn2XxtzQ?t=2107) |
| `AHCO` | **Acuity Electronics** | AdaptHealth Corp. | **no** | **✗** / yes | 2026-04-27 · in_depth_analysis · [11:11](https://youtu.be/HhPaoUmAoJA?t=671) / [23:57](https://youtu.be/HhPaoUmAoJA?t=1437) / [26:04](https://youtu.be/HhPaoUmAoJA?t=1564) |
| `ATEN` | **Aten International** | A10 Networks, Inc. | **no** | **✗** / **✗** | 2026-05-05 · opening_commentary · [0:18](https://youtu.be/stBiW-NPi9E?t=18) |
| `BCTX` | **Billion to One** | BriaCell Therapeutics Corp. | **no** | **✗** / yes | 2026-04-27 · lightning_round · [33:04](https://youtu.be/HhPaoUmAoJA?t=1984) |
| `BITO` | **Billion to One** | ProShares Bitcoin ETF | **no** | **✗** / yes | 2026-05-14 · lightning_round · [36:07](https://youtu.be/WubZMiGRH-I?t=2167) |
| `BK` | **Bob Evans Farms** | Bank of New York Mellon Corp | **no** | **✗** / yes | 2026-06-23 · opening_commentary · [0:17](https://youtu.be/TW-oqAAfZDY?t=17) |
| `EQST` | **Equipment Share** | Energy Quest, Inc | **no** | **✗** / yes | 2026-01-26 · in_depth_analysis · [episode](https://youtu.be/NX6I2jJccas) |
| `FG` | **Figure Technologies** | F&G Annuities & Life, Inc. | **no** | **✗** / yes | 2026-01-20 · in_depth_analysis · [episode](https://youtu.be/tKgYSl5KSq0) |
| `IMRX` | **Immunity Bio** | Immuneering Corporation | **no** | **✗** / yes | 2026-06-16 · lightning_round · [36:38](https://youtu.be/2XCGYERvEzg?t=2198) |
| `IMTX` | **Immunity Bio** | Immatics N.V. | **no** | **✗** / yes | 2026-04-17 · lightning_round · [36:27](https://youtu.be/HYRppgkEDXc?t=2187) |
| `INSP` | **Inspira Technologies** | Inspire Medical Systems, Inc. | **no** | yes / **✗** | 2026-04-20 · lightning_round · [35:06](https://youtu.be/-kPm8LikEBI?t=2106) |
| `KD` | **Kendrell** | Kyndryl Holdings, Inc. | **no** | yes / **✗** | 2026-02-24 · lightning_round · [36:00](https://youtu.be/g09PyNhWRws?t=2160) |
| `KGC` | **Kagra** | Kinross Gold Corporation | **no** | **✗** / yes | 2026-03-27 · opening_commentary · [0:17](https://youtu.be/aK5g9aWVbWU?t=17) |
| `KMG` | **Kimcor** | KMG Chemicals, Inc. | **no** | **✗** / **✗** | 2026-03-26 · opening_commentary · [0:18](https://youtu.be/LPnGGW9Dm48?t=18) |
| `MDLM` | **Medline Industries** | MEDLEY MANAGEMENT INC | **no** | **✗** / yes | 2026-01-16 · lightning_round · [episode](https://youtu.be/3qf_h8DXLyY) |
| `NU` | **Nubank** | Nu Holdings Ltd. | **no** | **✗** / **✗** | 2026-01-23 · lightning_round · [episode](https://youtu.be/rzJfXrAjODY) |
| `PBR` | **Petrobras** | Petroleo Brasileiro S.A. Petrob | **no** | yes / **✗** | 2026-04-02 · lightning_round · [36:20](https://youtu.be/3nt_bL2oclU?t=2180) |
| `PCG` | **PG&E Corporation** | Pacific Gas & Electric Co. | **no** | yes / yes | 2026-04-23 · interview · [10:51](https://youtu.be/4AOW-E3MQLY?t=651) / [21:05](https://youtu.be/4AOW-E3MQLY?t=1265) / [28:54](https://youtu.be/4AOW-E3MQLY?t=1734) |
| `PDYN` | **Paladin** | Palladyne AI Corp. | **no** | yes / yes | 2026-03-24 · lightning_round · [36:15](https://youtu.be/WIdKqDtRhRg?t=2175) |
| `PLC` | **Power & Light Company** | Principal U.S. Large-Cap Multi-Factor ETF | **no** | yes / yes | 2026-07-06 · lightning_round · [36:30](https://youtu.be/UjZ1MYcw2OA?t=2190) |
| `RAN` | **Ramco Resources** | RanMarine Technology B.V. | **no** | yes / yes | 2026-01-27 · lightning_round · [episode](https://youtu.be/VqOMrFKSevs) |
| `SLS` | **Selecta Biosciences** | SELLAS Life Sciences Group, Inc | **no** | yes / **✗** | 2026-05-28 · lightning_round · [35:08](https://youtu.be/G_nPvcsM8LA?t=2108) |
| `THO` | **Tenneco (Thomas Oil)** | THOR Industries, Inc. | **no** | **✗** / yes | 2026-06-23 · opening_commentary · [0:17](https://youtu.be/TW-oqAAfZDY?t=17) |
| `TMPO` | **Tempest AI** | Tempo Automation Holdings, Inc. | **no** | **✗** / yes | 2026-03-27 · lightning_round · [35:00](https://youtu.be/aK5g9aWVbWU?t=2100) |
| `VDV` | **Verdiv** | Vanguard Developed Markets ex-U | **no** | **✗** / **✗** | 2026-03-27 · lightning_round · [35:00](https://youtu.be/aK5g9aWVbWU?t=2100) |
| `PAYX` | **Paychecks** | Paychex, Inc. | ~ | **✗** / yes | 2026-03-25 · interview · [14:50](https://youtu.be/V9apPO6VXII?t=890) / [45:30](https://youtu.be/V9apPO6VXII?t=2730)<br>2026-03-26 · macro_morass_analysis · [episode](https://youtu.be/LPnGGW9Dm48)<br>2026-03-30 · opening_commentary · [0:17](https://youtu.be/HZv54NYleAs?t=17)<br>2026-06-30 · interview · [16:19](https://youtu.be/FIMYXMYOpzg?t=979) / [36:48](https://youtu.be/FIMYXMYOpzg?t=2208) |
| `SNAP` | **Snapchat** | Snap Inc. | ~ | yes / yes | 2026-04-01 · opening_commentary · [0:17](https://youtu.be/6dJehtsavKU?t=17)<br>2026-04-28 · lightning_round · [35:35](https://youtu.be/Lgj13qHO9bE?t=2135)<br>2026-06-16 · opening_commentary · [0:17](https://youtu.be/2XCGYERvEzg?t=17) |
| `BTC` | **Bitcoin** | Grayscale Bitcoin Mini Trust (B | ~ | **✗** / yes | 2026-03-02 · closing_commentary · [40:25](https://youtu.be/FiJ8qLa09no?t=2425)<br>2026-04-24 · lightning_round · [37:08](https://youtu.be/i3xD9jEIuDg?t=2228) |
| `HBAN` | **Huntington Bancorp** | Huntington Bancshares Incorpora | ~ | **✗** / yes | 2026-01-16 · lightning_round · [episode](https://youtu.be/3qf_h8DXLyY)<br>2026-04-10 · am_i_diversified · [episode](https://youtu.be/6tmhL98Xa1g) |
| `UAMY` | **U.S. Antimony Corporation** | United States Antimony Corporation | ~ | yes / **✗** | 2026-01-20 · in_depth_analysis · [episode](https://youtu.be/tKgYSl5KSq0)<br>2026-03-12 · lightning_round · [35:12](https://youtu.be/MsK1NxlzwvY?t=2112) |
| `VCX` | **Fundrise Innovation Fund** | Fundrise Growth Tech Fund, LLC | ~ | yes / yes | 2026-03-24 · in_depth_analysis · [31:10](https://youtu.be/WIdKqDtRhRg?t=1870)<br>2026-07-08 · in_depth_analysis · [11:21](https://youtu.be/k1DEekxlGG4?t=681) / [19:20](https://youtu.be/k1DEekxlGG4?t=1160) |
| `AEIS` | **Array Electronic Industries (Ametek/AEI Systems)** | Advanced Energy Industries, Inc | ~ | yes / yes | 2026-03-05 · lightning_round · [29:00](https://youtu.be/5dAxKTZ3sIA?t=1740) |
| `AUTR` | **Auterion** | Autris | ~ | **✗** / **✗** | 2026-03-27 · investing_club_meeting · [episode](https://youtu.be/aK5g9aWVbWU) |
| `BURL` | **Burlington Coat Factory** | Burlington Stores, Inc. | ~ | **✗** / yes | 2026-04-07 · opening_commentary · [0:01](https://youtu.be/8at2Eyt89RQ?t=1) |
| `DECK` | **Deckers Brands** | Deckers Outdoor Corporation | ~ | **✗** / yes | 2026-01-05 · in_depth_analysis · [29:31](https://youtu.be/k4bEI8CxAgQ?t=1771) |
| `EAGLE` | **Eagle Gold Mining** | Eagle Cement Corp | ~ | yes / yes | 2026-01-28 · opening_commentary · [episode](https://youtu.be/UxsosXoIT9E) |
| `EQPT` | **Equipment Shares** | EquipmentShare.com Inc | ~ | **✗** / yes | 2026-03-24 · lightning_round · [36:15](https://youtu.be/WIdKqDtRhRg?t=2175) |
| `FWONK` | **Liberty Media Formula One** | Liberty Media Corporation - Ser | ~ | yes / yes | 2026-03-06 · in_depth_analysis · [17:27](https://youtu.be/OLHPn2XxtzQ?t=1047) / [28:14](https://youtu.be/OLHPn2XxtzQ?t=1694) |
| `KRMN` | **Karman Space & Defense** | Karman Holdings Inc. | ~ | **✗** / yes | 2026-01-05 · lightning_round · [36:40](https://youtu.be/k4bEI8CxAgQ?t=2200) |
| `NRGV` | **Energy Storage Company** | Energy Vault Holdings, Inc. | ~ | yes / yes | 2026-05-15 · lightning_round · [36:39](https://youtu.be/JIQheuNzaAI?t=2199) |
| `PRIM` | **Primary Energy Holdings (infrastructure services)** | Primoris Services Corporation | ~ | **✗** / yes | 2026-03-10 · lightning_round · [36:00](https://youtu.be/SA2ZUqpSEss?t=2160) |
| `QBTS` | **D-Wave Systems** | D-Wave Quantum Inc. | ~ | **✗** / yes | 2026-06-01 · lightning_round · [36:24](https://youtu.be/oHrBBaAh4Jc?t=2184) |
| `RAL` | **Reliant** | Ralliant Corporation | ~ | yes / yes | 2026-06-05 · lightning_round · [36:00](https://youtu.be/LDtdnZddg-k?t=2160) |
| `SATL` | **Satalogic Inc.** | Satellogic Inc. | ~ | yes / yes | 2026-01-28 · lightning_round · [episode](https://youtu.be/UxsosXoIT9E) |
| `SGHC` | **Supergroup** | Super Group (SGHC) Limited | ~ | yes / yes | 2026-04-13 · interview · [29:50](https://youtu.be/ZJNO3IbjSDg?t=1790) |
| `TEM` | **Tempest AI** | Tempus AI, Inc. | ~ | yes / yes | 2026-02-06 · opening_commentary · [0:03](https://youtu.be/xpEBYrOyHPE?t=3) |
| `TKR` | **Timkin** | Timken Company (The) | ~ | yes / yes | 2026-06-04 · interview · [10:28](https://youtu.be/2KJ4PtpX3Wk?t=628) / [29:00](https://youtu.be/2KJ4PtpX3Wk?t=1740) |


## 3. Name variants — 5 ticker(s), cosmetic only

Yahoo maps our stored name back to the *same* symbol, so the ticker is correct
and no price history is affected. Our name is just informal ("Snapchat"),
shortened ("Petco"), dated ("Burlington Coat Factory"), or a caption
misspelling. Safe to leave alone; fix only if the wording bothers you on the
site. For a genuine rename, prefer `New Name (formerly Old Name)` — see the
renamed-companies note in CLAUDE.md.

| Ticker | We stored it as | Yahoo's name | Said? sym/name | Where — date · segment · time |
|--------|-----------------|--------------|----------------|-------------------------------|
| `ELAN` | **Elanco** | Elanco Animal Health Incorporat | **✗** / yes | 2026-02-24 · interview · [27:00](https://youtu.be/g09PyNhWRws?t=1620)<br>2026-06-02 · lightning_round · [36:57](https://youtu.be/dVzjXBscDRc?t=2217) |
| `DD` | **DuPont** | DuPont de Nemours, Inc. | **✗** / yes | 2026-02-06 · opening_commentary · [0:03](https://youtu.be/xpEBYrOyHPE?t=3) |
| `FDS` | **FactSet** | FactSet Research Systems Inc. | **✗** / yes | 2026-02-23 · in_depth_analysis · [episode](https://youtu.be/Ij0nyL7Z2vc) |
| `PHM` | **Pulte Homes** | PulteGroup, Inc. | **✗** / yes | 2026-05-26 · lightning_round · [35:46](https://youtu.be/UBZvilR6Zuo?t=2146) |
| `WOOF` | **Petco** | Petco Health and Wellness Compa | yes / yes | 2026-06-05 · opening_commentary · [0:17](https://youtu.be/LDtdnZddg-k?t=17) |


_Checked 807 tickers with a stored company name. Tickers Yahoo does not
recognise at all (hallucinated, private, OTC) are not listed here — see the
'Hallucinated tickers' note in CLAUDE.md._

_This list intentionally over-flags. A shared single word is not treated as a
match, so `Chipotle` vs `Chipotle Mexican Grill` appears even though it is fine —
the same rule is what keeps `Marriott Vacations Worldwide` from matching
`Marriott International`. Missing a real mis-ticker costs a corrupted price
history; a false positive costs one glance._
