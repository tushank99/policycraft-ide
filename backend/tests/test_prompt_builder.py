from backend.generation_orchestrator.prompt_builder import build_system_prompt

def test_prompt_includes_typescript_golden_path():
    
    spec = {
        "stack": {"language": "typescript", "framework": "express"},
        "requirements": {
            "openTelemetryEnabled": True,
            "correlationHeader": "X-Company-Trace-ID",
            "healthEndpoint": {
                "enabled": True,
                "livenessPath": "/ping",
                "readinessPath": "/ready"
            }
        },
        "artifacts": ["source", "dockerfile"]
    }
    
    prompt = build_system_prompt(spec)
    
    # 1. Verify Target Runtime
    assert "Node.js 20 + TypeScript + Express" in prompt
    
    # 2. Verify Pinned Dependencies
    assert "@opentelemetry/sdk-node" in prompt
    
    # 3. Verify Custom Correlation Header
    assert "X-Company-Trace-ID" in prompt
    
    # 4. Verify Custom Health Probes
    assert "Map Liveness to '/ping' and Readiness to '/ready'" in prompt

def test_prompt_disables_otel_when_configured():
    spec = {
        "stack": {"language": "python", "framework": "fastapi"},
        "requirements": {
            "openTelemetryEnabled": False,  
            "monitoring": True,
            "observabilityTool": "CloudWatch",
            "healthEndpoint": {"enabled": False}
        },
        "artifacts": ["source"]
    }
    
    prompt = build_system_prompt(spec)
    
    
    assert "Observability (OpenTelemetry)" not in prompt
    assert "CloudWatch-style structured metric logs" in prompt