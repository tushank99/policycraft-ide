import json
import re
from typing import List, Dict, Any

class ManifestComplianceEngine:
    @staticmethod
    def validate_manifests(files: Dict[str, str], spec: dict) -> List[Dict[str, Any]]:
        """Validates all infrastructure, dependency, and container files."""
        results = []
        
        requested_artifacts = spec.get("selectedArtifacts", spec.get("artifacts", []))

        # 1. Dependency Pinning
        if "source" in requested_artifacts:
            results.extend(ManifestComplianceEngine._check_dependencies(files))

        # 2. Dockerfile Compliance
        if "dockerfile" in requested_artifacts:
            results.extend(ManifestComplianceEngine._check_dockerfile(files))

        # 3. Kubernetes Probes Alignment
        if "k8s-manifests" in requested_artifacts:
            results.extend(ManifestComplianceEngine._check_kubernetes(files))

        return results

    @staticmethod
    def _check_dependencies(files: Dict[str, str]) -> List[Dict[str, Any]]:
        results = []
        
        # requirements.txt (Python)
        if "requirements.txt" in files:
            unpinned = []
            for line in files["requirements.txt"].split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # If there's no '==' it's either unpinned or uses a risky range (>=, ~>)
                if '==' not in line and not line.startswith('-'):
                    unpinned.append(line)
            
            if unpinned:
                results.append(ManifestComplianceEngine._build_finding(
                    rule="Strict Dependency Pinning (Python)",
                    status="FAIL",
                    severity="mandatory",
                    message=f"Found unpinned dependencies in requirements.txt: {', '.join(unpinned)}",
                    remediation="Use exact version pins (e.g., fastapi==0.111.0) to prevent supply chain drift."
                ))

        # package.json (Node.js/TypeScript)
        if "package.json" in files:
            try:
                pkg = json.loads(files["package.json"])
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                
                # Check for risky modifiers that allow automatic minor/patch updates
                unpinned = [
                    pkg_name for pkg_name, ver in deps.items() 
                    if any(c in ver for c in ['^', '~', '>', '<', '*'])
                ]
                
                if unpinned:
                    results.append(ManifestComplianceEngine._build_finding(
                        rule="Strict Dependency Pinning (Node.js)",
                        status="FAIL",
                        severity="mandatory",
                        message=f"Found loose version ranges in package.json: {', '.join(unpinned)}",
                        remediation="Remove '^' and '~' modifiers. Pin to exact semver versions to guarantee reproducibility."
                    ))
            except json.JSONDecodeError:
                results.append(ManifestComplianceEngine._build_finding(
                    rule="Manifest Parseability",
                    status="FAIL",
                    severity="mandatory",
                    message="package.json contains invalid JSON data."
                ))

        if not results and ("requirements.txt" in files or "package.json" in files):
             results.append(ManifestComplianceEngine._build_finding(
                rule="Dependency Pinning", status="PASS", severity="mandatory", message="All dependencies are strictly pinned."
             ))
        return results

    @staticmethod
    def _check_dockerfile(files: Dict[str, str]) -> List[Dict[str, Any]]:
        results = []
        dockerfile_content = files.get("Dockerfile", "") or files.get("dockerfile", "")
        
        if dockerfile_content:
            # Enforce Multi-stage build (must have at least 2 FROM instructions)
            from_count = len(re.findall(r"^FROM\s+", dockerfile_content, re.MULTILINE | re.IGNORECASE))
            if from_count < 2:
                results.append(ManifestComplianceEngine._build_finding(
                    rule="Dockerfile Multi-Stage Build",
                    status="FAIL",
                    severity="mandatory",
                    message=f"Dockerfile has only {from_count} FROM directive(s).",
                    remediation="Use a multi-stage build (builder stage + minimal runtime stage) to reduce image footprint and attack surface."
                ))
            
            # Enforce Non-root user execution
            if not re.search(r"^USER\s+(?!root\b)", dockerfile_content, re.MULTILINE | re.IGNORECASE):
                results.append(ManifestComplianceEngine._build_finding(
                    rule="Dockerfile Non-Root Execution",
                    status="FAIL",
                    severity="mandatory",
                    message="No valid non-root USER directive found in Dockerfile.",
                    remediation="Add 'USER appuser' or a specific UID before the ENTRYPOINT/CMD to prevent root execution."
                ))

        if not results and dockerfile_content:
             results.append(ManifestComplianceEngine._build_finding(
                rule="Dockerfile Compliance", status="PASS", severity="mandatory", message="Dockerfile is multi-stage and secure."
             ))
        return results

    @staticmethod
    def _check_kubernetes(files: Dict[str, str]) -> List[Dict[str, Any]]:
        results = []
        k8s_content = files.get("deployment.yaml", "") or files.get("k8s-manifests", "") or files.get("k8s/deployment.yaml", "")
        
        if k8s_content:
            if "/healthz" not in k8s_content or "livenessProbe" not in k8s_content:
                results.append(ManifestComplianceEngine._build_finding(
                    rule="Kubernetes Liveness Probe Alignment",
                    status="FAIL",
                    severity="mandatory",
                    message="Missing livenessProbe configured with /healthz.",
                    remediation="Define a livenessProbe using an HTTP GET on the /healthz endpoint."
                ))
            
            if "/readyz" not in k8s_content or "readinessProbe" not in k8s_content:
                results.append(ManifestComplianceEngine._build_finding(
                    rule="Kubernetes Readiness Probe Alignment",
                    status="FAIL",
                    severity="mandatory",
                    message="Missing readinessProbe configured with /readyz.",
                    remediation="Define a readinessProbe using an HTTP GET on the /readyz endpoint."
                ))

        if not results and k8s_content:
             results.append(ManifestComplianceEngine._build_finding(
                rule="Kubernetes Probe Alignment", status="PASS", severity="mandatory", message="Health probes correctly mapped to /healthz and /readyz."
             ))
        return results

    @staticmethod
    def _build_finding(rule: str, status: str, severity: str, message: str, remediation: str = "") -> Dict[str, Any]:
        """Helper to format validation results consistently."""
        finding = {
            "rule": rule,
            "status": status,
            "severity": severity,
            "message": message,
            "engine": "manifest_compliance"
        }
        if status == "FAIL" and remediation:
            finding["remediation"] = remediation
        return finding