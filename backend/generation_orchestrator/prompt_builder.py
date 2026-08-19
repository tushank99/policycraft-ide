"""Prompt builder for the code generation LLM call.

Constructs a system prompt (role, constraints, output format) and user prompt
(developer's service request) from the resolved generation spec.
"""

try:
    from golden_paths import get_golden_path_spec
except ModuleNotFoundError:
    from backend.generation_orchestrator.golden_paths import get_golden_path_spec


def build_system_prompt(spec: dict) -> str:
    """Build the system prompt from a generation spec."""
    stack = spec["stack"]
    reqs = spec["requirements"]
    artifacts = spec.get("selectedArtifacts", spec.get("artifacts", []))

    constraints = []

    # ── Phase 2: Enterprise Golden Path Resolution ────────────────────────────
    golden_path = get_golden_path_spec(stack["language"], stack.get("framework", ""))

    constraints.append(
        f"- Target Runtime Environment: {golden_path['runtime']}"
    )

    # ── Stack ────────────────────────────────────────────────────────────────
    constraints.append(
        f"- Language: {stack['language']} {stack.get('version', '')}".strip()
    )
    constraints.append(f"- Framework: {stack.get('framework', '')}")

    # ── Architecture ─────────────────────────────────────────────────────────
    arch_pattern = reqs.get("architecturePattern", "")
    if arch_pattern and arch_pattern.lower() != "none":
        constraints.append(
            f"- Architecture: Follow the '{arch_pattern}' layering pattern. "
            "Separate concerns clearly — each layer has a single responsibility. "
            "Never mix business logic with HTTP handling or data access."
        )

    if reqs.get("apiResponseFormat", False):
        constraints.append(
            '- API Response Format: ALL endpoint responses MUST use this standard envelope: '
            '{"data": <payload or null>, "status": "success" | "error", "error": null | "<message>"}. '
            'Never return a raw object directly — always wrap in this structure.'
        )

    # ── Phase 2: Enterprise Observability & OpenTelemetry ─────────────────────
    obs_reqs = reqs.get("openTelemetryEnabled", True)
    if obs_reqs:
        constraints.append(f"- Observability (OpenTelemetry): {golden_path['telemetry_rules']}")

    correlation_header = reqs.get("correlationHeader", "X-Correlation-ID")
    constraints.append(
        f"- Traceability (Correlation ID): {golden_path['correlation_id_rules']} Use header '{correlation_header}'."
    )

    # ── Health endpoint (Phase 2 Golden Path Enforced) ────────────────────────
    health_reqs = reqs.get("healthEndpoint", {})
    if health_reqs.get("enabled", True):
        liveness = health_reqs.get("livenessPath", "/healthz")
        readiness = health_reqs.get("readinessPath", "/readyz")
        constraints.append(
            f"- Kubernetes Health Probes: {golden_path['health_probes']} "
            f"Map Liveness to '{liveness}' and Readiness to '{readiness}'."
        )

    # ── Security ─────────────────────────────────────────────────────────────
    auth_type = reqs.get("authType", "JWT")
    jwt_expiry = reqs.get("jwtExpiry", 3600)
    rbac = reqs.get("rbac", False)

    if reqs.get("auth", {}).get("enabled", False):
        rbac_clause = (
            " Include RBAC: define at least admin, user, and viewer roles; "
            "enforce role checks with a decorator or dependency on protected endpoints."
            if rbac else ""
        )
        constraints.append(
            f"- Authentication: REQUIRED using {auth_type}. "
            f"Token expiry: {jwt_expiry} seconds. "
            f"Include auth middleware/decorators, token validation, and protect all endpoints.{rbac_clause}"
        )
    else:
        constraints.append("- Authentication: NOT required. No auth middleware needed.")

    # ── Logging ──────────────────────────────────────────────────────────────
    if reqs.get("structuredLogging", True):
        log_format = reqs.get("logFormat", "JSON")
        log_fields = reqs.get("logRequiredFields", ["requestId", "userId", "serviceName", "timestamp"])
        log_level = reqs.get("logLevel", "INFO")
        constraints.append(
            f"- Logging: Use {log_format} structured logging. Minimum level: {log_level}. "
            f"Every log entry MUST include these fields: {', '.join(log_fields)}. "
            "Configure the logger at startup so all output follows this format."
        )

    # ── Naming ───────────────────────────────────────────────────────────────
    naming = reqs.get("namingPattern", "{name}-service")
    constraints.append(f"- Service Naming: Apply pattern '{naming}' for the service name (replace {{name}} with the derived name).")

    # ── Observability (Legacy Metrics fallback) ──────────────────────────────
    if reqs.get("monitoring", True) and not obs_reqs:
        obs_tool = reqs.get("observabilityTool", "Prometheus")
        if obs_tool == "CloudWatch":
            constraints.append(
                "- Monitoring: Emit CloudWatch-style structured metric logs (EMF format). "
                "Track request count, latency (p50/p99), and error rate per endpoint."
            )
        else:
            constraints.append(
                "- Monitoring: Include Prometheus-compatible metrics via prometheus_client or equivalent. "
                "Expose a /metrics endpoint. Instrument request count (Counter), "
                "latency (Histogram), and error rate (Counter) per endpoint."
            )

    # ── Audit logging ─────────────────────────────────────────────────────────
    if reqs.get("auditLogging", False):
        constraints.append(
            "- Audit Logging: Log every API request and data mutation in a dedicated audit log. "
            "Each audit entry must include: caller identity (user/token), timestamp, HTTP method, "
            "path, request body (sanitised), status code, and response time. "
            "Use middleware so no endpoint can bypass audit logging."
        )

    # ── Docker ────────────────────────────────────────────────────────────────
    if reqs.get("dockerSupport", True):
        constraints.append(
            "- Docker: Generate a production-ready Dockerfile with multi-stage build "
            "(builder stage + minimal runtime stage). Include a docker-compose.yml for local development."
        )

    # ── Code Style ────────────────────────────────────────────────────
    code_naming = reqs.get("codeNaming", {})
    class_naming = code_naming.get("classes", "PascalCase")
    var_naming = code_naming.get("variables", "snake_case")
    constraints.append(
        f"- Code Style: Class names must use {class_naming}. "
        f"Variables and function names must use {var_naming}. "
        "Follow language idioms strictly — no mixed conventions."
    )

    forbidden_libs = reqs.get("forbiddenLibraries", [])
    allowed_libs = reqs.get("allowedLibraries", [])
    if forbidden_libs:
        constraints.append(
            f"- Forbidden Libraries: NEVER use these packages: {', '.join(forbidden_libs)}. "
            "Use alternatives from the standard library or approved packages."
        )
    if allowed_libs:
        constraints.append(
            f"- Approved Libraries: Only use packages from this allowlist (plus standard library): "
            f"{', '.join(allowed_libs)}. Do not introduce any other third-party dependencies."
        )

    # ── Artifact list ─────────────────────────────────────────────────────────
    artifact_descriptions = {
        "source": "Main application source code with all business logic",
        "api-skeleton": "API route definitions, request/response models, and endpoint handlers",
        "readme": "Comprehensive README.md with setup instructions, API documentation, and architecture overview",
        "dockerfile": "Production Dockerfile (multi-stage) and docker-compose.yml",
        "github-actions": "GitHub Actions CI/CD workflow (.github/workflows/ci.yml) with build, test, lint, and deploy stages",
        "k8s-manifests": "Kubernetes deployment.yaml and service.yaml with health checks, resource limits, and labels",
    }

    artifact_list = "\n".join(
        f"  - {a}: {artifact_descriptions.get(a, a)}"
        for a in artifacts
    )

    constraints_text = "\n".join(constraints)

    system_prompt = f"""You are a code generation engine for an Internal Developer Platform. Your job is to generate production-quality microservice code that strictly adheres to the following company engineering standards.

## Technology Stack & Constraints
{constraints_text}

## Artifacts to Generate
{artifact_list}

## Enterprise Dependency Requirements
You MUST include the following dependency block exactly as written in your requirements.txt / package.json / go.mod. Do not change versions or hallucinate competing telemetry libraries.

{golden_path['pinned_dependencies']}


    ## Output Format
    For each file you generate, use this exact format:

    ### FILE: <relative/path/to/file>
    Rules:

    Every file MUST start with the ### FILE: marker followed by the relative path.

    File content MUST be inside a fenced code block (triple backticks).

    Generate ONLY the requested artifacts — nothing extra.

    All code must be production-quality: proper error handling, type hints (if applicable), docstrings, and clean structure.

    Do NOT include placeholder comments like "TODO" or "implement here" — generate complete, working code.

    For the naming convention pattern, replace {{name}} with the service name derived from the user's request.

    Ensure all generated code is consistent — imports match actual file paths, config references are correct.

    IMPORTANT: Generate complete, working, production-ready code. Every file should be functional out of the box."""

    return system_prompt

def build_user_prompt(service_request: str, service_name: str) -> str:
    """Build the user prompt from the developer's service request."""
    return f"""Generate a complete microservice project for the following request:

    Service Request: {service_request}
    Service Name: {service_name}

    Generate all requested artifacts as complete, production-ready files. The service should implement reasonable business logic based on the request description — include appropriate data models, API endpoints, error handling, and configuration.

    Remember to follow ALL company engineering standards specified in the system prompt."""