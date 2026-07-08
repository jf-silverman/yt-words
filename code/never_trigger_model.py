"""
Trains and scores the "will this buy_on_pullback call ever pull back?" model.

Frozen-model design: train_and_save() is run once (or re-run deliberately) against
whatever buy_on_pullback calls exist at that moment — those become the permanent
training set. Every later call to score() looks up whether a given (ticker, call_date)
was in that training set ("used for training") or is new, in which case it gets a live
prediction from the frozen model. This is what lets analyze_buy_on_pullback.py label
old calls "used for training" and score newly-added calls going forward.
"""
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
RESULTS_PATH = ROOT / "data" / "prototypes" / "buy_on_pullback_results.json"
MODEL_PATH = ROOT / "data" / "prototypes" / "never_trigger_model.json"

MKTCAP_CATS = ["mega", "large", "mid", "small"]


def _key(ticker: str, call_date: str) -> str:
    return f"{ticker}|{call_date}"


def _features(c: dict):
    cat = (c["market_cap_category"] or "").lower()
    return [c["beta"], c["pretrend_30d_pct"]] + [1.0 if cat == m else 0.0 for m in MKTCAP_CATS]


def train_and_save():
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.metrics import roc_auc_score, accuracy_score

    calls = json.loads(RESULTS_PATH.read_text())["calls"]
    rows = [c for c in calls if c["beta"] is not None and c["pretrend_30d_pct"] is not None]

    X = np.array([_features(c) for c in rows])
    y = np.array([0 if c["dip_triggered"] else 1 for c in rows])

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof_probs = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
    auc = roc_auc_score(y, oof_probs)
    acc = accuracy_score(y, (oof_probs >= 0.5).astype(int))

    payload = {
        "trained_at": datetime.utcnow().isoformat(),
        "feature_names": ["beta", "pretrend_30d_pct"] + [f"mktcap_{m}" for m in MKTCAP_CATS],
        "mktcap_cats": MKTCAP_CATS,
        "intercept": model.intercept_[0],
        "coef": model.coef_[0].tolist(),
        "training_keys": [_key(c["ticker"], c["call_date"]) for c in rows],
        "cv_accuracy": round(acc, 3),
        "cv_auc": round(auc, 3),
        "n_training": len(rows),
    }
    MODEL_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Trained on {len(rows)} calls. CV accuracy={acc:.3f}, CV AUC={auc:.3f}")
    print(f"Model saved to {MODEL_PATH}")


def load_model():
    if not MODEL_PATH.exists():
        return None
    return json.loads(MODEL_PATH.read_text())


def score(model: dict, ticker: str, call_date: str, beta, pretrend_30d_pct, market_cap_category) -> dict:
    """Returns {'status': 'training'|'predicted'|'insufficient_data', 'prob_never_trigger_pct': float|None}"""
    key = _key(ticker, call_date)
    if key in model["training_keys"]:
        return {"status": "training", "prob_never_trigger_pct": None}
    if beta is None or pretrend_30d_pct is None:
        return {"status": "insufficient_data", "prob_never_trigger_pct": None}

    cat = (market_cap_category or "").lower()
    x = [beta, pretrend_30d_pct] + [1.0 if cat == m else 0.0 for m in model["mktcap_cats"]]
    logit = model["intercept"] + sum(c * v for c, v in zip(model["coef"], x))
    prob = 1 / (1 + math.exp(-logit))
    return {"status": "predicted", "prob_never_trigger_pct": round(prob * 100, 1)}


if __name__ == "__main__":
    train_and_save()
