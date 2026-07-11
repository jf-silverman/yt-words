"""
Prototype analysis: does Cramer's "buy on pullback" thesis actually hold up?

For every buy_on_pullback mention, checks whether a real pullback happened within 60
calendar days, and if so, compares buying at the call-day close vs. buying at the dip
(each held for its own 60 days). Standalone script — reads the DB, writes results to
data/prototypes/buy_on_pullback_results.json. Does not touch pipeline.py or db.py.
"""
import bisect
import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

from db import get_connection
import never_trigger_model

ROOT = Path(__file__).parent.parent
BETA_CACHE_PATH = ROOT / "data" / "prototypes" / "beta_cache.json"
RET20_CACHE_PATH = ROOT / "data" / "prototypes" / "ret20_cache.json"
RESULTS_PATH = ROOT / "data" / "prototypes" / "buy_on_pullback_results.json"

WINDOW_DAYS = 60
RARITY_THRESHOLDS = [2, 3, 5]
SMALL_SAMPLE_N = 30

# Prediction model (never_trigger_model): predicts whether a buy_on_pullback call
# will AVOID a >= FIXED_PULLBACK_PCT drawdown within WINDOW_DAYS. This label is
# deliberately independent of the beta/market-cap strategy threshold below (which
# only governs the Strategy B "buy the dip" entry) — the old beta-derived label was
# partly circular because beta also sets that threshold. The single predictor is
# ret_20d: the stock's trailing ~20-calendar-day return as of the call date.
FIXED_PULLBACK_PCT = 5.0
RET20_DAYS = 20

BETA_BUCKETS = [
    (0.8, 2.0),
    (1.2, 3.0),
    (1.6, 5.0),
    (float("inf"), 8.0),
]
MKTCAP_THRESHOLDS = {
    "mega": 2.0,
    "large": 3.0,
    "mid": 5.0,
    "small": 10.0,
}
HOLD_OR_SELL_SENTS = {"wait_hold_neutral", "wait_hold", "caution_concern", "sell_avoid"}
EXIT_TRIGGER_SENTS = {"caution_concern", "sell_avoid"}
PRETREND_DAYS = 30


def _beta_threshold(beta: float) -> float:
    for cutoff, pct in BETA_BUCKETS:
        if beta <= cutoff:
            return pct
    return BETA_BUCKETS[-1][1]


def load_beta_cache() -> dict:
    if BETA_CACHE_PATH.exists():
        return json.loads(BETA_CACHE_PATH.read_text())
    return {}


def save_beta_cache(cache: dict) -> None:
    BETA_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def fetch_betas(tickers: list, cache: dict) -> dict:
    missing = [t for t in tickers if t not in cache]
    if missing:
        import yfinance as yf
        print(f"Fetching beta for {len(missing)} tickers via yfinance...")
        for i, t in enumerate(missing):
            try:
                info = yf.Ticker(t).info
                cache[t] = info.get("beta")
            except Exception as e:
                print(f"  {t}: failed ({e})")
                cache[t] = None
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(missing)}")
        save_beta_cache(cache)
    return cache


def load_ret20_cache() -> dict:
    if RET20_CACHE_PATH.exists():
        return json.loads(RET20_CACHE_PATH.read_text())
    return {}


def save_ret20_cache(cache: dict) -> None:
    RET20_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _ret20_from_series(sdates: list, series: dict, call_date: str, days: int = RET20_DAYS):
    """Trailing `days`-calendar-day return from a {date: close} series, as-of call_date."""
    on = [d for d in sdates if d <= call_date]
    if not on:
        return None
    px = series[on[-1]]
    cutoff = add_days(call_date, -days)
    prior = [d for d in sdates if d <= cutoff]
    if not prior or not px:
        return None
    p0 = series[prior[-1]]
    if not p0:
        return None
    return round((px - p0) / p0 * 100, 2)


def fetch_ret20(calls_by_ticker: dict, cache: dict) -> dict:
    """Populate ret20_cache (key 'TICKER|call_date') from yfinance 2y history.

    Needed because daily_prices only goes back to late 2025, so the 20-day trailing
    return can't be computed from the DB for early-2026 calls. Mirrors fetch_betas:
    only fetches keys not already cached, so it is cheap to re-run."""
    missing = [t for t, ds in calls_by_ticker.items()
               if any(f"{t}|{d}" not in cache for d in ds)]
    if missing:
        import yfinance as yf
        print(f"Fetching 2y history for ret_20d on {len(missing)} tickers...")
        for i, t in enumerate(missing):
            try:
                h = yf.Ticker(t).history(period="2y", auto_adjust=True)
                series = {d.strftime("%Y-%m-%d"): float(c) for d, c in zip(h.index, h["Close"])}
                sdates = sorted(series)
                for cd in calls_by_ticker[t]:
                    cache.setdefault(f"{t}|{cd}", _ret20_from_series(sdates, series, cd))
            except Exception as e:
                print(f"  {t}: failed ({e})")
                for cd in calls_by_ticker[t]:
                    cache.setdefault(f"{t}|{cd}", None)
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(missing)}")
                save_ret20_cache(cache)
        save_ret20_cache(cache)
    return cache


def threshold_for(ticker: str, beta_cache: dict, mktcap_cat: str) -> tuple:
    beta = beta_cache.get(ticker)
    if beta is not None:
        return _beta_threshold(beta), f"beta={beta:.2f}"
    cat = (mktcap_cat or "").lower()
    if cat in MKTCAP_THRESHOLDS:
        return MKTCAP_THRESHOLDS[cat], f"mktcap={cat}"
    return MKTCAP_THRESHOLDS["mid"], "default=mid (no beta/mktcap)"


def add_days(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def price_on_or_before(dates: list, daily: dict, d: str):
    idx = bisect.bisect_right(dates, d) - 1
    if idx < 0:
        return None
    return daily[dates[idx]]


def trailing_return_pct(dates: list, daily: dict, call_date: str, call_price: float, days: int = PRETREND_DAYS):
    cutoff = add_days(call_date, -days)
    idx = bisect.bisect_right(dates, cutoff) - 1
    if idx < 0:
        return None
    d = dates[idx]
    if (date.fromisoformat(call_date) - date.fromisoformat(d)).days > days + 10:
        return None
    price_then = daily[d]
    return round((call_price - price_then) / price_then * 100, 2)


def compute_analysis(conn, beta_cache: dict, trigger_model: dict | None,
                     ret20_cache: dict | None = None) -> tuple:
    """Pure computation over an open DB connection — no file I/O, no printing.
    Returns (results, summary). Reused by both the standalone CLI (analyze()) and
    db.py's build_analytics_json() for the live site."""
    ret20_cache = ret20_cache or {}
    c = conn.cursor()

    c.execute("""
        SELECT m.ticker, m.date, m.closing_price
        FROM mentions m
        JOIN episodes e ON e.id = m.episode_id
        WHERE m.sentiment = 'buy_on_pullback' AND m.closing_price IS NOT NULL
        ORDER BY m.ticker, m.date
    """)
    calls = [dict(r) for r in c.fetchall()]

    c.execute("SELECT ticker, market_cap_category FROM stocks")
    mktcap = {r["ticker"]: r["market_cap_category"] for r in c.fetchall()}

    c.execute("""
        SELECT m.ticker, m.date, m.sentiment
        FROM mentions m
        JOIN episodes e ON e.id = m.episode_id
        ORDER BY m.ticker, m.date
    """)
    mentions_by_ticker: dict = {}
    for r in c.fetchall():
        mentions_by_ticker.setdefault(r["ticker"], []).append({"date": r["date"], "sentiment": r["sentiment"]})

    c.execute("SELECT ticker, date, close FROM daily_prices ORDER BY ticker, date")
    daily_by_ticker: dict = {}
    for r in c.fetchall():
        daily_by_ticker.setdefault(r["ticker"], {})[r["date"]] = r["close"]
    dates_by_ticker = {t: sorted(d.keys()) for t, d in daily_by_ticker.items()}

    results = []
    rarity_hits = {t: 0 for t in RARITY_THRESHOLDS}
    rarity_evaluable = 0

    for call in calls:
        ticker, call_date, call_price = call["ticker"], call["date"], call["closing_price"]
        dates = dates_by_ticker.get(ticker, [])
        daily = daily_by_ticker.get(ticker, {})
        if not dates:
            continue

        window_end = add_days(call_date, WINDOW_DAYS)
        lo = bisect.bisect_right(dates, call_date)
        hi = bisect.bisect_right(dates, window_end)
        window_dates = dates[lo:hi]
        if not window_dates:
            continue

        rarity_evaluable += 1
        max_drawdown_pct = max(
            (call_price - daily[d]) / call_price * 100 for d in window_dates
        )
        for t in RARITY_THRESHOLDS:
            if max_drawdown_pct >= t:
                rarity_hits[t] += 1

        # only count toward the main A/B comparison if we actually have data
        # through call_date+60d; tolerate a few missing trading days at the tail
        # (weekends/holidays) by requiring the last available date to be within
        # 5 calendar days of window_end
        has_full_a_window = (
            date.fromisoformat(window_dates[-1]) >= date.fromisoformat(window_end) - timedelta(days=5)
        )

        thresh_pct, thresh_source = threshold_for(ticker, beta_cache, mktcap.get(ticker))

        dip_date = dip_price = None
        for d in window_dates:
            drawdown = (call_price - daily[d]) / call_price * 100
            if drawdown >= thresh_pct:
                dip_date, dip_price = d, daily[d]
                break

        other_calls = [
            m for m in mentions_by_ticker.get(ticker, [])
            if call_date < m["date"] <= window_end
        ]

        entry = {
            "ticker": ticker,
            "call_date": call_date,
            "call_price": call_price,
            "threshold_pct": thresh_pct,
            "threshold_source": thresh_source,
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "dip_triggered": dip_date is not None,
            "dip_date": dip_date,
            "dip_price": dip_price,
            "superseded_within_60d": bool(other_calls),
            "other_calls_within_60d": other_calls,
            "pretrend_30d_pct": trailing_return_pct(dates, daily, call_date, call_price),
            "beta": beta_cache.get(ticker),
            "market_cap_category": mktcap.get(ticker),
        }

        # ret_20d: trailing 20-calendar-day return as of the call date — the single
        # predictor for the never-pullback model. Prefer the yfinance-backed cache
        # (covers early-2026 calls the DB can't reach); fall back to the DB for calls
        # made after daily_prices has enough trailing history.
        ret20 = ret20_cache.get(f"{ticker}|{call_date}")
        if ret20 is None:
            ret20 = trailing_return_pct(dates, daily, call_date, call_price, days=RET20_DAYS)
        entry["ret_20d"] = ret20

        # Fixed-threshold pullback label for the prediction model. Only defined when a
        # full 60-day window has elapsed (otherwise "never pulled back" could just mean
        # "not enough time has passed"). True = a >= FIXED_PULLBACK_PCT drop occurred.
        entry["pullback_5pct"] = (max_drawdown_pct >= FIXED_PULLBACK_PCT) if has_full_a_window else None

        if trigger_model is not None:
            entry["never_trigger_prediction"] = never_trigger_model.score(
                trigger_model, ticker, call_date, entry["ret_20d"]
            )
        else:
            entry["never_trigger_prediction"] = {"status": "no_model", "prob_never_trigger_pct": None}

        if has_full_a_window:
            a_end_dates = [d for d in window_dates if d >= window_end]
            a_end_date = a_end_dates[0] if a_end_dates else window_dates[-1]
            a_return = (daily[a_end_date] - call_price) / call_price * 100
            entry["strategy_a_return_pct"] = round(a_return, 2)
        else:
            entry["strategy_a_return_pct"] = None

        downgraded_before_dip = dip_date is not None and any(
            m["date"] < dip_date and m["sentiment"] in HOLD_OR_SELL_SENTS for m in other_calls
        )

        if dip_date is not None and downgraded_before_dip:
            entry["strategy_b_return_pct"] = None
            entry["dip_excluded_reason"] = "downgraded before dip"
        elif dip_date is not None:
            dip_window_end = add_days(dip_date, WINDOW_DAYS)
            b_lo = bisect.bisect_right(dates, dip_date)
            b_dates = dates[b_lo:]
            b_end_dates = [d for d in b_dates if d >= dip_window_end]
            if b_end_dates:
                b_end_date = b_end_dates[0]
                b_return = (daily[b_end_date] - dip_price) / dip_price * 100
                entry["strategy_b_return_pct"] = round(b_return, 2)
            else:
                entry["strategy_b_return_pct"] = None
                entry["strategy_b_note"] = "insufficient data past dip+60d"
        else:
            entry["strategy_b_return_pct"] = None

        # Strategy C: buy at the dip (same entry as B), but if Cramer issues a
        # caution/sell call on this ticker before the dip's own 60-day window is
        # up, exit at that call's date instead of holding to day 60.
        if dip_date is not None and not downgraded_before_dip:
            dip_window_end = add_days(dip_date, WINDOW_DAYS)
            exit_candidates = sorted(
                m["date"] for m in mentions_by_ticker.get(ticker, [])
                if dip_date < m["date"] <= dip_window_end and m["sentiment"] in EXIT_TRIGGER_SENTS
            )
            if exit_candidates:
                exit_date = exit_candidates[0]
                exit_price = price_on_or_before(dates, daily, exit_date)
                if exit_price is not None:
                    entry["strategy_c_return_pct"] = round((exit_price - dip_price) / dip_price * 100, 2)
                    entry["strategy_c_exit_date"] = exit_date
                    entry["strategy_c_exit_reason"] = "downgraded to caution/sell"
                else:
                    entry["strategy_c_return_pct"] = None
            else:
                entry["strategy_c_return_pct"] = entry["strategy_b_return_pct"]
                entry["strategy_c_exit_date"] = None
                entry["strategy_c_exit_reason"] = "held full 60d" if entry["strategy_b_return_pct"] is not None else None
        else:
            entry["strategy_c_return_pct"] = None
            entry["strategy_c_exit_date"] = None
            entry["strategy_c_exit_reason"] = None

        results.append(entry)

    # ── Aggregate ──────────────────────────────────────────────────────────
    comparable = [
        r for r in results
        if r["strategy_a_return_pct"] is not None and r["strategy_b_return_pct"] is not None
    ]
    never_triggered = [r for r in results if not r["dip_triggered"] and r["strategy_a_return_pct"] is not None]
    triggered_no_b_data = [
        r for r in results
        if r["dip_triggered"] and r["strategy_a_return_pct"] is not None and r["strategy_b_return_pct"] is None
        and r.get("dip_excluded_reason") != "downgraded before dip"
    ]
    excluded_downgrade = [r for r in results if r.get("dip_excluded_reason") == "downgraded before dip"]

    def summarize(returns):
        if not returns:
            return None
        return {
            "n": len(returns),
            "mean_pct": round(statistics.mean(returns), 2),
            "median_pct": round(statistics.median(returns), 2),
            "win_rate_pct": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
            "small_sample": len(returns) < SMALL_SAMPLE_N,
        }

    a_returns = [r["strategy_a_return_pct"] for r in comparable]
    b_returns = [r["strategy_b_return_pct"] for r in comparable]
    b_beats_a = sum(1 for r in comparable if r["strategy_b_return_pct"] > r["strategy_a_return_pct"])

    never_triggered_a_returns = [r["strategy_a_return_pct"] for r in never_triggered]

    comparable_c = [
        r for r in results
        if r["strategy_a_return_pct"] is not None and r.get("strategy_c_return_pct") is not None
    ]
    c_returns = [r["strategy_c_return_pct"] for r in comparable_c]
    c_beats_a = sum(1 for r in comparable_c if r["strategy_c_return_pct"] > r["strategy_a_return_pct"])
    early_exits = [r for r in comparable_c if r.get("strategy_c_exit_date")]
    c_vs_b_where_both = [r for r in comparable_c if r.get("strategy_b_return_pct") is not None]
    c_beats_b = sum(
        1 for r in c_vs_b_where_both if r["strategy_c_return_pct"] > r["strategy_b_return_pct"]
    )

    # ── Predictive signal: triggered vs. never-triggered ────────────────────
    triggered_group = [r for r in results if r["dip_triggered"]]
    never_group = [r for r in results if not r["dip_triggered"]]

    def group_stats(group):
        betas = [r["beta"] for r in group if r["beta"] is not None]
        pretrends = [r["pretrend_30d_pct"] for r in group if r["pretrend_30d_pct"] is not None]
        cats = {}
        for r in group:
            cat = (r["market_cap_category"] or "unknown").lower()
            cats[cat] = cats.get(cat, 0) + 1
        return {
            "n": len(group),
            "avg_beta": round(statistics.mean(betas), 2) if betas else None,
            "avg_pretrend_30d_pct": round(statistics.mean(pretrends), 2) if pretrends else None,
            "market_cap_breakdown": cats,
        }

    predictive_analysis = {
        "triggered": group_stats(triggered_group),
        "never_triggered": group_stats(never_group),
    }

    # Fixed-threshold pullback label (what the prediction model actually targets).
    labeled = [r for r in results if r["pullback_5pct"] is not None]
    never_5pct = [r for r in labeled if not r["pullback_5pct"]]
    fixed_pullback = {
        "threshold_pct": FIXED_PULLBACK_PCT,
        "window_days": WINDOW_DAYS,
        "n_labeled": len(labeled),
        "n_never_pullback": len(never_5pct),
        "never_pullback_rate_pct": round(len(never_5pct) / len(labeled) * 100, 1) if labeled else None,
        "pullback_rate_pct": round((len(labeled) - len(never_5pct)) / len(labeled) * 100, 1) if labeled else None,
    }

    summary = {
        "total_buy_on_pullback_calls": len(calls),
        "calls_with_price_data": rarity_evaluable,
        "rarity": {
            f">= {t}% drawdown within {WINDOW_DAYS}d": {
                "count": rarity_hits[t],
                "pct_of_evaluable": round(rarity_hits[t] / rarity_evaluable * 100, 1) if rarity_evaluable else None,
            }
            for t in RARITY_THRESHOLDS
        },
        "strategy_a_buy_immediately": summarize(a_returns),
        "strategy_b_buy_the_dip": summarize(b_returns),
        "b_beats_a": {
            "n": len(comparable),
            "count": b_beats_a,
            "pct": round(b_beats_a / len(comparable) * 100, 1) if comparable else None,
        },
        "never_triggered": {
            "n": len(never_triggered),
            "pct_of_full_a_window_calls": round(
                len(never_triggered) / (
                    len(never_triggered) + len(comparable) + len(triggered_no_b_data) + len(excluded_downgrade)
                ) * 100, 1
            ) if (never_triggered or comparable or triggered_no_b_data or excluded_downgrade) else None,
            "strategy_a_if_bought_anyway": summarize(never_triggered_a_returns),
        },
        "triggered_but_insufficient_b_data": len(triggered_no_b_data),
        "excluded_downgraded_before_dip": len(excluded_downgrade),
        "superseded_within_60d": {
            "n": sum(1 for r in results if r["superseded_within_60d"]),
            "pct_of_all_calls": round(
                sum(1 for r in results if r["superseded_within_60d"]) / len(results) * 100, 1
            ) if results else None,
            "n_within_comparable": sum(1 for r in comparable if r["superseded_within_60d"]),
        },
        "strategy_c_buy_dip_follow_updates": summarize(c_returns),
        "c_beats_a": {
            "n": len(comparable_c),
            "count": c_beats_a,
            "pct": round(c_beats_a / len(comparable_c) * 100, 1) if comparable_c else None,
        },
        "c_beats_b": {
            "n": len(c_vs_b_where_both),
            "count": c_beats_b,
            "pct": round(c_beats_b / len(c_vs_b_where_both) * 100, 1) if c_vs_b_where_both else None,
        },
        "c_early_exits": len(early_exits),
        "predictive_analysis": predictive_analysis,
        "fixed_pullback": fixed_pullback,
    }

    return results, summary


def analyze():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT ticker FROM mentions WHERE sentiment = 'buy_on_pullback'")
    tickers = sorted(r["ticker"] for r in c.fetchall())

    beta_cache = load_beta_cache()
    beta_cache = fetch_betas(tickers, beta_cache)

    # ret_20d needs each call's date, not just the ticker
    c.execute("""
        SELECT DISTINCT m.ticker, m.date
        FROM mentions m
        WHERE m.sentiment = 'buy_on_pullback' AND m.closing_price IS NOT NULL
    """)
    calls_by_ticker: dict = {}
    for r in c.fetchall():
        calls_by_ticker.setdefault(r["ticker"], []).append(r["date"])
    ret20_cache = load_ret20_cache()
    ret20_cache = fetch_ret20(calls_by_ticker, ret20_cache)

    trigger_model = never_trigger_model.load_model()

    results, summary = compute_analysis(conn, beta_cache, trigger_model, ret20_cache)
    conn.close()

    payload = {"generated_at": datetime.utcnow().isoformat(), "summary": summary, "calls": results}
    RESULTS_PATH.write_text(json.dumps(payload, indent=2))

    print(f"\nTotal buy_on_pullback calls: {summary['total_buy_on_pullback_calls']}")
    print(f"Calls with any price data: {summary['calls_with_price_data']}")
    print("\nRarity (any evaluable window, regardless of A/B comparability):")
    for k, v in summary["rarity"].items():
        print(f"  {k}: {v['count']} calls ({v['pct_of_evaluable']}%)")

    print(f"\nComparable calls (full A window + dip triggered + full B window): {summary['b_beats_a']['n']}")
    print(f"Never triggered a dip (within full A window): {summary['never_triggered']['n']} "
          f"({summary['never_triggered']['pct_of_full_a_window_calls']}%)")
    print(f"Dip triggered but not enough data past dip+60d yet: {summary['triggered_but_insufficient_b_data']}")
    print(f"Dip triggered but excluded — Cramer downgraded to hold/sell before the dip: "
          f"{summary['excluded_downgraded_before_dip']}")
    sup = summary["superseded_within_60d"]
    print(f"Superseded by another call within 60d (any sentiment, marks a * in per-call detail): "
          f"{sup['n']}/{len(results)} ({sup['pct_of_all_calls']}%) — "
          f"{sup['n_within_comparable']} of those are in the comparable A/B set")

    a = summary["strategy_a_buy_immediately"]
    b = summary["strategy_b_buy_the_dip"]
    if a and b:
        print(f"\nStrategy A (buy immediately), n={a['n']}: mean {a['mean_pct']}%, "
              f"median {a['median_pct']}%, win rate {a['win_rate_pct']}%"
              f"{'  [small sample]' if a['small_sample'] else ''}")
        print(f"Strategy B (buy the dip),   n={b['n']}: mean {b['mean_pct']}%, "
              f"median {b['median_pct']}%, win rate {b['win_rate_pct']}%"
              f"{'  [small sample]' if b['small_sample'] else ''}")
        print(f"B beats A head-to-head: {summary['b_beats_a']['count']}/{summary['b_beats_a']['n']} "
              f"({summary['b_beats_a']['pct']}%)")

    nt = summary["never_triggered"]["strategy_a_if_bought_anyway"]
    if nt:
        print(f"\nNever-triggered calls, bought anyway at call price (n={nt['n']}): "
              f"mean {nt['mean_pct']}%, median {nt['median_pct']}%, win rate {nt['win_rate_pct']}%"
              f"{'  [small sample]' if nt['small_sample'] else ''}")

    cst = summary["strategy_c_buy_dip_follow_updates"]
    if cst:
        print(f"\nStrategy C (buy the dip, exit early on a caution/sell call), n={cst['n']}: "
              f"mean {cst['mean_pct']}%, median {cst['median_pct']}%, win rate {cst['win_rate_pct']}%"
              f"{'  [small sample]' if cst['small_sample'] else ''}")
        print(f"  {summary['c_early_exits']} of those exited early on a downgrade")
        print(f"  C beats A head-to-head: {summary['c_beats_a']['count']}/{summary['c_beats_a']['n']} "
              f"({summary['c_beats_a']['pct']}%)")
        print(f"  C beats B head-to-head (where both computable): "
              f"{summary['c_beats_b']['count']}/{summary['c_beats_b']['n']} ({summary['c_beats_b']['pct']}%)")

    fp = summary["fixed_pullback"]
    print(f"\nFixed {fp['threshold_pct']:.0f}% pullback label (prediction-model target), "
          f"full-window calls only (n={fp['n_labeled']}):")
    print(f"  Never dropped {fp['threshold_pct']:.0f}% within {fp['window_days']}d: "
          f"{fp['n_never_pullback']}/{fp['n_labeled']} ({fp['never_pullback_rate_pct']}%)")

    pa = summary["predictive_analysis"]
    print("\nPredictive signal — triggered vs. never-triggered calls:")
    for label, key in [("Triggered", "triggered"), ("Never triggered", "never_triggered")]:
        g = pa[key]
        print(f"  {label} (n={g['n']}): avg beta {g['avg_beta']}, "
              f"avg {PRETREND_DAYS}d pre-call momentum {g['avg_pretrend_30d_pct']}%, "
              f"mkt cap breakdown {g['market_cap_breakdown']}")

    print(f"\nFull results written to {RESULTS_PATH}")


if __name__ == "__main__":
    analyze()
