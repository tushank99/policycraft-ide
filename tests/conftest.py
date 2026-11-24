import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("REMEDIATION_LLM", "offline")
os.environ.setdefault("SEVERITY_BACKEND", "heuristic")
for k in ("GITHUB_TOKEN", "PR_NUMBER"):
    os.environ.pop(k, None)
