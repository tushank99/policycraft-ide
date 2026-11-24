#!/usr/bin/env python3
"""TF-IDF + logistic regression baseline for CVE severity (macro-F1).

    python -m ml.baseline --data ml/data/nvd_cves.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline

from ml.data_utils import LABELS, load_splits


def build() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=100_000, sublinear_tf=True)),
        ("clf", LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced")),
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="ml/data/nvd_cves.csv")
    ap.add_argument("--model-out", default="ml/models/baseline_tfidf_lr.joblib")
    ap.add_argument("--metrics-out", default="ml/results/baseline.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    splits = load_splits(args.data, args.seed)
    train = splits["train"]
    test = splits["test"]
    # Baseline has no early stopping, so it trains on train+val (DistilBERT uses val for model selection).
    fit_df = pd.concat([train, splits["val"]], ignore_index=True)

    t0 = time.time()
    model = build().fit(fit_df["description"], fit_df["severity"])
    train_s = time.time() - t0
    pred = model.predict(test["description"])

    macro_f1 = f1_score(test["severity"], pred, average="macro", labels=LABELS)
    report = classification_report(test["severity"], pred, labels=LABELS, digits=4, output_dict=True)
    print(classification_report(test["severity"], pred, labels=LABELS, digits=4))
    print(f"Baseline macro-F1: {macro_f1:.4f}  (train {train_s:.1f}s, n_train={len(fit_df)}, n_test={len(test)})")

    Path(args.model_out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, args.model_out)
    Path(args.metrics_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics_out).write_text(json.dumps({
        "model": "tfidf(1-2gram)+logreg(balanced)",
        "macro_f1": round(macro_f1, 4),
        "per_class_f1": {k: round(report[k]["f1-score"], 4) for k in LABELS},
        "confusion_matrix": {"labels": LABELS, "matrix": confusion_matrix(test["severity"], pred, labels=LABELS).tolist()},
        "n_train": len(fit_df),
        "n_test": len(test),
        "train_seconds": round(train_s, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
