"""Tests for the real audit orchestrator. classify_code/classify_code_with_retrieval/
investigate are mocked at the boundary — their own behaviour is already covered by
test_classify.py and test_investigator.py; this file tests the orchestration logic:
status determination, when investigation triggers, impact pricing, and the
ask_bookkeeper pause/resume loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from auditor import audit
from auditor.agent.investigator import InvestigationOutcome
from auditor.classify import ClassificationOutcome
from auditor.schemas import Classification, ClarifyingQuestion, InvestigationStep, PayCode, PayRunRow

PAYRUNS = [
    PayRunRow(pay_date="2026-07-03", code="SITE ALLOW", total_amount=1125.0, employees_paid=25),
    PayRunRow(pay_date="2026-07-17", code="SITE ALLOW", total_amount=1125.0, employees_paid=25),
]


def _classification(counts="yes", confidence="high") -> Classification:
    return Classification(
        code="SITE ALLOW", normalised_name="Site Allowance", ato_category="allowance",
        counts_towards_super=counts, confidence=confidence, citations=[], reasoning="stub",
    )


def make_paycode(code="SITE ALLOW", name="Site Allowance", counts_for_super="N") -> PayCode:
    return PayCode(code=code, name=name, counts_for_super=counts_for_super)


def test_correct_status_when_setting_matches_classification(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="no", confidence="high"), escalated=False),
    )
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="classifier")
    assert verdict.status == "correct"
    assert verdict.impact is None


def test_should_count_status_when_excluded_but_should_count(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="yes", confidence="high"), escalated=False),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high")))
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="agent")
    assert verdict.status == "should_count"
    assert verdict.impact is not None
    assert verdict.impact.direction == "should_count_not_counted"


def test_counts_but_shouldnt_status_and_impact(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="no", confidence="high"), escalated=False),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="complete", conclusion=_classification("no", "high")))
    verdict = audit.audit_one_code(make_paycode(counts_for_super="Y"), PAYRUNS, mode="agent")
    assert verdict.status == "counts_but_shouldnt"
    assert verdict.impact.direction == "counts_should_not"


def test_unclear_classification_is_needs_review(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="step_limit_reached", conclusion=_classification("unclear", "low")))
    verdict = audit.audit_one_code(make_paycode(), PAYRUNS, mode="agent")
    assert verdict.status == "needs_review"
    assert verdict.impact is None


def test_investigation_not_triggered_for_confident_correct_classification(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="no", confidence="high"), escalated=False),
    )
    def fail_if_called(*a, **k):
        raise AssertionError("investigate() should not run for a confident, correct classification")
    monkeypatch.setattr(audit, "investigate", fail_if_called)
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="full")
    assert verdict.status == "correct"
    assert verdict.investigation == []


def test_investigation_updates_the_final_classification(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    revised = _classification(counts="yes", confidence="high")
    steps = [InvestigationStep(step_number=1, tool="get_payment_history", input={}, output="stub")]
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=steps, status="complete", conclusion=revised))
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="agent")
    assert verdict.classification.counts_towards_super == "yes"
    assert verdict.status == "should_count"
    assert verdict.investigation == steps


def test_ask_bookkeeper_loop_resumes_until_complete(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    question = ClarifyingQuestion(id="q1", code="SITE ALLOW", question="Ordinary time?")
    paused = InvestigationOutcome(
        steps=[InvestigationStep(step_number=1, tool="ask_bookkeeper", input={"question": "Ordinary time?"}, output="Paused.")],
        status="awaiting_input",
        pending_question=question,
    )
    resumed = InvestigationOutcome(steps=paused.steps, status="complete", conclusion=_classification("yes", "high"))

    calls = {"n": 0}
    def fake_investigate(pay_code, payruns, classification, resume_steps=None, resume_answer=None):
        calls["n"] += 1
        if calls["n"] == 1:
            assert resume_steps is None
            return paused
        assert resume_answer == "Yes, ordinary time."
        return resumed
    monkeypatch.setattr(audit, "investigate", fake_investigate)

    received_questions = []
    def ask_bookkeeper(q):
        received_questions.append(q)
        return "Yes, ordinary time."

    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="agent", ask_bookkeeper=ask_bookkeeper)
    assert calls["n"] == 2
    assert received_questions == [question]
    assert verdict.classification.counts_towards_super == "yes"
    assert verdict.status == "should_count"


def test_fresh_bookkeeper_answer_is_recorded_in_the_trail(monkeypatch):
    """tools.ask_bookkeeper's step output is a generic "Paused..." placeholder — without
    rewriting it here, a freshly-answered pause looks identical to one that was never
    resolved once the audit completes, and the actual question/answer are lost from the
    permanent record (they only ever existed in the transient pending_question)."""

    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    question = ClarifyingQuestion(id="q1", code="SITE ALLOW", question="Ordinary time?")
    paused = InvestigationOutcome(
        steps=[InvestigationStep(step_number=1, tool="ask_bookkeeper", input={"question": "Ordinary time?"}, output="Paused.")],
        status="awaiting_input",
        pending_question=question,
    )
    resumed = InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high"))

    calls = {"n": 0}
    captured_resume_steps = []
    def fake_investigate(pay_code, payruns, classification, resume_steps=None, resume_answer=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return paused
        captured_resume_steps.append(resume_steps)
        return resumed
    monkeypatch.setattr(audit, "investigate", fake_investigate)

    audit.audit_one_code(
        make_paycode(counts_for_super="N"), PAYRUNS, mode="agent",
        ask_bookkeeper=lambda q: "Yes, ordinary time.",
    )
    resumed_steps = captured_resume_steps[0]
    assert "Ordinary time?" in resumed_steps[-1].output
    assert "Yes, ordinary time." in resumed_steps[-1].output
    assert resumed_steps[-1].output != "Paused."


def test_remembered_answer_is_used_without_calling_ask_bookkeeper(monkeypatch):
    """Spec 6.5: an already-answered code pattern for this bookkeeper skips asking
    again entirely — the audit shouldn't even pause for a human this time."""

    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    question = ClarifyingQuestion(id="q1", code="SITE ALLOW", question="Ordinary time?")
    paused = InvestigationOutcome(
        steps=[InvestigationStep(step_number=1, tool="ask_bookkeeper", input={"question": "Ordinary time?"}, output="Paused.")],
        status="awaiting_input",
        pending_question=question,
    )
    resumed = InvestigationOutcome(steps=paused.steps, status="complete", conclusion=_classification("yes", "high"))

    calls = {"n": 0}
    captured_resume_steps = []
    def fake_investigate(pay_code, payruns, classification, resume_steps=None, resume_answer=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return paused
        captured_resume_steps.append(resume_steps)
        assert resume_answer == "Remembered: ordinary time."
        return resumed
    monkeypatch.setattr(audit, "investigate", fake_investigate)

    audit.memory.get_memory().remember("default", "SITE ALLOW", "Ordinary time?", "Remembered: ordinary time.")

    def fail_if_asked(q):
        raise AssertionError("should not ask the bookkeeper when memory already has the answer")

    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="agent", ask_bookkeeper=fail_if_asked)
    assert calls["n"] == 2
    assert verdict.classification.counts_towards_super == "yes"
    # The trail must say this was answered from memory, not a fresh human pause —
    # otherwise the two look identical to anyone reading the results.
    resumed_steps = captured_resume_steps[0]
    assert "Answered from memory" in resumed_steps[-1].output
    assert "Remembered: ordinary time." in resumed_steps[-1].output


def test_a_new_answer_is_remembered_for_next_time(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    question = ClarifyingQuestion(id="q1", code="SITE ALLOW", question="Ordinary time?")
    paused = InvestigationOutcome(
        # A real investigate() always appends the ask_bookkeeper step before pausing —
        # never an empty list — so this matches that rather than a shape that can't
        # actually occur.
        steps=[InvestigationStep(step_number=1, tool="ask_bookkeeper", input={"question": "Ordinary time?"}, output="Paused.")],
        status="awaiting_input", pending_question=question,
    )
    resumed = InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high"))
    calls = {"n": 0}
    def fake_investigate(pay_code, payruns, classification, resume_steps=None, resume_answer=None):
        calls["n"] += 1
        return paused if calls["n"] == 1 else resumed
    monkeypatch.setattr(audit, "investigate", fake_investigate)

    audit.audit_one_code(
        make_paycode(counts_for_super="N"), PAYRUNS, mode="agent",
        ask_bookkeeper=lambda q: "Yes, ordinary time.",
    )

    remembered = audit.memory.get_memory().recall("default", "SITE ALLOW")
    assert remembered is not None
    assert remembered.answer == "Yes, ordinary time."
    assert remembered.question == "Ordinary time?"


def test_ask_bookkeeper_none_stops_at_the_pause_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification(counts="unclear", confidence="low"), escalated=True),
    )
    paused = InvestigationOutcome(steps=[], status="awaiting_input", pending_question=ClarifyingQuestion(id="q1", code="SITE ALLOW", question="?"))
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: paused)
    verdict = audit.audit_one_code(make_paycode(), PAYRUNS, mode="agent", ask_bookkeeper=None)
    assert verdict.status == "needs_review"  # falls back to the pre-investigation classification


def test_keyword_mode_uses_no_llm_at_all(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("keyword mode must not call the LLM classifier")
    monkeypatch.setattr(audit, "classify_code", fail_if_called)
    monkeypatch.setattr(audit, "classify_code_with_retrieval", fail_if_called)
    verdict = audit.audit_one_code(make_paycode("OT 1.5", "Overtime 1.5x", counts_for_super="N"), PAYRUNS, mode="keyword")
    assert verdict.classification.counts_towards_super == "no"
    assert verdict.status == "correct"


def test_no_rag_mode_calls_classify_code_not_the_retrieval_variant(monkeypatch):
    calls = {"no_rag": 0, "rag": 0}
    monkeypatch.setattr(audit, "classify_code", lambda pc, h: calls.__setitem__("no_rag", calls["no_rag"] + 1) or ClassificationOutcome(classification=_classification("no", "high"), escalated=False))
    def fail_if_called(*a, **k):
        raise AssertionError("no_rag mode must not use retrieval")
    monkeypatch.setattr(audit, "classify_code_with_retrieval", fail_if_called)
    audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="no_rag")
    assert calls["no_rag"] == 1


def test_run_audit_calls_progress_and_verdict_callbacks_in_order(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification("no", "high"), escalated=False),
    )
    codes = [make_paycode("A", "A", "N"), make_paycode("B", "B", "N")]
    seen_verdicts = []
    seen_progress = []
    verdicts = audit.run_audit(
        codes, [], "hospitality_ma000009", mode="classifier",
        on_verdict=seen_verdicts.append,
        on_progress=lambda i, n, code: seen_progress.append((i, n, code)),
    )
    assert [v.code for v in verdicts] == ["A", "B"]
    assert [v.code for v in seen_verdicts] == ["A", "B"]
    assert seen_progress == [(1, 2, "A"), (2, 2, "B")]


# --- verifier wiring (full mode only) -----------------------------------------------


def test_verifier_not_called_outside_full_mode(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification("yes", "high"), escalated=False),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high")))
    def fail_if_called(classification):
        raise AssertionError("verifier must not run outside full mode")
    monkeypatch.setattr(audit, "verify", fail_if_called)
    audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="agent")  # non-obvious, but not full


def test_verifier_not_called_for_a_confident_correct_verdict_even_in_full_mode(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification("no", "high"), escalated=False),
    )
    def fail_if_called(classification):
        raise AssertionError("verifier must not run on an obvious, already-correct verdict")
    monkeypatch.setattr(audit, "verify", fail_if_called)
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="full")
    assert verdict.status == "correct"
    assert verdict.verifier_agreed is None


def test_verifier_agreement_is_recorded_and_status_unchanged(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification("yes", "high"), escalated=False),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high")))
    from auditor.verifier import VerifierOutcome
    monkeypatch.setattr(audit, "verify", lambda classification: VerifierOutcome(agrees=True, note="Supported."))
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="full")
    assert verdict.verifier_agreed is True
    assert verdict.status == "should_count"  # unchanged by agreement


def test_verifier_disagreement_forces_needs_review_and_drops_impact(monkeypatch):
    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification("yes", "high"), escalated=False),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high")))
    from auditor.verifier import VerifierOutcome
    monkeypatch.setattr(audit, "verify", lambda classification: VerifierOutcome(agrees=False, note="The rule says the opposite."))
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="full")
    assert verdict.verifier_agreed is False
    assert verdict.status == "needs_review"
    assert verdict.impact is None  # needs_review isn't a priced status


def test_verifier_none_result_does_not_change_status(monkeypatch):
    """A verifier whose own output couldn't be validated is a shrug, not a disagreement
    — it must never silently downgrade a verdict to needs_review."""

    monkeypatch.setattr(
        audit, "classify_code_with_retrieval",
        lambda pc, h: ClassificationOutcome(classification=_classification("yes", "high"), escalated=False),
    )
    monkeypatch.setattr(audit, "investigate", lambda *a, **k: InvestigationOutcome(steps=[], status="complete", conclusion=_classification("yes", "high")))
    from auditor.verifier import VerifierOutcome
    monkeypatch.setattr(audit, "verify", lambda classification: VerifierOutcome(agrees=None, note="Could not validate."))
    verdict = audit.audit_one_code(make_paycode(counts_for_super="N"), PAYRUNS, mode="full")
    assert verdict.verifier_agreed is None
    assert verdict.status == "should_count"
