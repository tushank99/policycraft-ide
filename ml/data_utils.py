"""Shared dataset loading + a fixed stratified split so baseline and DistilBERT
are evaluated on exactly the same test CVEs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
LABEL2ID = {label: i for i, label in enumerate(LABELS)}
ID2LABEL = {i: label for label, i in LABEL2ID.items()}


def load_splits(csv_path: str | Path, seed: int = 42) -> dict[str, pd.DataFrame]:
    """80/10/10 stratified split. The split is written next to the CSV the first
    time and re-used afterwards, so every model sees the same partitions."""
    csv_path = Path(csv_path)
    split_path = csv_path.with_name(csv_path.stem + f".split{seed}.csv")
    df = pd.read_csv(csv_path).dropna(subset=["description", "severity"])
    df = df[df["severity"].isin(LABELS)].drop_duplicates("cve_id").reset_index(drop=True)

    if split_path.exists():
        split = pd.read_csv(split_path)
        df = df.merge(split, on="cve_id", how="inner")
    else:
        train, rest = train_test_split(df, test_size=0.2, stratify=df["severity"], random_state=seed)
        val, test = train_test_split(rest, test_size=0.5, stratify=rest["severity"], random_state=seed)
        df = pd.concat([train.assign(split="train"), val.assign(split="val"), test.assign(split="test")])
        df[["cve_id", "split"]].to_csv(split_path, index=False)

    df["label"] = df["severity"].map(LABEL2ID)
    return {name: df[df["split"] == name].reset_index(drop=True) for name in ("train", "val", "test")}
