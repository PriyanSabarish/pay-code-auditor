"""Tests for the Gemini provider path in llm.py: message/tool translation and rate-limit
retry. The underlying genai client is monkeypatched — these check our translation logic,
not Gemini's actual behaviour.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from auditor import llm


@pytest.fixture(autouse=True)
def _use_gemini_provider(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "gemini")


def _fake_response(text: str = "", function_calls: list[tuple[str, dict]] | None = None):
    parts = []
    if text:
        parts.append(SimpleNamespace(text=text, function_call=None))
    for name, args in function_calls or []:
        parts.append(SimpleNamespace(text=None, function_call=SimpleNamespace(id=None, name=name, args=args)))
    candidate = SimpleNamespace(content=SimpleNamespace(parts=parts))
    usage = SimpleNamespace(prompt_token_count=12, candidates_token_count=6, total_token_count=18)
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


class _FakeModels:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _install_fake_client(monkeypatch, side_effects):
    fake_models = _FakeModels(side_effects)
    fake_client = SimpleNamespace(models=fake_models)
    monkeypatch.setattr(llm, "get_gemini_client", lambda: fake_client)
    return fake_models


def test_returns_plain_text(monkeypatch):
    fake = _install_fake_client(monkeypatch, [_fake_response(text="hello")])
    result = llm.complete([{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}], tier="fast")
    assert result.text == "hello"
    assert result.total_tokens == 18
    assert fake.calls[0]["config"].system_instruction == "be terse"


def test_translates_function_call_into_tool_call(monkeypatch):
    _install_fake_client(monkeypatch, [_fake_response(function_calls=[("search_ato_guidance", {"query": "PILN"})])])
    tools = [{"type": "function", "function": {"name": "search_ato_guidance", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
    result = llm.complete([{"role": "user", "content": "hi"}], tier="strong", tools=tools, tool_choice="auto")
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search_ato_guidance"
    assert result.tool_calls[0].arguments == {"query": "PILN"}


def test_resumed_tool_conversation_translates_all_roles(monkeypatch):
    """A full assistant tool_call + tool result round trip, as investigator.py builds it,
    must translate without raising — this is the shape _rebuild_messages actually sends."""
    fake = _install_fake_client(monkeypatch, [_fake_response(text="done")])
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "investigate PILN"},
        {"role": "assistant", "tool_calls": [{"id": "step-1", "type": "function", "function": {"name": "get_payment_history", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "step-1", "content": "paid fortnightly"},
    ]
    result = llm.complete(messages, tier="strong")
    assert result.text == "done"
    contents = fake.calls[0]["contents"]
    assert contents[-1].parts[0].function_response.name == "get_payment_history"


def test_retries_after_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    fake = _install_fake_client(monkeypatch, [
        genai_errors.ClientError(429, {"error": {"message": "rate limited"}}),
        _fake_response(text="hello"),
    ])
    result = llm.complete([{"role": "user", "content": "hi"}], tier="fast")
    assert result.text == "hello"
    assert len(fake.calls) == 2


def test_gives_up_after_max_rate_limit_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    effects = [genai_errors.ClientError(429, {"error": {"message": "rate limited"}}) for _ in range(llm.MAX_RATE_LIMIT_RETRIES + 1)]
    _install_fake_client(monkeypatch, effects)
    with pytest.raises(genai_errors.ClientError):
        llm.complete([{"role": "user", "content": "hi"}], tier="fast")


def test_reraises_non_rate_limit_client_errors(monkeypatch):
    _install_fake_client(monkeypatch, [genai_errors.ClientError(400, {"error": {"message": "bad request"}})])
    with pytest.raises(genai_errors.ClientError):
        llm.complete([{"role": "user", "content": "hi"}], tier="fast")


def test_retries_after_transient_server_error(monkeypatch):
    """A live run hit a real 503 'model experiencing high demand' — a 5xx ServerError is
    a distinct exception class from the 429 ClientError and must be retried too."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    fake = _install_fake_client(monkeypatch, [
        genai_errors.ServerError(503, {"error": {"message": "high demand"}}),
        _fake_response(text="hello"),
    ])
    result = llm.complete([{"role": "user", "content": "hi"}], tier="fast")
    assert result.text == "hello"
    assert len(fake.calls) == 2
