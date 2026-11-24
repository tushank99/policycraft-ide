#!/usr/bin/env python3
"""Rank scanner findings with the CVE-severity model.

    python -m ml.rank_findings trivy.json semgrep.json pip-audit.json --top 20 --json ranked.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ml.findings import load_findings
from ml.severity_model import SeverityPredictor, rank_findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--backend", choices=["distilbert", "baseline", "heuristic"])
    args = ap.parse_args()

    predictor = SeverityPredictor(prefer=args.backend)
    ranked = rank_findings(load_findings(args.files), predictor)
    print(f"{len(ranked)} findings ranked with backend={predictor.backend}\n")
    print(f"{'#':>3} {'risk':>5} {'pred':<8} {'scanner':<8} {'tool':<10} finding")
    for f in ranked[: args.top]:
        where = f.get("package") or f.get("file") or ""
        print(f"{f['rank']:>3} {f['risk_score']:>5.2f} {f['predicted_severity']:<8} {f['scanner_severity']:<8} "
              f"{f['tool'][:10]:<10} {f.get('cve') or f['rule_id']} {where}")
    if args.json:
        args.json.write_text(json.dumps({"backend": predictor.backend, "findings": ranked}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
