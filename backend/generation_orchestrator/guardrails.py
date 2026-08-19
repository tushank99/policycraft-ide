import re

class TokenBudgetExceededException(Exception):
    """Raised when the estimated prompt tokens exceed the configured limit."""
    pass

class Guardrails:
    MAX_TOKEN_BUDGET = 6000 
    
    @staticmethod
    def redact_secrets(text: str) -> str:
        """Masks common secrets like AWS Keys and GitHub tokens."""
        if not text:
            return ""
            
        
        aws_pattern = r"(AKIA[0-9A-Z]{16})"
        github_pattern = r"(ghp_[a-zA-Z0-9]{36})"
        
        text = re.sub(aws_pattern, "[REDACTED_AWS_KEY]", text)
        text = re.sub(github_pattern, "[REDACTED_GITHUB_TOKEN]", text)
        return text
        
    @staticmethod
    def sanitize_and_isolate(user_prompt: str) -> str:
        """Redacts secrets and wraps the prompt in XML boundaries."""
        clean_prompt = Guardrails.redact_secrets(user_prompt)
        # XML tags help the LLM separate instructions from user input
        return f"<developer_request_context>\n{clean_prompt}\n</developer_request_context>"
        
    @staticmethod
    def check_token_budget(prompt: str) -> None:
        """Estimates token count and throws an error if it exceeds the limit."""
        
        estimated_tokens = len(prompt) // 4
        if estimated_tokens > Guardrails.MAX_TOKEN_BUDGET:
            raise TokenBudgetExceededException(
                f"Request exceeds token budget. Estimated: {estimated_tokens}, Max: {Guardrails.MAX_TOKEN_BUDGET}"
            )