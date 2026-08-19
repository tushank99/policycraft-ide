from .python_fastapi import get_python_fastapi_spec
from .typescript_express import get_typescript_express_spec
from .go_gin import get_go_gin_spec

def get_golden_path_spec(language: str, framework: str) -> dict:
    """
    Returns the deterministic enterprise boilerplate constraints for the requested stack.
    Defaults to Python/FastAPI if the stack is unknown.
    """
    lang = language.lower()
    fw = framework.lower() if framework else ""

    if lang in ["typescript", "javascript", "node", "nodejs"] and "express" in fw:
        return get_typescript_express_spec()
    elif lang == "go" and "gin" in fw:
        return get_go_gin_spec()
    else:
        # Default fallback is Python FastAPI
        return get_python_fastapi_spec()