def get_go_gin_spec() -> dict:
    return {
        "runtime": "Go 1.22 + Gin",
        "pinned_dependencies": """
// -- ENTERPRISE REQUIRED DEPENDENCIES (DO NOT MODIFY) --
require (
\tgithub.com/gin-gonic/gin v1.10.0
\tgithub.com/google/uuid v1.6.0
\tgo.opentelemetry.io/otel v1.27.0
\tgo.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp v1.27.0
\tgo.opentelemetry.io/otel/sdk v1.27.0
\tgo.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin v0.52.0
)
// ----------------------------------------------------
""",
        "telemetry_rules": (
            "Create a 'telemetry.go' package that configures OpenTelemetry. Use otlptracehttp for the exporter. "
            "Wrap the Gin router setup with the 'otelgin' middleware for automatic route tracing."
        ),
        "correlation_id_rules": (
            "Implement a Gin middleware that extracts 'X-Correlation-ID'. If empty, generate a new google/uuid. "
            "Set it in the Gin context (c.Set) and add it to the response headers. Ensure the standard 'log/slog' JSON logger extracts this from context."
        ),
        "health_probes": (
            "Implement two distinct routes: "
            "1. GET /healthz (Liveness) -> c.JSON(200, gin.H{\"status\": \"ok\"}). "
            "2. GET /readyz (Readiness) -> Verify database connection, return 200 or 503."
        )
    }