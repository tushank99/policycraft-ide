def get_python_fastapi_spec() -> dict:
    return {
        "runtime": "Python 3.12 + FastAPI",
        "pinned_dependencies": """
# -- ENTERPRISE REQUIRED DEPENDENCIES (DO NOT MODIFY) --
fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic==2.7.1
pydantic-settings==2.2.1
opentelemetry-api==1.24.0
opentelemetry-sdk==1.24.0
opentelemetry-instrumentation-fastapi==0.45b0
opentelemetry-exporter-otlp==1.24.0
python-json-logger==2.0.7
python-jose[cryptography]==3.3.0
# ----------------------------------------------------
""",
        "telemetry_rules": (
            "Create a 'telemetry.py' file that configures OpenTelemetry with a non-blocking OTLP exporter. "
            "If the OTEL_EXPORTER_OTLP_ENDPOINT env var is missing, it should gracefully fall back to ConsoleSpanExporter without crashing."
        ),
        "correlation_id_rules": (
            "Implement a FastAPI middleware that checks for 'X-Correlation-ID' in the request headers. "
            "If missing, generate a new UUID4. Store this ID using 'contextvars' and ensure all structlog/json logs automatically include 'correlation_id'."
        ),
        "health_probes": (
            "Implement two strict health endpoints: "
            "1. GET /healthz (Liveness) -> Returns 200 OK immediately. "
            "2. GET /readyz (Readiness) -> Ping the database/cache (mocked if none) and return 200 if healthy, 503 if unavailable."
        )
    }