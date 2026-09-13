"""Unit tests for the bounded tool-using investigator. The LLM is stubbed throughout
(same approach as test_classify.py) — these check the loop mechanics: the six-step cap,
the ask_bookkeeper pause/resume path, trail shape, and instrumentation — not model quality.
"""

from __future__ import annotations

import json

import pytest

from auditor.agent import investigator
from auditor.llm import CompletionResult, ToolCall
from auditor.schemas import Classification, PayCode, PayRunRow

PAYRUNS = [
    PayRunRow(pay_date="2026-07-03", code="SITE ALLOW", total_amount=1125.0, employees_paid=25),
    PayRunRow(pay_date="2026-07-17", code="SITE ALLOW", total_amount=1125.0, employees_paid=25),
]

UNCERTAIN_CLASSIFICATION = Classification(
    code="SITE ALLOW",
    normalised_name="Site allowance",
    ato_category="allowance_working_conditions",
    counts_towards_super="unclear",
    confidence="low",
    citations=[],
    reasoning="Cannot tell from the name alone.",
)


def _tool_call(name: str, arguments: dict, call_id: str = "call_1", tokens: int = 50) -> CompletionResult:
    return CompletionResult(
        text="",
        tier="strong",
        model="stub-strong",
        latency_seconds=0.01,
        prompt_tokens=tokens,
        completion_tokens=10,
        total_tokens=tokens + 10,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def _conclusion(counts="yes", confidence="high", question=None, tokens: int = 50) -> CompletionResult:
    text = json.dumps(
        {
            "normalised_name": "Site allowance",
            "ato_category": "allowance_working_conditions",
            "counts_towards_super": counts,
            "confidence": confidence,
            "citations": [{"source": "Award", "reference": "cl. 19.4"}],
            "reasoning": "Compensates for site conditions.",
            "question_for_reviewer": question,
        }
    )
    return CompletionResult(
        text=text, tier="strong", model="stub-strong", latency_seconds=0.01,
        prompt_tokens=tokens, completion_tokens=10, total_tokens=tokens + 10,
    )


def _stub(monkeypatch, responses: list[CompletionResult]):
    queue = list(responses)

    def fake_complete(messages, *, tier="strong", temperature=0.0, **kwargs):
        assert temperature == 0.0
        assert kwargs.get("tools")  # the investigator must always offer its tools
        if not queue:
            raise AssertionError("LLM called more times than the test expected")
        return queue.pop(0)

    monkeypatch.setattr(investigator.llm, "complete", fake_complete)
    return queue


def make_paycode(code="SITE ALLOW", name="Site Allowance", counts_for_super="N") -> PayCode:
    return PayCode(code=code, name=name, counts_for_super=counts_for_super)


def test_concludes_immediately_with_no_tool_calls(monkeypatch):
    _stub(monkeypatch, [_conclusion(counts="yes")])
    outcome = investigator.investigate(make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION)
    assert outcome.status == "complete"
    assert outcome.conclusion.counts_towards_super == "yes"
    assert outcome.steps == []
    assert len(outcome.calls) == 1


def test_full_investigation_trail_matches_site_allow_example(monkeypatch):
    _stub(
        monkeypatch,
        [
            _tool_call("get_payment_history", {}),
            _tool_call("search_award", {"query": "site allowance"}),
            _tool_call("search_ato_guidance", {"query": "adverse working conditions"}),
            _tool_call("calculate_impact", {"direction": "should_count_not_counted"}),
            _conclusion(counts="yes", confidence="high"),
        ],
    )
    outcome = investigator.investigate(make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION)

    assert outcome.status == "complete"
    assert [s.tool for s in outcome.steps] == [
        "get_payment_history",
        "search_award",
        "search_ato_guidance",
        "calculate_impact",
    ]
    assert [s.step_number for s in outcome.steps] == [1, 2, 3, 4]
    # get_payment_history actually ran against PAYRUNS, not a canned string
    assert "1,125.00" in outcome.steps[0].output
    assert "25" in outcome.steps[0].output
    # calculate_impact actually computed real dollars via impact.py (2 pay runs 14 days
    # apart infer a 26.07, not an idealised 26, pay-run cadence — see test_ingest.py)
    from auditor.impact import calculate_underpayment_impact
    from auditor.ingest import infer_pay_runs_per_year

    expected = calculate_underpayment_impact("SITE ALLOW", 1125.0, infer_pay_runs_per_year(PAYRUNS))
    assert f"{expected.super_amount:,.2f}" in outcome.steps[3].output
    assert outcome.conclusion.counts_towards_super == "yes"
    assert len(outcome.calls) == 5


def test_step_number_field_and_shape_matches_frozen_schema(monkeypatch):
    """IT has been rendering {step_number, tool, input, output, citation} since hour 7 —
    this pins that shape."""

    _stub(monkeypatch, [_tool_call("get_payment_history", {}), _conclusion()])
    outcome = investigator.investigate(make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION)
    step = outcome.steps[0]
    assert set(step.model_dump().keys()) == {"step_number", "tool", "input", "output", "citation"}


def test_six_step_cap_is_enforced_even_if_model_never_stops(monkeypatch):
    # The model tries to call a tool forever; the loop must not let it exceed MAX_STEPS.
    _stub(monkeypatch, [_tool_call("get_payment_history", {}) for _ in range(20)])
    outcome = investigator.investigate(make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION)
    assert outcome.status == "step_limit_reached"
    assert len(outcome.steps) == investigator.MAX_STEPS
    assert len(outcome.calls) == investigator.MAX_STEPS
    assert outcome.conclusion.counts_towards_super == "unclear"
    assert outcome.conclusion.confidence == "low"


def test_ask_bookkeeper_pauses_and_stops_calling_the_model(monkeypatch):
    queue = _stub(
        monkeypatch,
        [
            _tool_call("get_payment_history", {}),
            _tool_call("ask_bookkeeper", {"question": "Is this ordinary hours?", "context": "Matters for RDOs."}),
            _conclusion(),  # must NOT be consumed — loop should stop at the pause
        ],
    )
    outcome = investigator.investigate(make_paycode("RDO PAYOUT", "RDO Payout"), PAYRUNS, UNCERTAIN_CLASSIFICATION)
    assert outcome.status == "awaiting_input"
    assert outcome.pending_question is not None
    assert outcome.pending_question.question == "Is this ordinary hours?"
    assert outcome.pending_question.code == "RDO PAYOUT"
    assert [s.tool for s in outcome.steps] == ["get_payment_history", "ask_bookkeeper"]
    assert len(queue) == 1  # the conclusion response was never touched


def test_resume_after_answer_continues_and_respects_remaining_budget(monkeypatch):
    paused = investigator.InvestigationOutcome(
        steps=[
            investigator.InvestigationStep(
                step_number=1, tool="ask_bookkeeper",
                input={"question": "Ordinary time or overtime?"},
                output="Paused — waiting on the bookkeeper's answer.",
            )
        ],
        status="awaiting_input",
    )
    _stub(monkeypatch, [_conclusion(counts="no", confidence="high")])
    outcome = investigator.investigate(
        make_paycode("RDO PAYOUT", "RDO Payout"),
        PAYRUNS,
        UNCERTAIN_CLASSIFICATION,
        resume_steps=paused.steps,
        resume_answer="Generated in lieu of overtime.",
    )
    assert outcome.status == "complete"
    assert outcome.conclusion.counts_towards_super == "no"
    assert outcome.steps == paused.steps  # no new tool steps were needed to conclude


def test_resume_feeds_the_answer_into_the_replayed_tool_result(monkeypatch):
    captured = {}

    def fake_complete(messages, *, tier="strong", temperature=0.0, **kwargs):
        captured["messages"] = messages
        return _conclusion()

    monkeypatch.setattr(investigator.llm, "complete", fake_complete)
    steps = [
        investigator.InvestigationStep(
            step_number=1, tool="ask_bookkeeper", input={"question": "q"}, output="Paused."
        )
    ]
    investigator.investigate(
        make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION, resume_steps=steps, resume_answer="the real answer"
    )
    tool_result_messages = [m for m in captured["messages"] if m.get("role") == "tool"]
    assert tool_result_messages[-1]["content"] == "the real answer"


def test_unknown_tool_name_does_not_crash_and_is_not_added_to_trail(monkeypatch):
    _stub(monkeypatch, [_tool_call("delete_everything", {}), _conclusion()])
    outcome = investigator.investigate(make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION)
    assert outcome.status == "complete"
    assert outcome.steps == []  # the bogus call never became a trail entry
    assert len(outcome.calls) == 2


def test_conclusion_retries_once_on_invalid_json(monkeypatch):
    bad = CompletionResult(
        text="not json", tier="strong", model="stub", latency_seconds=0.01,
        prompt_tokens=10, completion_tokens=5, total_tokens=15,
    )
    _stub(monkeypatch, [bad, _conclusion(counts="yes")])
    outcome = investigator.investigate(make_paycode(), PAYRUNS, UNCERTAIN_CLASSIFICATION)
    assert outcome.status == "complete"
    assert outcome.conclusion.counts_towards_super == "yes"
    assert len(outcome.calls) == 2  # both attempts are tracked for instrumentation


def test_calculate_impact_uses_real_payruns_not_model_supplied_numbers(monkeypatch):
    # The model is never given a way to pass amounts — only a direction — so there is
    # nothing for it to get arithmetically wrong.
    schema = investigator.TOOL_SCHEMAS[3]["function"]
    assert schema["name"] == "calculate_impact"
    assert set(schema["parameters"]["properties"].keys()) == {"direction"}
