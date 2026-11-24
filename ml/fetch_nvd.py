#!/usr/bin/env python3
"""Download a class-balanced sample of public NVD CVE descriptions + CVSS v3 severity.

Uses the NVD CVE API 2.0 (free). Without an API key NVD allows 5 requests per
30 s, so the script sleeps 6.5 s between calls; set NVD_API_KEY to go faster.

    python -m ml.fetch_nvd --per-class 1500 --out ml/data/nvd_cves.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time
from pathlib import Path

import requests

API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
PAGE = 2000


def _get(params: dict, session: requests.Session) -> dict:
    headers = {"User-Agent": "policycraft-ml/1.0"}
    key = os.environ.get("NVD_API_KEY")
    if key:
        headers["apiKey"] = key
    for attempt in range(6):
        r = session.get(API, params=params, headers=headers, timeout=60)
        if r.status_code == 200:
            return r.json()
        wait = 10 * (attempt + 1)
        print(f"  NVD HTTP {r.status_code}, retrying in {wait}s", file=sys.stderr)
        time.sleep(wait)
    r.raise_for_status()
    return {}


def _extract(vuln: dict) -> tuple[str, str, str, str] | None:
    cve = vuln["cve"]
    if cve.get("vulnStatus") in ("Rejected", "Reserved"):
        return None
    desc = next((d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
    if not desc or desc.startswith("** REJECT"):
        return None
    metrics = cve.get("metrics", {})
    for key in ("cvssMetricV31", "cvssMetricV30"):
        for m in metrics.get(key, []):
            sev = m.get("cvssData", {}).get("baseSeverity")
            if sev in LABELS:
                return cve["id"], " ".join(desc.split()), sev, cve.get("published", "")[:10]
    return None


def fetch(per_class: int, seed: int, pause: float) -> list[tuple[str, str, str, str]]:
    rng = random.Random(seed)
    session = requests.Session()
    rows: dict[str, tuple] = {}
    for label in LABELS:
        meta = _get({"cvssV3Severity": label, "resultsPerPage": 1}, session)
        total = meta.get("totalResults", 0)
        time.sleep(pause)
        print(f"{label}: {total} CVEs available, sampling {per_class}")
        # Random pages across the whole history so the sample isn't all from one year.
        starts = list(range(0, total, PAGE))
        rng.shuffle(starts)
        # Spread each class over several pages (different years) so the model
        # can't separate classes by era-specific vocabulary.
        pages = min(len(starts), 5)
        cap = -(-per_class // pages)
        got = 0
        for start in starts:
            taken_here = 0
            data = _get({"cvssV3Severity": label, "resultsPerPage": PAGE, "startIndex": start}, session)
            time.sleep(pause)
            vulns = data.get("vulnerabilities", [])
            rng.shuffle(vulns)
            for v in vulns:
                row = _extract(v)
                if row and row[2] == label and row[0] not in rows:
                    rows[row[0]] = row
                    got += 1
                    taken_here += 1
                    if got >= per_class or (taken_here >= cap and len(starts) > 1):
                        break
            print(f"  page@{start}: {got}/{per_class}")
            if got >= per_class:
                break
    return list(rows.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("ml/data/nvd_cves.csv"))
    args = ap.parse_args()

    pause = 0.8 if os.environ.get("NVD_API_KEY") else 6.5
    rows = fetch(args.per_class, args.seed, pause)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cve_id", "description", "severity", "published"])
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
