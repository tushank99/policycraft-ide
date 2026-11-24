"""Regression tests for the 'ZIP only contains requirements.txt' bug.

Root cause: a reasoning model (qwen3 on Groq) hit max_tokens while still inside
an unclosed <think> block. The old stripper only removed *closed* think blocks,
so code fences inside the reasoning were parsed as the project.
"""
import io
import json
from unittest.mock import patch

import pytest

from llm_client import LLMClient, LLMTruncatedError, _strip_planning_prose
from handler import _check_completeness


TRUNCATED_THINK = (
    "<think>\nOkay, payment service. First requirements:\n```\n"
    "fastapi==0.111.0\nuvicorn==0.30.0\n```\nThen main.py should..."
)


def test_unclosed_think_is_dropped_entirely():
    assert _strip_planning_prose(TRUNCATED_THINK) == ""


def test_closed_think_is_removed_but_files_kept():
    out = "<think>plan</think>\n### FILE: main.py\n```python\nprint(1)\n```"
    assert _strip_planning_prose(out).startswith("### FILE: main.py")


def _fake_response(content, finish_reason="stop"):
    body = json.dumps({
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }).encode()

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(body)


def test_groq_truncated_reasoning_raises(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    client = LLMClient()
    with patch("urllib.request.urlopen", return_value=_fake_response(TRUNCATED_THINK, "length")):
        with pytest.raises(LLMTruncatedError):
            client._call_groq("sys", "user")


def test_reasoning_model_requests_hidden_reasoning(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3-32b")
    payload = LLMClient()._groq_payload("s", "u")
    assert payload["reasoning_format"] == "hidden"


def test_default_model_is_non_reasoning(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    payload = LLMClient()._groq_payload("s", "u")
    assert "reasoning_format" not in payload


def test_requirements_only_project_is_incomplete():
    spec = {"stack": {"language": "Python"}, "selectedArtifacts": ["source", "readme"]}
    problems = _check_completeness({"requirements.txt": "fastapi==0.111.0\n"}, spec)
    assert problems


def test_full_project_is_complete():
    spec = {"stack": {"language": "Python"}, "selectedArtifacts": ["source", "readme"]}
    files = {
        "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        "requirements.txt": "fastapi==0.111.0\n",
        "README.md": "# svc\n",
    }
    assert _check_completeness(files, spec) == []
