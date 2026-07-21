# Data Flow — From YouTube to Finished Products

How raw episode audio becomes the nightly email and the GitHub Pages site.
Everything below is produced by `code/pipeline.py` unless noted.

---

## The nightly run

```mermaid
flowchart TD
    subgraph EXT["External sources"]
        YT["YouTube — CNBC Mad Money<br/>(yt-dlp)"]
        YF["Yahoo Finance<br/>v8 chart API + yfinance"]
        OC["Overcast<br/>(episode IDs)"]
        AN["Claude<br/>(Code CLI by default, Haiku API opt-in)"]
    end

    YT -->|"discover new video IDs"| DISC["1. Discover episodes"]
    DISC --> TR["2. Fetch transcript<br/>extract_info(process=False)<br/>json3 &rarr; vtt fallback"]
    YT -.->|"auto-caption URL"| TR
    TR --> TXT[["data/transcripts/<br/>{date}_transcript.txt"]]

    TXT --> ANA["3. Analyze"]
    RULES[["prompts/<br/>mad_money_rules.md"]] --> ANA
    AN <--> ANA
    ANA --> AJSON["structured JSON<br/>sections + stocks"]

    AJSON --> UPD["4. update_stock_sentiments()<br/><i>clears the date first &mdash; idempotent</i>"]
    YF -->|"closing price<br/>per ticker per date"| UPD

    UPD --> DB[("data/mad_money.db<br/><b>SQLite — source of truth</b><br/>episodes · mentions · stocks<br/>daily_prices · forward_returns")]
    UPD --> SS[["data/stock_sentiments.json<br/><i>owns company/sector/style</i>"]]

    OC --> RED["5. Build redirect pages"]
    AJSON --> RED
    RED --> RD[["docs/redirect/<br/>{date}_{segment}.html"]]

    AJSON --> EM["6. Build + send email"]
    DB --> EM
    EM --> MAIL(["Gmail SMTP<br/>nightly email"])
    EM --> SUM[["data/summaries/<br/>{date}_summary.html"]]

    UPD --> SHARD["7. Write shards"]
    DB --> SHARD
    SS --> SHARD
    SHARD --> DOCS[["docs/data/*.json"]]

    DOCS --> PUSH["8. commit_and_push()<br/><b>refuses unless on main</b>"]
    RD --> PUSH
    PUSH --> PAGES(["GitHub Pages<br/>stocks.html"])

    %% Explicit color: on every classDef — a fill without one inherits the
    %% viewer's theme text colour, which renders light-on-light in dark mode.
    classDef store fill:#dbe4ff,stroke:#3b5bbf,stroke-width:1px,color:#0b1020
    classDef out   fill:#cdebd2,stroke:#2f7d43,stroke-width:1px,color:#0b1020
    class TXT,SS,RD,SUM,DOCS,RULES store
    class MAIL,PAGES out
```

| Box | Meaning |
|-----|---------|
| Blue, double-edged | a stored file or directory on disk |
| Green, rounded | a delivered product — the nightly email, the live site |
| Plain rectangle | a processing step in `pipeline.py` |
| Cylinder | the SQLite database (source of truth) |

---

## Stage detail

| # | Stage | Reads | Writes |
|---|-------|-------|--------|
| 1 | Discover | YouTube channel via yt-dlp | `data/processed_episodes.json` |
| 2 | Transcript | YouTube auto-captions (json3, else vtt) | `data/transcripts/`, `data/transcript_timing.csv` |
| 3 | Analyze | transcript + `prompts/mad_money_rules.md` | in-memory JSON |
| 4 | Persist | analysis + Yahoo closing prices | SQLite, `data/stock_sentiments.json` |
| 5 | Redirects | Overcast ID cache | `docs/redirect/` |
| 6 | Email | analysis + DB (charts via matplotlib) | SMTP send, `data/summaries/` |
| 7 | Shards | SQLite + `stock_sentiments.json` | `docs/data/` |
| 8 | Publish | everything dirty under `docs/` + `data/` | `main` &rarr; GitHub Pages |

---

## What each site file is for

```mermaid
flowchart LR
    DB[("mad_money.db")] --> IDX[["index.json<br/>every ticker, for search"]]
    DB --> SH[["{TICKER}.json<br/>one shard per ticker,<br/>fetched on demand"]]
    DB --> REC[["recent.json<br/>last 90 days"]]
    DB --> ANLY[["analytics.json<br/>build_analytics_json()"]]
    DB --> BT[["backtest_by_ticker.json<br/>60d buy-call backtest,<br/>&ge;3 calls only"]]
    DB --> PR[["{TICKER}_prices.json<br/>daily closes"]]

    IDX --> TAB1(["Search tab"])
    SH --> TAB1
    BT --> TAB1
    PR --> TAB1
    REC --> TAB2(["Recent Picks tab"])
    ANLY --> TAB3(["Analytics tab"])

    classDef store fill:#dbe4ff,stroke:#3b5bbf,stroke-width:1px,color:#0b1020
    classDef out   fill:#cdebd2,stroke:#2f7d43,stroke-width:1px,color:#0b1020
    class IDX,SH,REC,ANLY,BT,PR store
    class TAB1,TAB2,TAB3 out
```

`stocks.html` is fully client-side — it fetches these JSON files and renders
everything in the browser. There is no backend.

---

## Off the nightly path

These are run by hand and are **not** part of the cron.

```mermaid
flowchart TD
    DB[("mad_money.db")] --> UNK["--list-unknown-tickers"]
    UNK --> UNKMD[["notes/unknown-tickers.md<br/>manual review queue"]]
    UNKMD -.->|"human identifies<br/>the company"| FIX["sqlite UPDATE<br/>+ --backfill-prices<br/>+ --rebuild-shards"]
    FIX --> DB

    DB --> BOP["analyze_buy_on_pullback.py"]
    BOP --> R20[["ret20_cache.json"]]
    R20 --> NTM["never_trigger_model.py<br/>(frozen model)"]
    NTM --> ANLY[["analytics.json panel"]]

    TXT[["data/transcripts/"]] --> BF["backfill.py --reanalyze<br/>(no YouTube calls)"]
    BF --> DB

    classDef store fill:#dbe4ff,stroke:#3b5bbf,stroke-width:1px,color:#0b1020
    class UNKMD,R20,ANLY,TXT store
```

---

## Invariants worth not breaking

**SQLite is the source of truth for mention data.** `stock_sentiments.json` is
authoritative only for `company` / `sector` / `style`. `--rebuild-shards` calls
`_sync_mentions_from_db()` first, so after any manual DB edit a rebuild is all
that's needed — never hand-edit mentions in the JSON.

Note the direction reverses for names: `upsert_stock()` writes the JSON's company
name *into* the DB, so a name must be corrected in `stock_sentiments.json` or a
later `--fetch-sectors` will overwrite it.

**Re-processing a date replaces it.** `update_stock_sentiments()` clears the date's
mentions before writing. This matters because `UNIQUE(episode_id, ticker, segment)`
only rejects an *exact* repeat — before the clear existed, a re-analysis that moved
a call to another segment, or named the same company under a different ticker, left
both rows in place and nothing looked wrong. See BUG-010.

**`main` owns every generated artifact.** `docs/data/`, `docs/redirect/`,
`data/daily_prices/`, and the four `data/*.json` state files may only be committed
on `main`; `.githooks/pre-commit` enforces it. The cron therefore runs from a
main-pinned worktree (`~/Documents/DS/yt-words-cron`), and `commit_and_push()`
refuses to run anywhere else.

**Index comparisons are paired.** Any "vs. the S&P" figure subtracts the index's
return over *that call's own* window before aggregating. Never median-of-returns
minus median-of-index — see the paired-excess rule in `CLAUDE.md`.

**Everything is measured inside one ~6-month AI-driven bull market (Jan–Jul 2026).**
Every analytics panel carries that caveat on the site.
