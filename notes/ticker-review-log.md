# Ticker Review Log

Hand-maintained record of ticker corrections that required judgment, and of rows
deliberately **left unresolved**. The two queue files
(`ticker-name-mismatches.md`, `unknown-tickers.md`) are regenerated from the DB and
only show what is *currently* unresolved — they carry no memory of decisions. This
file is that memory, so nobody re-derives the same conclusion twice or "fixes" a
row that was left alone on purpose.

---

## Held — need your judgment (as of 2026-07-22)

These were verified far enough to know the machine suggestion is wrong, but not far
enough to be confident in a replacement. **Do not apply a suggestion to these
without listening to the audio.**

| Ticker | Date | Stored as | Why it's held |
|--------|------|-----------|---------------|
| `AVX` | 2026-04-17 | Aeva Technologies | Transcript literally says *"drone maker Aeva"* — but Aeva Technologies is a **lidar** company, public since 2021, and the note describes a **fresh IPO** ("IPO'd at $20, +35% to $27 on day one"). Either the caption garbled a different drone IPO's name, or Cramer misspoke. `AEVA` is a portfolio holding, so a wrong move here corrupts a chart you actually read. |
| `AX` | 2026-07-21 | Axiom (Defense Technology) | Flagged by the ingest validator on its first production run. `AX` is **Axos Financial**, a bank. Which defense company "Axiom" refers to is unclear — Axiom Space is private; there may be a recent listing. |
| `BDN` | 2026-03-03 | "Blue (implied Blackstone or similar…)" | The stored company name is itself a guess, not a company. Needs the audio. |
| `SPRL` | 2026-05-12 | "Spirail (exact company uncertain)" | Same — the name is admitted-uncertain at source. |
| `URG` | 2026-01-20 | "US Anamoney (United States Rare Earth…)" | Garbled name. `URG` is Ur-Energy. Candidate is `USAR` (USA Rare Earth) but unconfirmed. |
| `MIND` | 2026-04-20 | Biphenium Therapeutics | `MIND` is MIND Technology (marine tech). "Biphenium" doesn't resolve to a known issuer. |
| `PBR` | 2026-04-02 | Polarcoin | `PBR` is Petrobras. "Polarcoin" doesn't resolve. |
| `QTUM` / `QTEC` | 2026-06-04 / 03-25 | Quantinium / Quantee Electronics | Both stored tickers are **ETFs**. The underlying companies don't resolve to a listed symbol; these may belong in the `????` queue instead. |

---

## Resolved 2026-07-22 — the non-obvious ones

54 corrections were applied (see commit `40b3dc07`). Most were mechanical. These
required a transcript check and are recorded because the obvious answer was wrong:

**`BLK` was three different companies.** Its 8 mentions did not belong to one
issuer at all:
- 4 stay `BLK` — BlackRock (*"Larry Fink"*, *"passes a $15 trillion assets under
  management hurdle"*)
- 3 &rarr; `BX` — Blackstone (private credit, fund gates)
- 1 &rarr; `XYZ` — Block (*"CEO Jack Dorsey slashed the staff of Block"*)

The queue proposed a bulk `BLK` &rarr; `BX` move, which would have corrupted the
5 rows that were already correct. **Never bulk-move a multi-mention ticker without
reading each note.**

**`ABR` &rarr; `B`, not `ABX`.** Yahoo's search suggested `ABX` for "Barrick Gold",
but `ABX` is now **Abacus Global Management**. Barrick renamed to Barrick Mining,
symbol `B`. Cramer's *"it's called gold now"* is a red herring — `GOLD` is a
separate company, Gold.com Inc.

**`ONEG` &rarr; `ONON`, not `OMF`.** Transcript: *"two sports apparel plays, One
Holding and Under Armour"* — On Holding, not OneMain Financial.

**Ticker right, stored name wrong** — label-only fixes, no mention moved:
| Ticker | Was labelled | Actually |
|--------|--------------|----------|
| `SPOT` | One Holding | Spotify — transcript says Spotify |
| `EXE` | Sempra Energy | Expand Energy — transcript says "Expand Energy" |
| `KLAR` | Klär | Klarna Group — `KLAR` was already correct; the suggested `KLRA` is Kailera Therapeutics |
| `CMS` | Columbia Banking System | CMS Energy — that episode is entirely utilities, no bank mentioned |
| `BLK` | Blackstone | BlackRock |

---

## 2026-07-22 — first pass on the split queue

`--check-ticker-names` now proves out a small "likely mis-ticker" section. Three of
the five were checked against the transcript; two were applied.

| Ticker | Verdict | Transcript evidence |
|--------|---------|---------------------|
| `CPK` &rarr; `CPB` | **applied** | 2026-03-12: *"Yesterday, Campbell's reported one of the worst quarters I've seen in ages… Stock hit a 17-year low."* Was sitting on Chesapeake Utilities at $129.22; correct close is $21.65. |
| `USA` &rarr; `USAR` | **applied** | 2026-05-05 lightning round: caller asks about USA Rare Earth, Cramer answers *"the only one we're recommending in that area is MP Materials."* Was on Liberty All-Star Equity Fund at $5.81; correct close is $27.42. |
| `AVX` | **HELD — do not apply the suggestion** | See below. |

### `AVX` — the suggestion was actively dangerous

The queue suggested `AVX` &rarr; `AEVA`, because the stored company name is
"Aeva Technologies" and Yahoo maps that name to `AEVA`. The transcript says the
opposite — the **ticker is right and the name is the hallucination**:

> [21:08] *"today I want to talk about a new IPO that really excites me. It's called
> **AVX**. It's a defense contractor focused on drones… It rallied nearly 35% out of
> the gate."* (2026-04-17, also called "Avex" at [20:30])

So this is a genuinely new listing Cramer named on air. Applying `AEVA` would have
filed a drone-IPO call onto Aeva Technologies — a **held position**, whose chart and
backtest would then be wrong. Left alone until the real symbol is confirmed; Yahoo
currently reports `AVX` as "Avax One Technology Ltd.", which does not match either.

This is the concrete case behind the standing rule: **the suggestion assumes the
company name is the correct half.** When the name is the hallucination, the
suggestion points confidently at the wrong company.

`AX` ("Axiom (Defense Technology)" &rarr; `AXIN`) and `BDN` (stored as the prose
"Blue (implied Blackstone or similar…)") are unchecked and likely have the same
shape — a stored name that was never a real company name. Check the transcript
before touching either.

### Also noted

The 2026-03-12 episode is one of **16 flagged `is_fundamentals=1`**, which
`_sync_mentions_from_db()` filters out — so its 18 mentions never reach
`stock_sentiments.json`, the site, or the JSON-driven `--backfill-prices`. The `CPB`
price there had to be fetched and written to SQLite directly. Worth remembering: a
queue row can point at a mention that is invisible on the site, because the queue
counts mentions straight from the DB without that filter.

---

## Method notes

- **Yahoo's symbol search was wrong on 7 of 43** suggestions. Treat it as a
  starting point, never an answer.
- The **stored company name can be the wrong half of the pair.** Before moving a
  mention, confirm the *company* from the transcript — otherwise you move a correct
  ticker onto a wrong one.
- Check for a **UNIQUE(episode_id, ticker, segment) clash** before updating. If the
  correct ticker already has a row for that episode and segment, the wrong row is a
  duplicate — delete it instead (that was `SDOT` &rarr; `SNDK`).
- Both queue files now source company names from **SQLite**, not
  `stock_sentiments.json`, so they give the same answer in either worktree. Before
  that fix the feature-branch copy reported 100 rows against main's 78, purely
  because the tracked JSON is main-owned and goes stale on feature branches.
