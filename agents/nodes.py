"""Agent nodes for the triage graph.

supervisor   -> decides which agent runs next (deterministic, goal-driven)
triage       -> reads scanner JSON, ranks findings with the P4 severity model
remediation  -> proposes fixes (deterministic version bumps + LLM explanation, CVE links)
approval     -> HUMAN-IN-THE-LOOP gate: LangGraph interrupt() before any automatic fix
apply_fixes  -> applies ONLY human-approved dependency bumps
reporting    -> writes the markdown summary and posts it as a PR comment
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.types import interrupt

from agents import llm
from ml.findings import load_findings
from ml.severity_model import SeverityPredictor, rank_findings

NVD_URL = "https://nvd.nist.gov/vuln/detail/{}"


class TriageState(TypedDict, total=False):
    # inputs
    scan_files: list[str]
    repo_root: str
    approval_mode: Literal["interactive", "propose", "preapproved"]
    preapproved_ids: list[str]
    max_remediations: int
    # progress
    findings: list[dict]
    remediations: list[dict]
    approval: dict
    applied_fixes: list[dict]
    report_markdown: str
    report_posted: str
    started_at: float
    metrics: dict
    log: list[str]
    next: str


def _log(state: TriageState, msg: str) -> list[str]:
    return [*state.get("log", []), msg]


# ─── Supervisor ──────────────────────────────────────────────────────────────
def supervisor(state: TriageState) -> dict:
    """Goal: every finding triaged, every actionable one has a fix proposal,
    no fix applied without approval, and a report delivered."""
    if "findings" not in state:
        nxt = "triage"
    elif "remediations" not in state:
        nxt = "remediation"
    elif "approval" not in state:
        nxt = "approval" if any(r.get("auto_fix") for r in state["remediations"]) else "reporting"
    elif state["approval"].get("approved_ids") and "applied_fixes" not in state:
        nxt = "apply_fixes"
    elif "report_markdown" not in state:
        nxt = "reporting"
    else:
        nxt = "end"
    return {"next": nxt, "log": _log(state, f"supervisor -> {nxt}")}


# ─── Triage agent ────────────────────────────────────────────────────────────
def triage(state: TriageState) -> dict:
    findings = load_findings(state.get("scan_files", []))
    predictor = SeverityPredictor()
    ranked = rank_findings(findings, predictor)
    return {
        "findings": ranked,
        "log": _log(state, f"triage: {len(ranked)} findings ranked (severity backend={predictor.backend})"),
    }


# ─── Remediation agent ───────────────────────────────────────────────────────
_SYSTEM = (
    "You are an application-security engineer. For each finding, give a concise, concrete fix. "
    "Respond ONLY with JSON: {\"fixes\": [{\"id\": str, \"summary\": str, \"steps\": [str]}]}. "
    "Max 3 steps per finding. Never invent package versions; use the provided fixed_version when present."
)


def _deterministic_fix(f: dict) -> dict | None:
    if f.get("kind") == "dependency" and f.get("package") and f.get("fixed_version"):
        return {"type": "bump", "package": f["package"], "from": f.get("installed_version"),
                "to": f["fixed_version"], "target": f.get("file")}
    return None


def _template_text(f: dict) -> tuple[str, list[str]]:
    kind = f.get("kind")
    if kind == "dependency" and f.get("fixed_version"):
        return (f"Upgrade {f['package']} to {f['fixed_version']} or later.",
                [f"Bump {f['package']} from {f.get('installed_version')} to {f['fixed_version']}", "Re-run tests and scanners"])
    if kind == "dependency" and f.get("fix_hint"):
        return (f"Fixed upstream; run `{f['fix_hint']}` for {f.get('package')}.",
                [f"Run `{f['fix_hint']}` in the package directory", "Commit the lockfile and re-run tests"])
    if kind == "dependency":
        return (f"No fixed release of {f.get('package')} yet; mitigate or accept with a review date.",
                ["Check if the vulnerable code path is reachable", "Add to the accepted-risk list with justification"])
    if kind == "secret":
        return ("Revoke and rotate the leaked credential, then purge it from git history.",
                ["Revoke/rotate the credential at the provider", "Move it to SSM Parameter Store / GitHub secrets",
                 "Rewrite history (git filter-repo) if the repo is public"])
    return (f"Review {f.get('file')}:{f.get('line')} for rule {f.get('rule_id')}.",
            ["Apply the rule's recommended secure pattern", "Add a regression test"])


def remediation(state: TriageState) -> dict:
    limit = state.get("max_remediations", 10)
    top = state["findings"][:limit]
    llm_text: dict[str, dict] = {}
    provider = llm.provider_name()
    note = provider

    if top and provider != "offline":
        brief = [{k: f.get(k) for k in ("id", "tool", "kind", "rule_id", "cve", "title", "package",
                                         "installed_version", "fixed_version", "file", "line")}
                 | {"description": (f.get("description") or "")[:400]} for f in top]
        try:
            raw = llm.complete(_SYSTEM, json.dumps({"findings": brief}))
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
            for item in json.loads(raw).get("fixes", []):
                if isinstance(item, dict) and item.get("id"):
                    llm_text[item["id"]] = item
        except Exception as e:  # LLM is advisory; templates cover failures
            note = f"{provider} failed ({type(e).__name__}); used templates"

    remediations = []
    for f in top:
        summary, steps = _template_text(f)
        if f["id"] in llm_text:
            summary = str(llm_text[f["id"]].get("summary") or summary)[:400]
            steps = [str(s)[:300] for s in (llm_text[f["id"]].get("steps") or steps)][:3]
        remediations.append({
            "finding_id": f["id"],
            "rank": f["rank"],
            "cve_url": NVD_URL.format(f["cve"]) if f.get("cve") else f.get("url"),
            "summary": summary,
            "steps": steps,
            "auto_fix": _deterministic_fix(f),
        })
    return {"remediations": remediations,
            "log": _log(state, f"remediation: {len(remediations)} proposals via {note}")}


# ─── Human approval gate ─────────────────────────────────────────────────────
def approval(state: TriageState) -> dict:
    candidates = [r for r in state["remediations"] if r.get("auto_fix")]
    ids = [r["finding_id"] for r in candidates]
    mode = state.get("approval_mode", "propose")

    if mode == "preapproved":
        # A human already chose these ids (CLI flag / maintainer PR command).
        approved = [i for i in state.get("preapproved_ids", []) if i in ids]
        decision = {"approved_ids": approved, "decided_by": "preapproved", "pending": [i for i in ids if i not in approved]}
    elif mode == "interactive":
        # Pauses the graph; resumed with Command(resume={"approved_ids": [...]})
        answer = interrupt({"question": "Approve automatic fixes?", "candidates": [
            {"finding_id": r["finding_id"], **r["auto_fix"]} for r in candidates]})
        approved = [i for i in (answer or {}).get("approved_ids", []) if i in ids]
        decision = {"approved_ids": approved, "decided_by": "human", "pending": [i for i in ids if i not in approved]}
    else:  # propose: never change code, list what awaits approval
        decision = {"approved_ids": [], "decided_by": "nobody (propose mode)", "pending": ids}

    return {"approval": decision,
            "log": _log(state, f"approval: {len(decision['approved_ids'])} approved, {len(decision['pending'])} pending")}


# ─── Apply approved fixes ────────────────────────────────────────────────────
def _bump_requirements(path: Path, pkg: str, to: str) -> bool:
    text = path.read_text(encoding="utf-8")
    pat = re.compile(rf"(?im)^({re.escape(pkg)})\s*(==|>=|~=)\s*[\w.\-]+")
    new, n = pat.subn(lambda m: f"{m.group(1)}{'>=' if m.group(2) == '>=' else '=='}{to}", text)
    if n:
        path.write_text(new, encoding="utf-8")
    return bool(n)


def _bump_package_json(path: Path, pkg: str, to: str) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for section in ("dependencies", "devDependencies"):
        if pkg in data.get(section, {}):
            data[section][pkg] = f"^{to}"
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def apply_fixes(state: TriageState) -> dict:
    root = Path(state.get("repo_root", "."))
    approved = set(state["approval"]["approved_ids"])
    applied = []
    for r in state["remediations"]:
        fix = r.get("auto_fix")
        if r["finding_id"] not in approved or not fix:  # hard guarantee: nothing unapproved
            continue
        targets = list(root.rglob("requirements*.txt")) + [p for p in root.rglob("package.json") if "node_modules" not in p.parts]
        for t in targets:
            if any(part in ("venv", ".venv", "node_modules") for part in t.parts):
                continue
            ok = _bump_package_json(t, fix["package"], fix["to"]) if t.name == "package.json" \
                else _bump_requirements(t, fix["package"], fix["to"])
            if ok:
                applied.append({"finding_id": r["finding_id"], "file": str(t.relative_to(root)), **fix})
    return {"applied_fixes": applied, "log": _log(state, f"apply_fixes: {len(applied)} file edits")}


# ─── Reporting agent ─────────────────────────────────────────────────────────
MARKER = "<!-- policycraft-triage-report -->"


def build_report(state: TriageState, elapsed: float) -> str:
    findings = state.get("findings", [])
    rem = {r["finding_id"]: r for r in state.get("remediations", [])}
    appr = state.get("approval", {})
    applied = {a["finding_id"] for a in state.get("applied_fixes", [])}
    counts = {s: sum(1 for f in findings if f["predicted_severity"] == s) for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    backend = findings[0]["severity_backend"] if findings else "n/a"

    lines = [
        MARKER,
        "## 🛡️ PolicyCraft security triage",
        "",
        f"**{len(findings)} findings** · predicted severity: "
        + " · ".join(f"{k.title()} {v}" for k, v in counts.items())
        + f" · model: `{backend}` · remediation LLM: `{llm.provider_name()}`",
        "",
    ]
    if findings:
        lines += ["| # | Risk | Predicted | Scanner | Tool | Finding | Fix | Status |",
                  "|---|---|---|---|---|---|---|---|"]
        for f in findings[:15]:
            r = rem.get(f["id"], {})
            ref = f.get("cve") or f.get("rule_id")
            link = f"[{ref}]({r['cve_url']})" if r.get("cve_url") else f"`{ref}`"
            where = f.get("package") or (f"{f.get('file')}:{f.get('line')}" if f.get("line") else f.get("file")) or ""
            if f["id"] in applied:
                status = "✅ fixed (approved)"
            elif f["id"] in appr.get("pending", []):
                status = f"⏳ needs approval `{f['id']}`"
            elif r:
                status = "📝 manual"
            else:
                status = "—"
            fix = (r.get("summary") or "").replace("|", "\\|")[:140]
            lines.append(f"| {f['rank']} | {f['risk_score']:.1f} | {f['predicted_severity']} | {f['scanner_severity']} "
                         f"| {f['tool']} | {link} {where} | {fix} | {status} |")
        if len(findings) > 15:
            lines.append(f"\n_{len(findings) - 15} lower-risk findings omitted._")
    if appr.get("pending"):
        lines += ["", "### Human approval required",
                  "No automatic fix is applied without approval. A maintainer can approve with:",
                  "```", f"/approve-fixes {' '.join(appr['pending'])}", "```"]
    lines += ["", f"<sub>Processed {len(findings)} findings in {elapsed:.1f}s.</sub>"]
    return "\n".join(lines)


def reporting(state: TriageState) -> dict:
    elapsed = time.time() - state.get("started_at", time.time())
    md = build_report(state, elapsed)
    from agents.github import post_pr_comment  # local import keeps tests offline

    where = post_pr_comment(md, MARKER)
    metrics = {
        "findings_processed": len(state.get("findings", [])),
        "remediations": len(state.get("remediations", [])),
        "approved_fixes": len(state.get("approval", {}).get("approved_ids", [])),
        "applied_fixes": len(state.get("applied_fixes", [])),
        "seconds_per_report": round(elapsed, 2),
    }
    return {"report_markdown": md, "report_posted": where, "metrics": metrics,
            "log": _log(state, f"reporting: report delivered to {where}")}


def route(state: TriageState) -> Any:
    return state["next"]
