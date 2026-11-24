"""CVE-description -> severity predictor with graceful fallback.

Backends, in order of preference:
  1. fine-tuned DistilBERT  (ml/models/distilbert-cve-severity, needs torch+transformers)
  2. TF-IDF + logistic regression baseline (ml/models/baseline_tfidf_lr.joblib)
  3. keyword heuristic (always available, so CI/agents never break)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
# Mid-points of the CVSS v3 bands; used to turn probabilities into an expected score.
SEVERITY_SCORE = {"LOW": 2.0, "MEDIUM": 5.5, "HIGH": 8.0, "CRITICAL": 9.5, "UNKNOWN": 5.0}

_ROOT = Path(__file__).resolve().parent
DEFAULT_DISTILBERT = Path(os.environ.get("SEVERITY_MODEL_DIR", _ROOT / "models" / "distilbert-cve-severity"))
DEFAULT_BASELINE = Path(os.environ.get("SEVERITY_BASELINE", _ROOT / "models" / "baseline_tfidf_lr.joblib"))

_HEURISTICS = [
    (r"remote code execution|arbitrary code|command injection|deserializ|unauthenticated.*(execute|rce)", "CRITICAL"),
    (r"sql injection|privilege escalation|authentication bypass|hard-?coded (secret|credential|password|key)|"
     r"path traversal|ssrf|server-side request forgery|secret|private key|api key|token", "HIGH"),
    (r"cross-site|xss|denial of service|dos\b|redos|information disclosure|open redirect|csrf|"
     r"prototype pollution|timeout|wildcard", "MEDIUM"),
]


class SeverityPredictor:
    def __init__(self, model_dir: Path | str = DEFAULT_DISTILBERT, baseline_path: Path | str = DEFAULT_BASELINE,
                 prefer: str | None = None):
        self.backend = "heuristic"
        self._tok = self._model = self._pipe = None
        prefer = prefer or os.environ.get("SEVERITY_BACKEND")
        model_dir, baseline_path = Path(model_dir), Path(baseline_path)

        if prefer in (None, "distilbert") and (model_dir / "config.json").exists():
            try:
                import torch  # noqa: F401
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                self._tok = AutoTokenizer.from_pretrained(model_dir)
                self._model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
                self.backend = "distilbert"
                return
            except Exception as e:  # pragma: no cover - depends on local install
                print(f"[severity] DistilBERT unavailable ({e}); falling back")
        if prefer in (None, "distilbert", "baseline") and baseline_path.exists():
            try:
                import joblib

                self._pipe = joblib.load(baseline_path)
                self.backend = "baseline"
            except Exception as e:  # pragma: no cover
                print(f"[severity] baseline unavailable ({e}); using heuristic")

    def predict_proba(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []
        if self.backend == "distilbert":
            import torch

            out = []
            for i in range(0, len(texts), 32):
                enc = self._tok(texts[i:i + 32], truncation=True, max_length=256, padding=True, return_tensors="pt")
                with torch.no_grad():
                    probs = torch.softmax(self._model(**enc).logits, dim=-1).tolist()
                id2label = self._model.config.id2label
                out += [{id2label[j]: float(p) for j, p in enumerate(row)} for row in probs]
            return out
        if self.backend == "baseline":
            classes = list(self._pipe.classes_)
            return [{str(c): float(p) for c, p in zip(classes, row)} for row in self._pipe.predict_proba(texts)]
        return [self._heuristic(t) for t in texts]

    @staticmethod
    def _heuristic(text: str) -> dict[str, float]:
        t = (text or "").lower()
        label = "LOW"
        for pattern, sev in _HEURISTICS:
            if re.search(pattern, t):
                label = sev
                break
        return {l: (0.7 if l == label else 0.1) for l in LABELS}

    def predict(self, texts: list[str]) -> list[dict]:
        results = []
        for probs in self.predict_proba(texts):
            label = max(probs, key=probs.get)
            expected = sum(SEVERITY_SCORE[l] * probs.get(l, 0.0) for l in LABELS)
            results.append({"label": label, "confidence": round(float(probs[label]), 4),
                            "expected_score": round(float(expected), 3), "probs": {k: round(v, 4) for k, v in probs.items()}})
        return results


def finding_text(f: dict) -> str:
    return " ".join(x for x in (f.get("title"), f.get("description")) if x)[:2000]


def rank_findings(findings: list[dict], predictor: SeverityPredictor | None = None,
                  model_weight: float = 0.7) -> list[dict]:
    """Attach model predictions and sort findings, most urgent first.

    risk = model_weight * model_expected_score + (1 - model_weight) * scanner_score
    Secrets are pinned to the top (a leaked key is exploitable immediately).
    """
    predictor = predictor or SeverityPredictor()
    preds = predictor.predict([finding_text(f) for f in findings])
    ranked = []
    for f, p in zip(findings, preds):
        scanner = f.get("scanner_severity", "UNKNOWN")
        if scanner == "UNKNOWN":
            risk = p["expected_score"]
        else:
            risk = model_weight * p["expected_score"] + (1 - model_weight) * SEVERITY_SCORE[scanner]
        if f.get("kind") == "secret":
            risk = 10.0
        ranked.append({**f, "predicted_severity": p["label"], "prediction_confidence": p["confidence"],
                       "risk_score": round(risk, 3), "severity_backend": predictor.backend})
    ranked.sort(key=lambda x: (x["risk_score"], x.get("fixed_version") is not None), reverse=True)
    for i, f in enumerate(ranked, 1):
        f["rank"] = i
    return ranked
