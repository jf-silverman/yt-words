"""
Prototype model: can beta, pre-call momentum, and market cap predict which
buy_on_pullback calls will NEVER see a real pullback within 60 days?

Two views of the same question, both cross-validated (not in-sample) since n is small:
  1. Regression: predict max_drawdown_pct (continuous) -> report R^2 directly.
  2. Classification: predict never_triggered (yes/no) -> report accuracy, ROC AUC,
     and an out-of-fold McFadden pseudo-R^2 for readers who want an R^2-style number
     on the actual yes/no question.

Reads data/prototypes/buy_on_pullback_results.json (written by analyze_buy_on_pullback.py).
Standalone — no changes to the site or pipeline.
"""
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.metrics import roc_auc_score, accuracy_score, confusion_matrix

ROOT = Path(__file__).parent.parent
RESULTS_PATH = ROOT / "data" / "prototypes" / "buy_on_pullback_results.json"

MKTCAP_CATS = ["mega", "large", "mid", "small"]


def build_features(calls: list):
    rows = [c for c in calls if c["beta"] is not None and c["pretrend_30d_pct"] is not None]
    dropped = len(calls) - len(rows)
    print(f"Using {len(rows)} calls with complete beta + pre-call momentum data "
          f"({dropped} dropped for missing data)")

    X = []
    for c in rows:
        cat = (c["market_cap_category"] or "").lower()
        cat_onehot = [1.0 if cat == m else 0.0 for m in MKTCAP_CATS]
        X.append([c["beta"], c["pretrend_30d_pct"]] + cat_onehot)
    X = np.array(X)
    feature_names = ["beta", "pretrend_30d_pct"] + [f"mktcap_{m}" for m in MKTCAP_CATS]

    y_drawdown = np.array([c["max_drawdown_pct"] for c in rows])
    y_never = np.array([0 if c["dip_triggered"] else 1 for c in rows])
    return X, y_drawdown, y_never, feature_names, rows


def run_regression(X, y_drawdown, feature_names):
    print("\n--- Regression: predicting max_drawdown_pct ---")
    model = LinearRegression()
    cv = 5
    scores = cross_val_score(model, X, y_drawdown, cv=cv, scoring="r2")
    print(f"Cross-validated R^2 ({cv}-fold): {scores}")
    print(f"Mean R^2: {scores.mean():.3f}  (0 = no better than predicting the average drawdown, "
          f"1 = perfect prediction; negative means worse than just guessing the average)")

    model.fit(X, y_drawdown)
    print("In-sample coefficients (direction/magnitude only — see CV R^2 above for real predictive power):")
    for name, coef in zip(feature_names, model.coef_):
        print(f"  {name}: {coef:+.3f}")


def run_classification(X, y_never):
    print("\n--- Classification: predicting never_triggered (yes/no) ---")
    model = LogisticRegression(max_iter=1000)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof_probs = cross_val_predict(model, X, y_never, cv=cv, method="predict_proba")[:, 1]
    oof_preds = (oof_probs >= 0.5).astype(int)

    acc = accuracy_score(y_never, oof_preds)
    auc = roc_auc_score(y_never, oof_probs)
    cm = confusion_matrix(y_never, oof_preds)

    eps = 1e-9
    ll_model = np.sum(y_never * np.log(oof_probs + eps) + (1 - y_never) * np.log(1 - oof_probs + eps))

    # out-of-fold null model: for each fold, predict the training-fold base rate
    null_probs = np.zeros_like(oof_probs)
    for train_idx, test_idx in cv.split(X, y_never):
        base_rate = y_never[train_idx].mean()
        null_probs[test_idx] = base_rate
    ll_null = np.sum(y_never * np.log(null_probs + eps) + (1 - y_never) * np.log(1 - null_probs + eps))
    mcfadden_r2 = 1 - ll_model / ll_null

    print(f"Out-of-fold accuracy: {acc:.3f}  (base rate if always guessing 'triggered': "
          f"{1 - y_never.mean():.3f})")
    print(f"Out-of-fold ROC AUC: {auc:.3f}  (0.5 = no better than a coin flip, 1.0 = perfect)")
    print(f"Out-of-fold McFadden pseudo-R^2: {mcfadden_r2:.3f}  "
          f"(0 = no better than guessing the base rate, higher = better; can go negative)")
    print(f"Confusion matrix [rows=actual, cols=predicted], order=[triggered, never_triggered]:\n{cm}")


def main():
    payload = json.loads(RESULTS_PATH.read_text())
    X, y_drawdown, y_never, feature_names, rows = build_features(payload["calls"])
    print(f"Never-triggered rate in this sample: {y_never.mean():.1%}")

    print("\n============================")
    print(" Full model (beta + pre-call momentum + market cap dummies)")
    print("============================")
    run_regression(X, y_drawdown, feature_names)
    run_classification(X, y_never)

    # Market cap categories are sparse (mid=6, small=1 in this sample) and can
    # destabilize the linear coefficients — check a simpler 2-feature model too.
    X_simple = X[:, :2]
    print("\n============================")
    print(" Simple model (beta + pre-call momentum only, no market cap)")
    print("============================")
    run_regression(X_simple, y_drawdown, feature_names[:2])
    run_classification(X_simple, y_never)


if __name__ == "__main__":
    main()
