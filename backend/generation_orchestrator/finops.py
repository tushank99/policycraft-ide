from decimal import Decimal

class FinOps:
    # Pricing per 1M tokens in USD(It is standard because all major LLM and cloud providers publish and bill their base API rates in USD.)
    PRICING = {
        "llama-3.3-70b-versatile": {"prompt": 0.59, "completion": 0.79},
        "meta.llama3-70b-instruct-v1:0": {"prompt": 2.65, "completion": 3.50}, # Bedrock Llama 3
        "anthropic.claude-3-haiku": {"prompt": 0.25, "completion": 1.25}       # Bedrock Haiku
    }

    @staticmethod
    def normalize_usage(raw_usage: dict, provider: str) -> dict:
        """Standardizes token payload differences between Groq and Bedrock."""
        if provider == "groq":
            prompt = raw_usage.get("prompt_tokens", 0)
            completion = raw_usage.get("completion_tokens", 0)
        elif provider == "bedrock":
            prompt = raw_usage.get("input_tokens", 0)
            completion = raw_usage.get("output_tokens", 0)
        else:
            prompt, completion = 0, 0
            
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion
        }

    @staticmethod
    def calculate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """Calculates exact USD cost based on token usage and model ID."""
        rates = FinOps.PRICING.get(model_id, {"prompt": 0.0, "completion": 0.0})
        
        prompt_cost = (prompt_tokens / 1_000_000) * rates["prompt"]
        completion_cost = (completion_tokens / 1_000_000) * rates["completion"]
        
        # Cast to Decimal for safe DynamoDB serialization and cap at 6 decimal places
        total_cost = Decimal(str(prompt_cost + completion_cost)).quantize(Decimal('0.000000'))
        return total_cost