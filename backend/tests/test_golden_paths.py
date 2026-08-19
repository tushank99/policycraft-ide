from backend.generation_orchestrator.golden_paths import get_golden_path_spec

def test_python_fastapi_golden_path():
    spec = get_golden_path_spec("python", "fastapi")
    assert "Python 3.12" in spec["runtime"]
    assert "opentelemetry-instrumentation-fastapi" in spec["pinned_dependencies"]
    assert "/healthz" in spec["health_probes"]

def test_typescript_express_golden_path():
    spec = get_golden_path_spec("typescript", "express")
    assert "Node.js 20" in spec["runtime"]
    assert "@opentelemetry/sdk-node" in spec["pinned_dependencies"]
    assert "AsyncLocalStorage" in spec["correlation_id_rules"]

def test_go_gin_golden_path():
    spec = get_golden_path_spec("go", "gin")
    assert "Go 1.22" in spec["runtime"]
    assert "github.com/gin-gonic/gin/otelgin" in spec["pinned_dependencies"]
    assert "c.Set" in spec["correlation_id_rules"]

def test_golden_path_fallback():
    # Unknown combinations should safely default to Python FastAPI
    spec = get_golden_path_spec("rust", "rocket")
    assert "Python 3.12" in spec["runtime"]