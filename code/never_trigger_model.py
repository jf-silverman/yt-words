"""
Trains and scores the "will this buy_on_pullback call avoid a real pullback?" model.

Target (set in analyze_buy_on_pullback.py): y=1 if the stock NEVER dropped
>= FIXED_PULLBACK_PCT (5%) below the call-day close within 60 calendar days. This
fixed threshold replaced an earlier beta-derived one that was partly circular (beta
also set the threshold). Only calls with a fully-elapsed 60-day window are labeled.

Single predictor: ret_20d — the stock's trailing ~20-calendar-day return as of the
call date. Research (grouped cross-validation by ticker and by call date) found this
one momentum feature carried essentially all the out-of-sample signal (~0.76 AUC);
adding volatility, fundamentals, market-regime, or beta did not improve held-out AUC
and beta actively hurt. The model is intentionally kept to this one feature.

Frozen-model design: train_and_save() is run once (or re-run deliberately) against
whatever labeled buy_on_pullback calls exist at that moment — those become the
permanent training set. Every later call to score() looks up whether a given
(ticker, call_date) was in that training set ("used for training") or is new, in
which case it gets a live prediction from the frozen model.
"""
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
RESULTS_PATH = ROOT / "data" / "prototypes" / "buy_on_pullback_results.json"
MODEL_PATH = ROOT / "data" / "prototypes" / "never_trigger_model.json"


def _key(ticker: str, call_date: str) -> str:
    return f"{ticker}|{call_date}"


def _training_rows(calls: list) -> list:
    """Calls that are both labeled (full 60d window) and have the predictor."""
    return [c for c in calls if c.get("pullback_5pct") is not None and c.get("ret_20d") is not None]


def train_and_save():
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
    from sklearn.metrics import roc_auc_score, accuracy_score

    calls = json.loads(RESULTS_PATH.read_text())["calls"]
    rows = _training_rows(calls)

    X = np.array([[c["ret_20d"]] for c in rows])
    y = np.array([0 if c["pullback_5pct"] else 1 for c in rows])  # 1 = never pulled back >=5%
    groups = np.array([c["ticker"] for c in rows])

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    # Honest CV: fold by ticker so a stock never sits in both train and test.
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    oof = cross_val_predict(model, X, y, cv=cv, groups=groups, method="predict_proba")[:, 1]
    auc = roc_auc_score(y, oof)
    acc = accuracy_score(y, (oof >= 0.5).astype(int))

    payload = {
        "trained_at": datetime.utcnow().isoformat(),
        "target": "never_pullback_5pct_within_60d",
        "pullback_pct": 5.0,
        "window_days": 60,
        "feature_names": ["ret_20d"],
        "intercept": model.intercept_[0],
        "coef": model.coef_[0].tolist(),
        "training_keys": [_key(c["ticker"], c["call_date"]) for c in rows],
        "cv_accuracy": round(acc, 3),
        "cv_auc": round(auc, 3),
        "cv_scheme": "StratifiedGroupKFold by ticker, 5-fold",
        "base_rate_never_pct": round(float(y.mean()) * 100, 1),
        "n_training": len(rows),
    }
    MODEL_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Trained on {len(rows)} calls ({int(y.sum())} never pulled back >=5%). "
          f"CV accuracy={acc:.3f}, CV AUC={auc:.3f} (grouped by ticker)")
    print(f"Model saved to {MODEL_PATH}")


def load_model():
    if not MODEL_PATH.exists():
        return None
    return json.loads(MODEL_PATH.read_text())


def score(model: dict, ticker: str, call_date: str, ret_20d) -> dict:
    """Returns {'status': 'training'|'predicted'|'insufficient_data',
                'prob_never_trigger_pct': float|None}.
    prob_never_trigger_pct = P(stock avoids a >=5% pullback within 60 days)."""
    key = _key(ticker, call_date)
    if key in model["training_keys"]:
        return {"status": "training", "prob_never_trigger_pct": None}
    if ret_20d is None:
        return {"status": "insufficient_data", "prob_never_trigger_pct": None}

    logit = model["intercept"] + model["coef"][0] * ret_20d
    prob = 1 / (1 + math.exp(-logit))
    return {"status": "predicted", "prob_never_trigger_pct": round(prob * 100, 1)}


if __name__ == "__main__":
    train_and_save()
