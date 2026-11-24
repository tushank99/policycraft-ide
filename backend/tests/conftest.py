import os
import sys

# Make backend service modules importable from tests/ the same way they are
# laid out inside each Lambda ZIP (flat module names + a `shared` package).
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_BACKEND)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

for p in (
    os.path.join(_BACKEND, "validation_service"),
    os.path.join(_BACKEND, "policy_service"),
    os.path.join(_BACKEND, "generation_orchestrator"),
    os.path.join(_BACKEND, "triage_agents"),
    _BACKEND,
    _ROOT,
    _HERE,
):
    if p not in sys.path:
        sys.path.insert(0, p)
