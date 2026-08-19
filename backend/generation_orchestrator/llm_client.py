import os
import json
import time
import urllib.request
import boto3
try:
    from finops import FinOps
except ModuleNotFoundError:
    from backend.generation_orchestrator.finops import FinOps

class LLMClient:
    def __init__(self):
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.enable_bedrock = os.environ.get("ENABLE_BEDROCK_FALLBACK", "false").lower() == "true"
        self.bedrock_model = os.environ.get("BEDROCK_FALLBACK_MODEL", "meta.llama3-70b-instruct-v1:0")

    def _call_groq(self, system_prompt: str, user_prompt: str) -> dict:
        """Calls Groq API with an 8-second timeout per attempt."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            
        content = res_data["choices"][0]["message"]["content"]
        raw_usage = res_data.get("usage", {})
        
        return {
            "content": content,
            "provider": "groq",
            "model_id": "llama-3.3-70b-versatile",
            "usage": FinOps.normalize_usage(raw_usage, "groq")
        }

    def _call_bedrock(self, system_prompt: str, user_prompt: str) -> dict:
        """Fallback call to AWS Bedrock."""
        bedrock = boto3.client(service_name='bedrock-runtime')
        
        
        formatted_prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n{user_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
        
        body = json.dumps({
            "prompt": formatted_prompt,
            "max_gen_len": 4096,
            "temperature": 0.2
        })
        
        response = bedrock.invoke_model(
            modelId=self.bedrock_model,
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        
        res_body = json.loads(response['body'].read().decode('utf-8'))
        content = res_body.get("generation", "")
        
        raw_usage = {
            "input_tokens": res_body.get("prompt_token_count", len(formatted_prompt) // 4),
            "output_tokens": res_body.get("generation_token_count", len(content) // 4)
        }
        
        return {
            "content": content,
            "provider": "bedrock",
            "model_id": self.bedrock_model,
            "usage": FinOps.normalize_usage(raw_usage, "bedrock")
        }

    def generate_code(self, system_prompt: str, user_prompt: str) -> dict:
        """Attempts generation with Groq, falling back to Bedrock on error."""
        start_time = time.time()
        
        try:
            result = self._call_groq(system_prompt, user_prompt)
        except Exception as groq_err:
            print(f"[WARN] Groq generation failed: {str(groq_err)}. Checking fallback...")
            if self.enable_bedrock:
                try:
                    result = self._call_bedrock(system_prompt, user_prompt)
                except Exception as bedrock_err:
                    raise RuntimeError(f"All LLM providers failed. Bedrock error: {str(bedrock_err)}")
            else:
                raise RuntimeError(f"Groq API call failed and fallback is disabled: {str(groq_err)}")

        # Compute telemetry
        result["latency_ms"] = round((time.time() - start_time) * 1000, 2)
        result["cost_usd"] = FinOps.calculate_cost(
            result["model_id"],
            result["usage"]["prompt_tokens"],
            result["usage"]["completion_tokens"]
        )
        
        return result