"""Normalize scanner output (Trivy, pip-audit, Semgrep, npm audit, any SARIF
incl. gitleaks/Checkov) into one finding shape for ranking and triage."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_CVE = re.compile(r"CVE-\d{4}-\d{4,}")


def _sev(value: Any) -> str:
    v = str(value or "").upper()
    return {
        "ERROR": "HIGH", "WARNING": "MEDIUM", "NOTE": "LOW", "INFO": "LOW",
        "MODERATE": "MEDIUM", "NEGLIGIBLE": "LOW",
    }.get(v, v if v in SEVERITIES else "UNKNOWN")


def _cvss_band(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW" if score > 0 else "UNKNOWN"


def _finding(**kw) -> dict:
    f = {
        "tool": "", "kind": "code", "rule_id": "", "cve": None, "title": "", "description": "",
        "package": None, "installed_version": None, "fixed_version": None,
        "file": None, "line": None, "scanner_severity": "UNKNOWN", "url": None, "fix_hint": None,
    }
    f.update({k: v for k, v in kw.items() if v is not None})
    if not f["cve"]:
        m = _CVE.search(" ".join(str(f[k] or "") for k in ("rule_id", "title", "description")))
        f["cve"] = m.group(0) if m else None
    key = "|".join(str(f[k]) for k in ("tool", "rule_id", "package", "installed_version", "file", "line"))
    f["id"] = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f


def parse_trivy(doc: dict) -> list[dict]:
    out = []
    for res in doc.get("Results", []) or []:
        for v in res.get("Vulnerabilities", []) or []:
            out.append(_finding(
                tool="trivy", kind="dependency", rule_id=v.get("VulnerabilityID", ""),
                title=v.get("Title") or v.get("VulnerabilityID", ""), description=v.get("Description", ""),
                package=v.get("PkgName"), installed_version=v.get("InstalledVersion"),
                fixed_version=(v.get("FixedVersion") or "").split(",")[0].strip() or None,
                file=res.get("Target"), scanner_severity=_sev(v.get("Severity")), url=v.get("PrimaryURL"),
            ))
    return out


def parse_pip_audit(doc: Any) -> list[dict]:
    deps = doc.get("dependencies", []) if isinstance(doc, dict) else doc
    out = []
    for d in deps or []:
        for v in d.get("vulns", []) or []:
            aliases = v.get("aliases", []) or []
            cve = next((a for a in aliases if a.startswith("CVE-")), None)
            fixes = v.get("fix_versions") or []
            out.append(_finding(
                tool="pip-audit", kind="dependency", rule_id=v.get("id", ""), cve=cve,
                title=f"{d.get('name')} {d.get('version')}: {v.get('id')}", description=v.get("description", ""),
                package=d.get("name"), installed_version=d.get("version"), fixed_version=fixes[0] if fixes else None,
                file="requirements.txt",
            ))
    return out


def parse_semgrep(doc: dict) -> list[dict]:
    out = []
    for r in doc.get("results", []):
        extra = r.get("extra", {})
        meta = extra.get("metadata", {}) or {}
        cwe = meta.get("cwe")
        cwe_txt = " ".join(cwe) if isinstance(cwe, list) else (cwe or "")
        out.append(_finding(
            tool="semgrep", kind="code", rule_id=r.get("check_id", ""),
            title=r.get("check_id", "").split(".")[-1], description=f"{extra.get('message', '')} {cwe_txt}".strip(),
            file=r.get("path"), line=r.get("start", {}).get("line"), scanner_severity=_sev(extra.get("severity")),
        ))
    return out


def parse_npm_audit(doc: dict) -> list[dict]:
    out = []
    for name, v in (doc.get("vulnerabilities") or {}).items():
        for via in v.get("via", []):
            if not isinstance(via, dict):
                continue  # transitive pointer to another package
            fix = v.get("fixAvailable")
            fixed = fix.get("version") if isinstance(fix, dict) else None
            out.append(_finding(
                fix_hint="npm audit fix" if fix is True else ("npm audit fix --force (breaking)" if isinstance(fix, dict) and fix.get("isSemVerMajor") else None),
                tool="npm-audit", kind="dependency", rule_id=str(via.get("source") or via.get("url", "")),
                title=via.get("title", name), description=via.get("title", ""), package=name,
                installed_version=via.get("range"), fixed_version=fixed, file="frontend/package-lock.json",
                scanner_severity=_sev(via.get("severity") or v.get("severity")), url=via.get("url"),
            ))
    return out


def parse_sarif(doc: dict) -> list[dict]:
    out = []
    for run in doc.get("runs", []):
        driver = run.get("tool", {}).get("driver", {})
        tool = (driver.get("name") or "sarif").lower()
        rules = {r.get("id"): r for r in driver.get("rules", []) or []}
        kind = "secret" if "gitleaks" in tool else "iac" if "checkov" in tool else "dependency" if "trivy" in tool else "code"
        for res in run.get("results", []):
            rid = res.get("ruleId", "")
            rule = rules.get(rid, {})
            props = rule.get("properties", {}) or {}
            sev = "UNKNOWN"
            if props.get("security-severity"):
                try:
                    sev = _cvss_band(float(props["security-severity"]))
                except ValueError:
                    pass
            if sev == "UNKNOWN":
                sev = _sev(res.get("level") or rule.get("defaultConfiguration", {}).get("level"))
            loc = (res.get("locations") or [{}])[0].get("physicalLocation", {})
            desc = (rule.get("fullDescription") or {}).get("text") or (rule.get("shortDescription") or {}).get("text") or ""
            out.append(_finding(
                tool=tool, kind=kind, rule_id=rid, title=(res.get("message") or {}).get("text", rid)[:200],
                description=desc, file=loc.get("artifactLocation", {}).get("uri"),
                line=loc.get("region", {}).get("startLine"),
                scanner_severity="CRITICAL" if kind == "secret" else sev, url=rule.get("helpUri"),
            ))
    return out


def parse_document(doc: Any) -> list[dict]:
    """Auto-detect the scanner format."""
    if isinstance(doc, dict):
        if isinstance(doc.get("runs"), list):
            return parse_sarif(doc)
        if "Results" in doc or doc.get("ArtifactType"):
            return parse_trivy(doc)
        if "results" in doc and "errors" in doc:
            return parse_semgrep(doc)
        if "vulnerabilities" in doc and "auditReportVersion" in doc:
            return parse_npm_audit(doc)
        if "dependencies" in doc:
            return parse_pip_audit(doc)
        if "findings" in doc:  # already normalized
            return list(doc["findings"])
    if isinstance(doc, list) and doc and "vulns" in doc[0]:
        return parse_pip_audit(doc)
    raise ValueError("Unrecognized scanner output format")


def load_findings(paths: Iterable[str | Path]) -> list[dict]:
    seen, out = set(), []
    for p in paths:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        for f in parse_document(doc):
            if f["id"] not in seen:
                seen.add(f["id"])
                out.append(f)
    return out
