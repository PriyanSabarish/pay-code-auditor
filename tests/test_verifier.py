"""Unit tests for the verifier. The LLM is stubbed (same approach as test_classify.py) —
these check the validation/retry contract, not model judgement quality.
"""

from __future__ import annotations

import json

import pytest

from auditor import verifier
from auditor.llm import CompletionResult
from auditor.schemas import Citation, Classification


def _result(text: str, tokens: int = 40) -> CompletionResult:
    return CompletionResult(
        text=text, tier="strong", model="stub-strong", latency_seconds=0.01,
        prompt_tokens=tokens, completion_tokens=10, total_tokens=tokens + 10,
    )


def _verifier_json(agrees: bool, note: str = "Matches the cited rule.") -> str:
    return json.dumps({"agrees": agrees, "note": note})


def _stub(monkeypatch, responses: list[CompletionResult]):
    queue = list(responses)

    def fake_complete(messages, *, tier="strong", temperature=0.0, **kwargs):
        assert temperature == 0.0
        if not queue:
            raise AssertionError("LLM called more times than the test expected")
        return queue.pop(0)

    monkeypatch.setattr(verifier.llm, "complete", fake_complete)
    return queue


def make_classification(counts="yes", citations=None) -> Classification:
    if citations is None:
        citations = [Citation(source="ATO qualifying earnings page", reference="Table 8, row 2")]
    return Classification(
        code="SITE ALLOW", normalised_name="Site Allowance", ato_category="allowance",
        counts_towards_super=counts, confidence="high",
        citations=citations,
        reasoning="Compensates for adverse conditions.",
    )


def test_verifier_agrees_on_valid_response(monkeypatch):
    _stub(monkeypatch, [_result(_verifier_json(True, "The cited row supports this."))])
    outcome = verifier.verify(make_classification())
    assert outcome.agrees is True
    assert "supports" in outcome.note
    assert len(outcome.calls) == 1


def test_verifier_disagrees_on_valid_response(monkeypatch):
    _stub(monkeypatch, [_result(_verifier_json(False, "The cited row actually says the opposite."))])
    outcome = verifier.verify(make_classification())
    assert outcome.agrees is False
    assert "opposite" in outcome.note


def test_verifier_retries_once_on_invalid_json_then_succeeds(monkeypatch):
    queue = _stub(monkeypatch, [_result("not json"), _result(_verifier_json(True))])
    outcome = verifier.verify(make_classification())
    assert outcome.agrees is True
    assert len(outcome.calls) == 2
    assert queue == []


def test_verifier_gives_up_as_none_after_two_bad_attempts(monkeypatch):
    _stub(monkeypatch, [_result("garbage"), _result("still garbage")])
    outcome = verifier.verify(make_classification())
    assert outcome.agrees is None  # a shrug, not a disagreement
    assert len(outcome.calls) == 2
    assert "unverified" in outcome.note


def test_no_citations_formats_as_explicit_placeholder(monkeypatch):
    captured = {}

    def fake_complete(messages, *, tier="strong", temperature=0.0, **kwargs):
        captured["user_message"] = messages[-1]["content"]
        return _result(_verifier_json(True))

    monkeypatch.setattr(verifier.llm, "complete", fake_complete)
    verifier.verify(make_classification(citations=[]))
    assert "(no citations given)" in captured["user_message"]
