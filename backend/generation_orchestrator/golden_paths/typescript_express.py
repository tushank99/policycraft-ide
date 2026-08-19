def get_typescript_express_spec() -> dict:
    return {
        "runtime": "Node.js 20 + TypeScript + Express",
        "pinned_dependencies": """
  // -- ENTERPRISE REQUIRED DEPENDENCIES (DO NOT MODIFY) --
  "express": "^4.19.2",
  "pino": "^9.0.0",
  "pino-http": "^10.0.0",
  "uuid": "^9.0.1",
  "@opentelemetry/sdk-node": "^0.51.1",
  "@opentelemetry/auto-instrumentations-node": "^0.46.0",
  "@opentelemetry/exporter-trace-otlp-http": "^0.51.1"
  // ----------------------------------------------------
""",
        "telemetry_rules": (
            "Create a 'telemetry.ts' file using @opentelemetry/sdk-node. Initialize the tracer before importing Express. "
            "Ensure the OTLP trace exporter is configured but does not crash the Node process if the collector is unreachable."
        ),
        "correlation_id_rules": (
            "Implement an Express middleware using 'AsyncLocalStorage' (from async_hooks). "
            "Extract 'x-correlation-id' from headers or generate a UUID4. Ensure the Pino logger automatically binds this 'correlationId' to all log entries."
        ),
        "health_probes": (
            "Implement two strict endpoints: "
            "1. GET /healthz (Liveness) -> res.status(200).json({ status: 'up' }). "
            "2. GET /readyz (Readiness) -> Check simulated DB state, res.status(200) if ready, 503 if not."
        )
    }