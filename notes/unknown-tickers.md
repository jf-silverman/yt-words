# Unknown Tickers — Manual Review Queue

**23 mention(s)** are stored under a placeholder ticker (`????` / `???`) — Haiku heard a company but could not identify its symbol. These are excluded from the website until they are resolved.

> **Generated file — do not edit by hand.**
>
> ```bash
> python3 code/pipeline.py --list-unknown-tickers
> ```
>
> This is **manual — the nightly pipeline does not run it**, so this file does not
> update itself as new episodes land. Re-run the command to pick up new placeholders
> (and to drop rows you have already resolved).

Each row needs someone to open the episode at the timestamp and identify the
company. Once you know it:

```bash
sqlite3 data/mad_money.db \
  "UPDATE mentions SET ticker='CORRECT' WHERE ticker='????' AND date='YYYY-MM-DD' AND segment='SEGMENT';"
python3 code/pipeline.py --backfill-prices --tickers CORRECT
python3 code/pipeline.py --rebuild-shards
```

Re-run the generator afterwards and the row disappears on its own.

| Date | Placeholder | Segment | Time | Call | Cramer's description | Episode |
|------|-------------|---------|------|------|----------------------|---------|
| 2026-01-05 | `????` | lightning_round | 36:40 | caution_concern | Fine to speculate given ties to former Seattle Genetics leadership, but Cramer stresses this is speculation, not investing, given the cash burn. | [watch](https://youtu.be/k4bEI8CxAgQ?t=2200) |
| 2026-01-09 | `????` | lightning_round | 34:54 | wait_hold_neutral | Cramer congratulated the caller on the gain, describing the position as effectively resolved via the acquisition bid. | [watch](https://youtu.be/Ctwl6H8f9o8?t=2094) |
| 2026-02-02 | `????` | lightning_round | 36:03 | buy | Cramer and Ben covered and felt really good about it; glad they were right; pretty amazing; outstanding positive marks. | [watch](https://youtu.be/nNcDqZ2zTvI?t=2163) |
| 2026-03-17 | `????` | interview | 7:30 / 31:42 / 39:07 | buy | Private (valuation $13.7B as of Sept 2025); Nemotron coalition partner with Nvidia on open-weight models; Forge customization product targets fintech and industrial data; sovereign AI play with differentiation vs. closed LLMs. | [Interview: Nvidia (NVDA)](https://youtu.be/5l7fzwpaiiQ?t=450) · [Interview: Vertiv (VRT)](https://youtu.be/5l7fzwpaiiQ?t=1902) · [Interview: Mistral AI](https://youtu.be/5l7fzwpaiiQ?t=2347) |
| 2026-03-18 | `????` | interview | 14:50 / 45:00 | wait_hold_neutral | Private company; $400M+ revenue, 10x YoY growth, will cross $1B in 2026; open-weight model approach breaking AI concentration; Cramer would buy on IPO but not yet public. | [Interview: Sempra (SRE)](https://youtu.be/pq8Mr9n9EAw?t=890) · [Interview: Mistral AI](https://youtu.be/pq8Mr9n9EAw?t=2700) |
| 2026-03-24 | `????` | in_depth_analysis | 31:10 | buy | Data infrastructure company; 22% of Fundrise Fund portfolio; only exciting holding in Robinhood Ventures Fund (7 stocks); Cramer calls it 'truly exciting'; Fundrise got in 2023 at lower valuation, Robinhood late 2025. | [watch](https://youtu.be/WIdKqDtRhRg?t=1870) |
| 2026-03-24 | `????` | lightning_round | 36:15 | buy | Caller Steve bought at $75 beginning of year, now at $45, down $30/share, asking whether to cut losses. Cramer says no; checked delinquencies (very low); calls it 'rocket ship'; down 40% doesn't make sense; backlog strong, good operator. | [watch](https://youtu.be/WIdKqDtRhRg?t=2175) |
| 2026-03-30 | `????` | lightning_round | 36:27 | mild_buy | Tungsten mining; supply constraints support price; can go higher on pullback; okay entry point for speculators. | [watch](https://youtu.be/HZv54NYleAs?t=2187) |
| 2026-05-15 | `????` | lightning_round | 36:39 | sell_avoid | Medical device sector unpopular in current market; no attractive opportunities even among quality peers like Medtronic, Intuitive Surgical, Boston Scientific. | [watch](https://youtu.be/JIQheuNzaAI?t=2199) |
| 2026-05-18 | `????` | lightning_round | 40:37 | buy | Infrastructure play serving power industry; fairly new IPO (caller Ron, CA). Revenue +66% YoY, gross profit doubled, backlog $88M up 2x. Cramer: 'Great niche company, I salute you.' Buy. | [watch](https://youtu.be/6dOjtUMJmt8?t=2437) |
| 2026-05-18 | `????` | opening_commentary | 0:17 | sell_avoid | Blasted by failed metastatic melanoma cancer trial. Can't buy drug stock that drops hard on day 1 of decline. Stock damaged; downgrades likely coming. | [watch](https://youtu.be/6dOjtUMJmt8?t=17) |
| 2026-05-20 | `????` | interview | 12:25 / 20:41 | buy | Free cash flow positive AI data platform; Genie ontology solves enterprise AI context problem; $134B private valuation; staying private through 2026 to build; company you really want. | [Interview: V.F. Corp (VF)](https://youtu.be/BprK8UuV8uk?t=745) · [Interview: Databricks](https://youtu.be/BprK8UuV8uk?t=1241) |
| 2026-05-20 | `????` | lightning_round | 37:43 | wait_hold_neutral | Manufacturing company with third consecutive quarter accelerating growth; Siemens partnership (bought $50M stake); Cramer says growing like a weed but doesn't know them well enough to opine; invites CEO on show. | [watch](https://youtu.be/BprK8UuV8uk?t=2263) |
| 2026-05-26 | `????` | interview_abridge | — | mild_buy | Medical AI platform reduces clinician administrative burden (30+ hours/week), improving patient empathy and outcomes; live across 300+ health systems reaching 100M+ patients; Jensen Huang (Nvidia) backing; terrific advancement in healthcare AI efficiency. | [episode](https://youtu.be/UBZvilR6Zuo) |
| 2026-05-26 | `????` | lightning_round | 35:46 | wait_hold | Recently de-SPAC'd company that profitably operates; Cramer blesses speculation but concerned about late-cycle entry; recommend waiting for pullback. | [watch](https://youtu.be/UBZvilR6Zuo?t=2146) |
| 2026-05-28 | `????` | lightning_round | 35:08 | wait_hold_neutral | Crypto-related investment; Cramer bullish on crypto broadly but prefers Bitcoin; doesn't recommend doubling down on losing position—switch to Bitcoin. | [watch](https://youtu.be/G_nPvcsM8LA?t=2108) |
| 2026-05-28 | `????` | opening_commentary | 0:17 | mild_buy | Pure-play drone manufacturer; third of Cramer's top-three picks in sector; upside if selected by Pentagon for supplier stakes; pick one or two from group. | [watch](https://youtu.be/G_nPvcsM8LA?t=17) |
| 2026-06-03 | `????` | lightning_round | 35:46 | wait_hold_neutral | Space stock referenced in context of current news cycle. Cramer doesn't know ticker or company name; will research and follow up. | [watch](https://youtu.be/hNHRqIXUT0o?t=2146) |
| 2026-06-04 | `????` | lightning_round | 36:00 | wait_hold_neutral | 100% speculation on recent regulatory approval; only appropriate as small speculative allocation, not as core portfolio holding or primary position. | [watch](https://youtu.be/2KJ4PtpX3Wk?t=2160) |
| 2026-06-10 | `????` | lightning_round | 37:00 | wait_hold | Data center infrastructure play (caller Claire, TN); conflicting signals—executive resignation vs insider buying—prevent clear call; requires research. | [watch](https://youtu.be/PSHvy4EAT1g?t=2220) |
| 2026-07-01 | `???` | lightning_round | 36:55 | sell_avoid | Power supplier to AI data centers with Tennessee Valley Authority backing and $1B liquidity; too speculative for Cramer; prefers GE as safer alternative to power-to-AI theme. | [watch](https://youtu.be/McE90rfiEIg?t=2215) |
| 2026-07-08 | `????` | in_depth_analysis | 11:21 / 19:20 | buy_on_pullback | Attractive aerospace-engine and gas-turbine end markets with accelerating revenue and improving profitability post PIK-loan paydown, but trades at a premium to Howmet — wait for $42 or the 30s. | [In-Depth: FedEx (FDX)](https://youtu.be/k1DEekxlGG4?t=681) · [In-Depth: TPC Holdings (????)](https://youtu.be/k1DEekxlGG4?t=1160) |
| 2026-07-08 | `????` | opening_commentary | 0:17 | caution_concern | Cheap if the data center trade holds, but a $29B raise with no retail appeal would force institutions to sell other stocks to fund it. | [watch](https://youtu.be/k1DEekxlGG4?t=17) |

_1 row(s) show no timestamp — that episode has no redirect pages on disk (they are only generated when an Overcast ID or audio URL is found), so the link points at the start of the episode._
