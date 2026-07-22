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
