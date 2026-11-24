#!/usr/bin/env python3
"""Write ml/results/RESULTS.md comparing baseline vs DistilBERT macro-F1."""

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent / "results"


def _load(name):
    p = R / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> int:
    base, bert = _load("baseline"), _load("distilbert")
    labels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    rows = ["| Model | Macro-F1 | " + " | ".join(f"F1 {l}" for l in labels) + " | n_test | Train time |",
            "|---|---|" + "---|" * len(labels) + "---|---|"]
    for name, m in (("TF-IDF + LogReg (baseline)", base), ("DistilBERT (fine-tuned)", bert)):
        if not m:
            rows.append(f"| {name} | _not run yet_ |" + " |" * len(labels) + " | |")
            continue
        rows.append(f"| {name} | **{m['macro_f1']:.4f}** | " + " | ".join(f"{m['per_class_f1'][l]:.3f}" for l in labels)
                    + f" | {m['n_test']} | {m['train_seconds']}s |")
    if base and bert:
        delta = bert["macro_f1"] - base["macro_f1"]
        rows.append(f"\nDistilBERT vs baseline: **{delta:+.4f} macro-F1** ({delta / base['macro_f1'] * 100:+.1f}%).")
    out = "# P4 results: CVE severity classification\n\nSame stratified test split (seed 42) for both models.\n\n" + "\n".join(rows) + "\n"
    (R / "RESULTS.md").write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
