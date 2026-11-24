import os
import json
import re
import time
import urllib.request
import urllib.error

import boto3
from finops import FinOps

try:
    from shared.secrets import get_secret
except ImportError:  # pragma: no cover
    def get_secret(name: str) -> str:
        return os.environ.get(name, "")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Non-reasoning model by default: reasoning models (qwen3, deepseek-r1, gpt-oss)
# spend the output budget on <think> text and can be cut off before any file
# is written, which is what produced "requirements.txt only" ZIPs.
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMTruncatedError(RuntimeError):
    """The model stopped because it hit max_tokens before finishing."""


def _strip_planning_prose(content: str) -> str:
    """Remove reasoning blocks and planning prose from LLM output.

    Handles:
    - closed <think>...</think> blocks
    - an UNCLOSED <think> block (model was cut off while reasoning): everything
      from <think> onward is reasoning, never code, so it is dropped entirely
    - prose dumped before the first ### FILE: marker
    """
    content = content or ""
    content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
    open_think = content.find("<think>")
    if open_think != -1:
        content = content[:open_think]

    first_marker = content.find("### FILE:")
    if first_marker != -1:
        content = content[first_marker:]

    return content.strip()


def _is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return any(k in m for k in ("qwen3", "qwq", "deepseek-r1", "r1-distill"))


class LLMClient:
    def __init__(self):
        self._groq_api_key = None
        self.groq_model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self.max_tokens = int(os.environ.get("GROQ_MAX_TOKENS", "8000"))
        self.max_retries = int(os.environ.get("GROQ_MAX_RETRIES", "3"))
        self.enable_bedrock = os.environ.get("ENABLE_BEDROCK_FALLBACK", "false").lower() == "true"
        self.bedrock_model = os.environ.get("BEDROCK_FALLBACK_MODEL", "meta.llama3-70b-instruct-v1:0")

    @property
    def groq_api_key(self) -> str:
        if self._groq_api_key is None:
            self._groq_api_key = get_secret("GROQ_API_KEY")
        return self._groq_api_key

    def _groq_payload(self, system_prompt: str, user_prompt: str) -> dict:
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.15,
            "max_tokens": self.max_tokens,
        }
        if _is_reasoning_model(self.groq_model):
            # Keep reasoning out of `content` so it can never be parsed as files.
            payload["reasoning_format"] = "hidden"
        return payload

    def _call_groq(self, system_prompt: str, user_prompt: str) -> dict:
        """Calls Groq with retry/backoff on rate limits and 5xx errors."""
        if not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PolicyCraft/1.0",
        }
        data = json.dumps(self._groq_payload(system_prompt, user_prompt)).encode("utf-8")

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(GROQ_API_URL, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:500]
                last_err = RuntimeError(f"Groq HTTP {e.code}: {body}")
                if e.code in _RETRYABLE_STATUS and attempt < self.max_retries - 1:
                    retry_after = e.headers.get("retry-after") if e.headers else None
                    delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 2 ** (attempt + 1)
                    print(f"[WARN] Groq HTTP {e.code}, retrying in {delay}s")
                    time.sleep(min(delay, 30))
                    continue
                raise last_err from e
            except urllib.error.URLError as e:
                last_err = RuntimeError(f"Groq connection error: {e.reason}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise last_err from e
        else:  # pragma: no cover - loop always breaks or raises
            raise last_err or RuntimeError("Groq call failed")

        choice = res_data["choices"][0]
        content = _strip_planning_prose(choice["message"].get("content") or "")
        finish_reason = choice.get("finish_reason")

        if not content:
            raise LLMTruncatedError(
                f"Groq model '{self.groq_model}' returned no file content "
                f"(finish_reason={finish_reason}). Raise GROQ_MAX_TOKENS or use a non-reasoning model."
            )

        return {
            "content": content,
            "provider": "groq",
            "model_id": self.groq_model,
            "finish_reason": finish_reason,
            "usage": FinOps.normalize_usage(res_data.get("usage", {}), "groq"),
        }

    def _call_bedrock(self, system_prompt: str, user_prompt: str) -> dict:
        """Fallback call to AWS Bedrock (NOT free tier - disabled by default)."""
        bedrock = boto3.client(service_name="bedrock-runtime")

        formatted_prompt = (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            f"{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n"
            f"{user_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
        )

        body = json.dumps({"prompt": formatted_prompt, "max_gen_len": 4096, "temperature": 0.2})

        response = bedrock.invoke_model(
            modelId=self.bedrock_model,
            body=body,
            contentType="application/json",
            accept="application/json",
        )

        res_body = json.loads(response["body"].read().decode("utf-8"))
        content = _strip_planning_prose(res_body.get("generation", ""))

        raw_usage = {
            "input_tokens": res_body.get("prompt_token_count", len(formatted_prompt) // 4),
            "output_tokens": res_body.get("generation_token_count", len(content) // 4),
        }

        return {
            "content": content,
            "provider": "bedrock",
            "model_id": self.bedrock_model,
            "finish_reason": res_body.get("stop_reason"),
            "usage": FinOps.normalize_usage(raw_usage, "bedrock"),
        }

    def generate_code(self, system_prompt: str, user_prompt: str) -> dict:
        """Attempts generation with Groq, falling back to Bedrock on error."""
        start_time = time.time()

        try:
            result = self._call_groq(system_prompt, user_prompt)
        except Exception as groq_err:
            print(f"[WARN] Groq generation failed: {groq_err}. Checking fallback...")
            if self.enable_bedrock:
                try:
                    result = self._call_bedrock(system_prompt, user_prompt)
                except Exception as bedrock_err:
                    raise RuntimeError(f"All LLM providers failed. Bedrock error: {bedrock_err}")
            else:
                raise RuntimeError(f"Groq API call failed and fallback is disabled: {groq_err}")

        result["latency_ms"] = round((time.time() - start_time) * 1000, 2)
        result["cost_usd"] = FinOps.calculate_cost(
            result["model_id"],
            result["usage"]["prompt_tokens"],
            result["usage"]["completion_tokens"],
        )
        return result
