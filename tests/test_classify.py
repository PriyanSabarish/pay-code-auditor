"""Unit tests for the cascade classifier. The LLM is stubbed throughout — these tests
check the cascade/retry/escalation logic, not model quality, and need no API key."""

from __future__ import annotations

import json

import pytest

from auditor import classify
from auditor.llm import CompletionResult
from auditor.schemas import PayCode


def _result(text: str, tier: str = "fast", tokens: int = 100) -> CompletionResult:
    return CompletionResult(
        text=text,
        tier=tier,
        model=f"stub-{tier}",
        latency_seconds=0.01,
        prompt_tokens=tokens,
        completion_tokens=20,
        total_tokens=tokens + 20,
    )


def _valid_json(counts="yes", confidence="high", unclear_question=None) -> str:
    return json.dumps(
        {
            "normalised_name": "Ordinary hours",
            "ato_category": "ordinary_hours_wages",
            "counts_towards_super": counts,
            "confidence": confidence,
            "citations": [{"source": "ATO qualifying earnings reference", "reference": "Ordinary hours wages"}],
            "reasoning": "Straightforward ordinary hours payment.",
            "question_for_reviewer": unclear_question,
        }
    )


def _stub_llm(monkeypatch, responses: list[CompletionResult]):
    queue = list(responses)

    def fake_complete(messages, *, tier="fast", temperature=0.0, **kwargs):
        assert temperature == 0.0
        if not queue:
            raise AssertionError("LLM called more times than expected")
        return queue.pop(0)

    monkeypatch.setattr(classify.llm, "complete", fake_complete)
    return queue


def make_paycode(code="ORD HRS", name="Ordinary Hours", description=None) -> PayCode:
    return PayCode(code=code, name=name, description=description, counts_for_super="Y")


def test_keyword_guess_matches_obvious_cases():
    assert classify.keyword_guess(make_paycode("OT 1.5", "Overtime 1.5x")) == "no"
    assert classify.keyword_guess(make_paycode("COMM Q3", "Commission Q3")) == "yes"
    assert classify.keyword_guess(make_paycode("MYSTERY", "Something unrelated")) is None


def test_classify_code_happy_path_no_escalation(monkeypatch):
    _stub_llm(monkeypatch, [_result(_valid_json(counts="yes", confidence="high"))])
    outcome = classify.classify_code(make_paycode())
    assert outcome.classification.counts_towards_super == "yes"
    assert outcome.escalated is False
    assert len(outcome.calls) == 1
    assert outcome.calls[0].tier == "fast"


def test_retries_once_on_invalid_json_then_succeeds(monkeypatch):
    queue = _stub_llm(
        monkeypatch,
        [_result("not json at all"), _result(_valid_json(counts="yes", confidence="high"))],
    )
    result, calls = classify._classify_with_tier(make_paycode(), None, "fast", None)
    assert result.counts_towards_super == "yes"
    assert len(calls) == 2
    assert queue == []


def test_falls_back_to_unclear_after_two_bad_attempts_on_one_tier(monkeypatch):
    _stub_llm(monkeypatch, [_result("garbage"), _result("still garbage")])
    fallback, calls = classify._classify_with_tier(make_paycode(), None, "fast", None)
    assert fallback.counts_towards_super == "unclear"
    assert fallback.confidence == "low"
    assert len(calls) == 2


def test_classify_code_escalates_all_the_way_to_unclear_when_both_tiers_fail(monkeypatch):
    _stub_llm(monkeypatch, [_result("garbage")] * 4)  # 2 fast attempts + 2 strong attempts
    outcome = classify.classify_code(make_paycode())
    assert outcome.classification.counts_towards_super == "unclear"
    assert outcome.escalated is True
    assert len(outcome.calls) == 4


def test_unclear_result_escalates_to_strong_tier(monkeypatch):
    _stub_llm(
        monkeypatch,
        [
            _result(_valid_json(counts="unclear", confidence="low"), tier="fast"),
            _result(_valid_json(counts="no", confidence="high"), tier="strong"),
        ],
    )
    outcome = classify.classify_code(make_paycode("RDO PAYOUT", "RDO Payout"))
    assert outcome.escalated is True
    assert outcome.classification.counts_towards_super == "no"
    assert [c.tier for c in outcome.calls] == ["fast", "strong"]


def test_low_confidence_escalates_even_if_not_unclear(monkeypatch):
    _stub_llm(
        monkeypatch,
        [
            _result(_valid_json(counts="yes", confidence="low"), tier="fast"),
            _result(_valid_json(counts="yes", confidence="high"), tier="strong"),
        ],
    )
    outcome = classify.classify_code(make_paycode())
    assert outcome.escalated is True
    assert [c.tier for c in outcome.calls] == ["fast", "strong"]


def test_keyword_disagreement_escalates(monkeypatch):
    # Model says overtime counts ("yes"), but the keyword check says overtime should be "no".
    _stub_llm(
        monkeypatch,
        [
            _result(_valid_json(counts="yes", confidence="high"), tier="fast"),
            _result(_valid_json(counts="no", confidence="high"), tier="strong"),
        ],
    )
    outcome = classify.classify_code(make_paycode("OT 1.5", "Overtime 1.5x"))
    assert outcome.escalated is True
    assert outcome.classification.counts_towards_super == "no"


def test_keyword_agreement_does_not_escalate(monkeypatch):
    _stub_llm(monkeypatch, [_result(_valid_json(counts="no", confidence="high"), tier="fast")])
    outcome = classify.classify_code(make_paycode("OT 1.5", "Overtime 1.5x"))
    assert outcome.escalated is False
    assert len(outcome.calls) == 1


def test_summarize_metrics_aggregates_across_outcomes(monkeypatch):
    _stub_llm(
        monkeypatch,
        [
            _result(_valid_json(counts="yes", confidence="high"), tokens=100),
            _result(_valid_json(counts="unclear", confidence="low"), tier="fast", tokens=100),
            _result(_valid_json(counts="no", confidence="high"), tier="strong", tokens=200),
        ],
    )
    outcomes = [
        classify.classify_code(make_paycode("A", "A")),
        classify.classify_code(make_paycode("B", "B")),
    ]
    metrics = classify.summarize_metrics(outcomes)
    assert metrics["codes_classified"] == 2
    assert metrics["llm_calls"] == 3
    assert metrics["escalated_count"] == 1
    assert metrics["escalated_share"] == 0.5
    assert metrics["total_tokens"] == (120 + 120 + 220)


def test_retry_prompt_includes_validation_error(monkeypatch):
    captured_messages = []

    def fake_complete(messages, *, tier="fast", temperature=0.0, **kwargs):
        captured_messages.append([m["content"] for m in messages])
        if len(captured_messages) == 1:
            return _result("{\"counts_towards_super\": \"maybe\"}")  # invalid enum value
        return _result(_valid_json(counts="yes", confidence="high"))

    monkeypatch.setattr(classify.llm, "complete", fake_complete)
    classify.classify_code(make_paycode())
    assert len(captured_messages) == 2
    retry_prompt = captured_messages[1][-1]
    assert "was not valid" in retry_prompt
