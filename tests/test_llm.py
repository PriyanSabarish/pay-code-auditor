"""Tests for the Groq wrapper's resilience: rate-limit retry with backoff, and recovery
from the "json" tool-call quirk. The underlying Groq client is monkeypatched directly —
these are about our error-handling, not about Groq's actual behaviour.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError, RateLimitError

from auditor import llm


def _rate_limit_error(retry_after_ms: str | None = "50") -> RateLimitError:
    headers = {"retry-after-ms": retry_after_ms} if retry_after_ms else {}
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request, headers=headers, json={"error": {"message": "rate limited"}})
    return RateLimitError(message="rate limited", response=response, body={"error": {"message": "rate limited"}})


def _bad_request_json_tool_error(payload: dict) -> BadRequestError:
    import json as _json

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {
        "error": {
            "message": "Tool call validation failed",
            "code": "tool_use_failed",
            "failed_generation": _json.dumps({"name": "json", "arguments": payload}),
        }
    }
    response = httpx.Response(400, request=request, json=body)
    return BadRequestError(message="Tool call validation failed", response=response, body=body)


def _fake_response(text: str = "ok"):
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeChatCompletions:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _install_fake_client(monkeypatch, side_effects):
    fake_completions = _FakeChatCompletions(side_effects)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
    monkeypatch.setattr(llm, "get_client", lambda: fake_client)
    return fake_completions


def test_retries_after_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)  # don't actually wait in tests
    fake = _install_fake_client(monkeypatch, [_rate_limit_error(), _fake_response("hello")])
    result = llm.complete([{"role": "user", "content": "hi"}], tier="fast")
    assert result.text == "hello"
    assert fake.call_count == 2


def test_gives_up_after_max_rate_limit_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    effects = [_rate_limit_error() for _ in range(llm.MAX_RATE_LIMIT_RETRIES + 1)]
    _install_fake_client(monkeypatch, effects)
    with pytest.raises(RateLimitError):
        llm.complete([{"role": "user", "content": "hi"}], tier="fast")


def test_uses_retry_after_ms_header_for_wait_time(monkeypatch):
    waits = []
    monkeypatch.setattr(time, "sleep", lambda seconds: waits.append(seconds))
    _install_fake_client(monkeypatch, [_rate_limit_error(retry_after_ms="337"), _fake_response()])
    llm.complete([{"role": "user", "content": "hi"}], tier="fast")
    assert waits == [pytest.approx(0.337 + 0.25, abs=0.01)]


def test_falls_back_to_exponential_wait_when_no_header(monkeypatch):
    waits = []
    monkeypatch.setattr(time, "sleep", lambda seconds: waits.append(seconds))
    _install_fake_client(monkeypatch, [_rate_limit_error(retry_after_ms=None), _fake_response()])
    llm.complete([{"role": "user", "content": "hi"}], tier="fast")
    assert waits == [pytest.approx(2.0 + 0.25, abs=0.01)]


def test_recovers_text_from_json_tool_quirk(monkeypatch):
    payload = {"counts_towards_super": "yes", "confidence": "high"}
    _install_fake_client(monkeypatch, [_bad_request_json_tool_error(payload)])
    result = llm.complete([{"role": "user", "content": "hi"}], tier="strong")
    assert result.tool_calls == []
    assert '"counts_towards_super": "yes"' in result.text or "counts_towards_super" in result.text


def test_reraises_unrelated_bad_request_errors(monkeypatch):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {"error": {"message": "invalid request", "code": "invalid_request_error"}}
    response = httpx.Response(400, request=request, json=body)
    exc = BadRequestError(message="invalid request", response=response, body=body)
    _install_fake_client(monkeypatch, [exc])
    with pytest.raises(BadRequestError):
        llm.complete([{"role": "user", "content": "hi"}], tier="fast")
