"""LLM providers for the remediation agent.

REMEDIATION_LLM=groq     (default when GROQ_API_KEY is set; free tier)
REMEDIATION_LLM=bedrock  (AWS Bedrock Converse API; NOT free tier, billed per token)
REMEDIATION_LLM=offline  (deterministic templates; default when no key is set)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def provider_name() -> str:
    explicit = os.environ.get("REMEDIATION_LLM")
    if explicit:
        return explicit.lower()
    return "groq" if os.environ.get("GROQ_API_KEY") else "offline"


def complete(system: str, user: str, max_tokens: int = 1800) -> str:
    provider = provider_name()
    if provider == "groq":
        return _groq(system, user, max_tokens)
    if provider == "bedrock":
        return _bedrock(system, user, max_tokens)
    raise RuntimeError("offline provider has no LLM")


def _groq(system: str, user: str, max_tokens: int) -> str:
    payload = json.dumps({
        "model": os.environ.get("REMEDIATION_GROQ_MODEL", "llama-3.1-8b-instant"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode()
    headers = {
        "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
        "Content-Type": "application/json",
        "User-Agent": "policycraft-triage/1.0",
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=payload,
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def _bedrock(system: str, user: str, max_tokens: int) -> str:
    import boto3

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    resp = client.converse(
        modelId=os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0"),
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1},
    )
    return resp["output"]["message"]["content"][0]["text"]
