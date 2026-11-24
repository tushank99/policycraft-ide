#!/usr/bin/env python3
"""Fine-tune DistilBERT on NVD CVE descriptions -> severity (LOW/MEDIUM/HIGH/CRITICAL).

Designed for Colab's free T4 GPU (~6k examples, 3 epochs, ~5-8 min). Runs on
CPU too, just slowly.

    python -m ml.train_distilbert --data ml/data/nvd_cves.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, f1_score

from ml.data_utils import ID2LABEL, LABEL2ID, LABELS, load_splits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="ml/data/nvd_cves.csv")
    ap.add_argument("--base-model", default="distilbert-base-uncased")
    ap.add_argument("--out", default="ml/models/distilbert-cve-severity")
    ap.add_argument("--metrics-out", default="ml/results/distilbert.json")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    set_seed(args.seed)
    splits = load_splits(args.data, args.seed)
    tok = AutoTokenizer.from_pretrained(args.base_model)

    def to_ds(df):
        ds = Dataset.from_pandas(df[["description", "label"]].rename(columns={"label": "labels"}), preserve_index=False)
        return ds.map(lambda b: tok(b["description"], truncation=True, max_length=args.max_len), batched=True)

    train_ds, val_ds, test_ds = (to_ds(splits[k]) for k in ("train", "val", "test"))

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    )

    def metrics(p):
        preds = np.argmax(p.predictions, axis=-1)
        return {"macro_f1": f1_score(p.label_ids, preds, average="macro")}

    targs = TrainingArguments(
        output_dir=str(Path(args.out) / "checkpoints"),
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch * 2,
        weight_decay=0.01,
        warmup_ratio=0.06,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        fp16=torch.cuda.is_available(),
        logging_steps=50,
        report_to=[],
        seed=args.seed,
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tok,
        data_collator=DataCollatorWithPadding(tok),
        compute_metrics=metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=1)],
    )

    t0 = time.time()
    trainer.train()
    train_s = time.time() - t0

    out = trainer.predict(test_ds)
    preds = np.argmax(out.predictions, axis=-1)
    y = out.label_ids
    macro_f1 = f1_score(y, preds, average="macro")
    report = classification_report(y, preds, target_names=LABELS, digits=4, output_dict=True)
    print(classification_report(y, preds, target_names=LABELS, digits=4))
    print(f"DistilBERT macro-F1: {macro_f1:.4f}  (train {train_s/60:.1f} min)")

    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    Path(args.metrics_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics_out).write_text(json.dumps({
        "model": args.base_model,
        "macro_f1": round(float(macro_f1), 4),
        "per_class_f1": {k: round(report[k]["f1-score"], 4) for k in LABELS},
        "confusion_matrix": {"labels": LABELS, "matrix": confusion_matrix(y, preds).tolist()},
        "n_train": len(train_ds),
        "n_test": len(test_ds),
        "epochs": args.epochs,
        "max_len": args.max_len,
        "train_seconds": round(train_s, 1),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
