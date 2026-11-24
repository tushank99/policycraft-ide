#!/usr/bin/env python3
"""Run the multi-agent triage.

  # CI / PR: rank + propose, never change code, post PR comment
  python -m agents.run scans/*.json --mode propose

  # Local, human in the loop: the graph pauses and asks before fixing
  python -m agents.run scans/*.json --mode interactive

  # A maintainer already approved specific ids (e.g. via "/approve-fixes a1b2 c3d4")
  python -m agents.run scans/*.json --mode preapproved --approve a1b2c3d4e5f6 ...
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from langgraph.types import Command

try:
    from langgraph.checkpoint.memory import InMemorySaver as _Saver
except ImportError:  # older langgraph
    from langgraph.checkpoint.memory import MemorySaver as _Saver

from agents.graph import build_graph


def _ask(payload: dict) -> dict:
    print("\n=== HUMAN APPROVAL REQUIRED ===")
    for c in payload["candidates"]:
        print(f"  [{c['finding_id']}] bump {c['package']} {c.get('from')} -> {c['to']}  ({c.get('target')})")
    raw = input("Approve which ids? (space-separated, 'all', or empty for none): ").strip()
    ids = [c["finding_id"] for c in payload["candidates"]] if raw == "all" else raw.split()
    return {"approved_ids": ids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scans", nargs="+", help="scanner JSON/SARIF files")
    ap.add_argument("--mode", choices=["propose", "interactive", "preapproved"], default="propose")
    ap.add_argument("--approve", nargs="*", default=[], help="finding ids approved by a human (preapproved mode)")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--max-remediations", type=int, default=10)
    ap.add_argument("--out", type=Path, default=Path("triage-out"))
    args = ap.parse_args()

    scans = [s for s in args.scans if Path(s).is_file()]
    graph = build_graph(checkpointer=_Saver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 30}
    state = {
        "scan_files": scans,
        "repo_root": args.repo_root,
        "approval_mode": args.mode,
        "preapproved_ids": args.approve,
        "max_remediations": args.max_remediations,
        "started_at": time.time(),
        "log": [],
    }

    result = graph.invoke(state, config)
    while "__interrupt__" in result:  # human-in-the-loop pause
        payload = result["__interrupt__"][0].value
        result = graph.invoke(Command(resume=_ask(payload)), config)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(result.get("report_markdown", ""), encoding="utf-8")
    (args.out / "ranked_findings.json").write_text(json.dumps(result.get("findings", []), indent=2))
    (args.out / "metrics.json").write_text(json.dumps(result.get("metrics", {}), indent=2))
    for line in result.get("log", []):
        print(" -", line)
    print(json.dumps(result.get("metrics", {}), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
