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

Jump-to-video links (`date · segment · time`) come from the same section timing
the review queue uses; a link that lands on the episode start means that section
has no timing on disk. Timestamps are section starts, so scrub forward a little.

| Ticker | Where — date · segment · time | Stored as | Why it's held |
|--------|-------------------------------|-----------|---------------|
| `BDN` | 2026-03-03 · closing_commentary · [39:00](https://youtu.be/ISGe21_RSYs?t=2340) | "Blue (implied Blackstone or similar…)" | The stored company name is itself a guess, not a company. Needs the audio. |
| `SPRL` | 2026-05-12 · lightning_round · [37:26](https://youtu.be/RDTfIM7usu4?t=2246) | "Spirail (exact company uncertain)" | Same — the name is admitted-uncertain at source. |
| `URG` | 2026-01-20 · in_depth_analysis · [episode](https://youtu.be/tKgYSl5KSq0) | "US Anamoney (United States Rare Earth…)" | Garbled name. `URG` is Ur-Energy. Candidate is `USAR` (USA Rare Earth) but unconfirmed. |
| `MIND` | 2026-04-20 · interview · [28:08](https://youtu.be/-kPm8LikEBI?t=1688) | Biphenium Therapeutics | `MIND` is MIND Technology (marine tech). "Biphenium" doesn't resolve to a known issuer. |
| `PBR` | 2026-04-02 · lightning_round · [36:20](https://youtu.be/3nt_bL2oclU?t=2180) | Polarcoin | `PBR` is Petrobras. "Polarcoin" doesn't resolve. |
| `QTUM` / `QTEC` | 2026-06-04 · in_depth_analysis · [21:00](https://youtu.be/2KJ4PtpX3Wk?t=1260)<br>2026-03-25 · lightning_round · [56:00](https://youtu.be/V9apPO6VXII?t=3360) | Quantinium / Quantee Electronics | Both stored tickers are **ETFs**. The underlying companies don't resolve to a listed symbol; these may belong in the `????` queue instead. |

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

| Ticker | Where — date · segment · time | Verdict | Transcript evidence |
|--------|-------------------------------|---------|---------------------|
| `CPK` &rarr; `CPB` | 2026-03-12 · closing_commentary · [39:57](https://youtu.be/MsK1NxlzwvY?t=2397) | **applied** | *"Yesterday, Campbell's reported one of the worst quarters I've seen in ages… Stock hit a 17-year low."* Was sitting on Chesapeake Utilities at $129.22; correct close is $21.65. |
| `USA` &rarr; `USAR` | 2026-05-05 · lightning_round · [32:32](https://youtu.be/stBiW-NPi9E?t=1952) | **applied** | Caller asks about USA Rare Earth, Cramer answers *"the only one we're recommending in that area is MP Materials."* Was on Liberty All-Star Equity Fund at $5.81; correct close is $27.42. |
| `AVX` &rarr; `AVEX` | 2026-04-17 · in_depth_analysis · [21:20](https://youtu.be/HYRppgkEDXc?t=1280) | **RESOLVED 2026-07-23** | See below — *both* halves of the pair were wrong. |

### `AVX` &rarr; `AVEX` — both halves were wrong, and why the suggestion was dangerous

**Resolution (2026-07-23):** the call is **AEVEX Corp.**, ticker **`AVEX`**, a drone
defense contractor that IPO'd that very day. Yahoo confirms `AVEX` → "AEVEX Corp.",
and `AVEX` has *no* close on 04-16 but $26.93 on 04-17 — an IPO-day print that matches
the note's *"IPO'd at $20, +35% to $27 on day one"* exactly. Applied: mention retargeted
`AVX` → `AVEX`, company set to "AEVEX Corp.", price corrected from the inherited $7.68
(Avax One Technology) to **$26.93**.

The queue suggested `AVX` &rarr; `AEVA`, because the stored company name was
"Aeva Technologies" and Yahoo maps that name to `AEVA`. That was doubly wrong —
**neither half of the pair was right**:

> [21:08] *"today I want to talk about a new IPO that really excites me. It's called
> **AVX**. It's a defense contractor focused on drones… It rallied nearly 35% out of
> the gate."* (2026-04-17, also called "Avex" at [20:30])

The caption garbled "AEVEX" to "AVX"/"Avex", and the model then invented "Aeva
Technologies" for the name. Applying the suggested `AEVA` would have filed a drone-IPO
call onto Aeva Technologies — a **held position**, whose chart and backtest would then
be wrong.

This is the concrete case behind the standing rule: **the suggestion assumes the
company name is the correct half.** When the name is *also* a hallucination, the
suggestion points confidently at the wrong company — and the true answer (`AVEX`)
was neither the filed ticker nor the suggested one. It took a human who knew the
company to close it.

**`AX` (2026-07-21) was the same company** — resolved 2026-07-23. The caller says
he *"purchased the stock for 34 after the IPO in April and attended the earnings
call in May… the stock I'm calling about is AX,"* and Cramer answers *"defense
technology."* Same drone-defense IPO, same caption garble of "AEVEX" → "AX".
Retargeted `AX` &rarr; `AVEX`; price corrected from Axos Financial's inherited
$97.42 to AEVEX's real 07-21 close of **$14.75** (down from the $26.93 IPO-day pop,
consistent with the caller's $34 cost basis and the sector selloff). AEVEX now has
a genuine two-point history.

**`BDN` (2026-03-03) was deleted** — resolved 2026-07-23. It was not a stock call
at all: the closing commentary was about how private-equity/credit funds are
affecting public markets, and the reference was to **Blue Owl**, a Blackstone-run
private credit fund (blocked redemptions, 30% liquidity offers). No public-equity
call was being made, so the mention was removed rather than retargeted. It had been
sitting on Brandywine Realty Trust's inherited $3.12.

With that, **section 1 of the mismatch queue (proven mis-tickers) is empty** — the
`AVX`/`AX` → `AVEX` fixes and this deletion cleared all three that carried a
provably-wrong symbol.

### Also noted

The 2026-03-12 episode is one of **16 flagged `is_fundamentals=1`**, which
`_sync_mentions_from_db()` filters out — so its 18 mentions never reach
`stock_sentiments.json`, the site, or the JSON-driven `--backfill-prices`. The `CPB`
price there had to be fetched and written to SQLite directly. Worth remembering: a
queue row can point at a mention that is invisible on the site, because the queue
counts mentions straight from the DB without that filter.

---

## 2026-07-23 — validator catch on the nightly run

| Ticker | Where — date · segment · time | Verdict | Evidence |
|--------|-------------------------------|---------|----------|
| `KEL` &rarr; `KEEL` | 2026-07-22 · closing_commentary · [episode](https://youtu.be/wqIw4sfmmns) | **applied** | The ingest validator flagged it live: `KEL` resolves to no symbol, and Yahoo maps the stored name "Keel Infrastructure" to `KEEL`. Clean case (the name is the good half, unlike `AVX`). Was priceless; `KEEL` 2026-07-22 close is $4.69. |

This is the validator working as designed on the same night it ran, rather than a
row aging in the queue — the opposite failure mode from `AVX`, where the stored
*name* was the hallucination.

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
