# P4 results: CVE severity classification

Same stratified test split (seed 42) for both models.

| Model | Macro-F1 | F1 LOW | F1 MEDIUM | F1 HIGH | F1 CRITICAL | n_test | Train time |
|---|---|---|---|---|---|---|---|
| TF-IDF + LogReg (baseline) | **0.7034** | 0.730 | 0.698 | 0.632 | 0.753 | 600 | 6.2s |
| DistilBERT (fine-tuned) | _not run yet_ | | | | | | |
