from unittest.mock import patch
from backend.generation_orchestrator.llm_client import LLMClient

@patch.object(LLMClient, '_call_groq')
def test_groq_primary_success(mock_groq):
    mock_groq.return_value = {
        "content": "### FILE: main.py\nprint('hello')",
        "provider": "groq",
        "model_id": "llama-3.3-70b-versatile",
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
    }
    
    client = LLMClient()
    res = client.generate_code("system prompt", "user prompt")
    
    assert res["provider"] == "groq"
    assert "main.py" in res["content"]
    assert "cost_usd" in res
    assert "latency_ms" in res

@patch.object(LLMClient, '_call_groq', side_effect=Exception("Groq HTTP 429 Rate Limit"))
@patch.object(LLMClient, '_call_bedrock')
def test_bedrock_failover_on_groq_error(mock_bedrock, mock_groq):
    mock_bedrock.return_value = {
        "content": "### FILE: app.py\nprint('bedrock fallback')",
        "provider": "bedrock",
        "model_id": "meta.llama3-70b-instruct-v1:0",
        "usage": {"prompt_tokens": 60, "completion_tokens": 30, "total_tokens": 90}
    }
    
    client = LLMClient()
    client.enable_bedrock = True
    res = client.generate_code("system prompt", "user prompt")
    
    assert res["provider"] == "bedrock"
    assert "bedrock fallback" in res["content"]