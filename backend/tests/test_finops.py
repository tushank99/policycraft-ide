from decimal import Decimal
from backend.generation_orchestrator.finops import FinOps

def test_normalize_usage_groq():
    groq_raw = {"prompt_tokens": 100, "completion_tokens": 50}
    normalized = FinOps.normalize_usage(groq_raw, "groq")
    assert normalized == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

def test_normalize_usage_bedrock():
    bedrock_raw = {"input_tokens": 200, "output_tokens": 75}
    normalized = FinOps.normalize_usage(bedrock_raw, "bedrock")
    assert normalized == {"prompt_tokens": 200, "completion_tokens": 75, "total_tokens": 275}

def test_calculate_cost_precision():
    # 1000 prompt tokens @ $0.59/1M = $0.00059
    # 1000 completion tokens @ $0.79/1M = $0.00079
    # Total = $0.001380
    cost = FinOps.calculate_cost("llama-3.3-70b-versatile", 1000, 1000)
    assert cost == Decimal("0.001380")