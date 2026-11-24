import shutil
from pathlib import Path

import pytest

from ml.findings import load_findings
from ml.severity_model import SeverityPredictor, rank_findings

FIX = Path(__file__).parent / "fixtures"
SCANS = [str(FIX / n) for n in ("trivy.json", "semgrep.json", "gitleaks.sarif", "pip_audit.json")]


def test_all_formats_normalized():
    findings = load_findings(SCANS)
    tools = {f["tool"] for f in findings}
    assert {"trivy", "semgrep", "gitleaks", "pip-audit"} <= tools
    assert len(findings) == 5
    jinja = next(f for f in findings if f.get("package") == "jinja2")
    assert jinja["fixed_version"] == "3.1.4" and jinja["cve"] == "CVE-2024-0002"
    urllib3 = next(f for f in findings if f.get("package") == "urllib3")
    assert urllib3["fixed_version"] == "1.26.19"  # first of comma-separated fixes


def test_ranking_secret_first_then_rce():
    ranked = rank_findings(load_findings(SCANS), SeverityPredictor(prefer="heuristic"))
    assert ranked[0]["kind"] == "secret"
    order = [f.get("package") or f["rule_id"] for f in ranked]
    assert order.index("jinja2") < order.index("urllib3")  # RCE outranks info disclosure
    assert [f["rank"] for f in ranked] == list(range(1, len(ranked) + 1))


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("jinja2==3.1.2\nrequests>=2.31.0\nboto3>=1.34.0\n")
    return tmp_path


def _run(repo, mode, approve=None):
    pytest.importorskip("langgraph")
    from agents.graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": mode}, "recursion_limit": 30}
    state = {"scan_files": SCANS, "repo_root": str(repo), "approval_mode": mode,
             "preapproved_ids": approve or [], "max_remediations": 10, "started_at": 0, "log": []}
    return graph, cfg, graph.invoke(state, cfg)


def test_propose_mode_never_changes_files(repo):
    before = (repo / "backend" / "requirements.txt").read_text()
    _, _, out = _run(repo, "propose")
    assert (repo / "backend" / "requirements.txt").read_text() == before
    assert out["approval"]["approved_ids"] == []
    assert out["approval"]["pending"]  # fixes are listed as awaiting approval
    assert "Human approval required" in out["report_markdown"]
    assert out["metrics"]["findings_processed"] == 5
    assert any("nvd.nist.gov/vuln/detail/CVE-2024-0002" in (r["cve_url"] or "") for r in out["remediations"])


def test_preapproved_only_applies_approved_ids(repo):
    _, _, proposed = _run(repo, "propose")
    jinja_id = next(f["id"] for f in proposed["findings"] if f.get("package") == "jinja2")
    _, _, out = _run(repo, "preapproved", approve=[jinja_id])
    req = (repo / "backend" / "requirements.txt").read_text()
    assert "jinja2==3.1.4" in req
    assert "requests>=2.31.0" in req  # not approved -> untouched
    assert [a["package"] for a in out["applied_fixes"]] == ["jinja2"]


def test_interactive_interrupts_then_resumes(repo):
    from langgraph.types import Command

    graph, cfg, out = _run(repo, "interactive")
    assert "__interrupt__" in out  # paused for a human
    assert (repo / "backend" / "requirements.txt").read_text().startswith("jinja2==3.1.2")
    candidates = out["__interrupt__"][0].value["candidates"]
    req_id = next(c["finding_id"] for c in candidates if c["package"] == "requests")
    final = graph.invoke(Command(resume={"approved_ids": [req_id]}), cfg)
    assert "requests>=2.32.0" in (repo / "backend" / "requirements.txt").read_text()
    assert final["metrics"]["applied_fixes"] == 1


def test_baseline_backend_outputs_plain_floats(tmp_path):
    """sklearn returns numpy floats; LangGraph checkpoints need plain Python types."""
    pytest.importorskip("sklearn")
    import joblib
    from ml.baseline import build

    model = build().fit(["remote code execution flaw", "minor info leak"] * 5, ["CRITICAL", "LOW"] * 5)
    path = tmp_path / "m.joblib"
    joblib.dump(model, path)
    pred = SeverityPredictor(baseline_path=path, prefer="baseline").predict(["remote code execution"])[0]
    assert type(pred["confidence"]) is float and all(type(v) is float for v in pred["probs"].values())
