import pytest
from backend.generation_orchestrator.guardrails import Guardrails, TokenBudgetExceededException

def test_secret_redaction():
    raw_prompt = "Here is my key: AKIAIOSFODNN7EXAMPLE and token: ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    sanitized = Guardrails.redact_secrets(raw_prompt)
    assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized
    assert "[REDACTED_AWS_KEY]" in sanitized
    assert "[REDACTED_GITHUB_TOKEN]" in sanitized

def test_xml_boundary_isolation():
    raw_prompt = "Build a payment service"
    isolated = Guardrails.sanitize_and_isolate(raw_prompt)
    assert "<developer_request_context>" in isolated
    assert "</developer_request_context>" in isolated
    assert "Build a payment service" in isolated

def test_token_budget_exceeded():
    huge_prompt = "a" * (Guardrails.MAX_TOKEN_BUDGET * 4 + 100)
    with pytest.raises(TokenBudgetExceededException):
        Guardrails.check_token_budget(huge_prompt)