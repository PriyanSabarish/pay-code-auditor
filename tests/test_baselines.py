"""

keyword_baseline is deterministic, tested directly against real code
examples with no mocking needed. zero_guidance_baseline calls the LLM, so
it's mocked the same way tests/test_classify.py mocks it, patching the llm
reference as imported into the module under test.
"""

import json

import pytest

from auditor.llm import CompletionResult
from auditor.schemas import PayCode
from eval import baselines


def _paycode(code: str, name: str, description: str = None, category: str = None) -> PayCode:
    return PayCode(code=code, name=name, description=description, counts_for_super="Y", payroll_category=category)


def _completion_result(text: str) -> CompletionResult:
    return CompletionResult(
        text=text, tier="fast", model="test-model", latency_seconds=0.01,
        prompt_tokens=50, completion_tokens=20, total_tokens=70,
    )


class TestKeywordBaseline:

    def test_matches_a_known_keyword_rule(self):
        outcome = baselines.keyword_baseline(_paycode("OT15", "Overtime 1.5x"))
        assert outcome.classification.counts_towards_super == "no"
        assert outcome.classification.confidence == "medium"
        assert outcome.escalated is False
        assert outcome.calls == []  # zero model calls, zero cost

    def test_falls_back_to_unclear_with_low_confidence_on_no_match(self):
        outcome = baselines.keyword_baseline(_paycode("XYZ123", "Completely Novel Code Name"))
        assert outcome.classification.counts_towards_super == "unclear"
        assert outcome.classification.confidence == "low"
        assert outcome.classification.question_for_reviewer is not None

    def test_matches_audit_pys_keyword_only_classification_shape_exactly(self):
        """The whole point of duplicating rather than inventing new logic:
        this baseline's output must be indistinguishable from what
        run_audit(mode="keyword") produces for the same code."""
        from auditor.audit import _keyword_only_classification
        pay_code = _paycode("COMMQ3", "Commission Q3")
        from_baseline = baselines.keyword_baseline(pay_code).classification
        from_audit = _keyword_only_classification(pay_code)
        assert from_baseline.counts_towards_super == from_audit.counts_towards_super
        assert from_baseline.confidence == from_audit.confidence
        assert from_baseline.ato_category == from_audit.ato_category


class TestZeroGuidanceBaseline:

    def test_happy_path_parses_valid_json(self, monkeypatch):
        response = _completion_result(json.dumps({
            "counts_towards_super": "yes",
            "reasoning": "Commissions generally count towards super.",
        }))
        monkeypatch.setattr(baselines.llm, "complete", lambda *a, **k: response)

        outcome = baselines.zero_guidance_baseline(_paycode("COMMQ3", "Commission Q3"))
        assert outcome.classification.counts_towards_super == "yes"
        assert outcome.classification.confidence == "low"
        assert outcome.escalated is False
        assert len(outcome.calls) == 1

    def test_never_escalates_and_never_retries_even_on_bad_output(self, monkeypatch):
        call_count = {"n": 0}

        def fake_complete(*args, **kwargs):
            call_count["n"] += 1
            return _completion_result("not valid json at all")

        monkeypatch.setattr(baselines.llm, "complete", fake_complete)

        outcome = baselines.zero_guidance_baseline(_paycode("XYZ", "Something"))
        assert call_count["n"] == 1  # exactly one call, never a retry
        assert outcome.classification.counts_towards_super == "unclear"

    def test_rejects_an_out_of_range_verdict_and_falls_back_to_unclear(self, monkeypatch):
        response = _completion_result(json.dumps({
            "counts_towards_super": "maybe",  # not a valid SuperCountsStatus
            "reasoning": "Not sure.",
        }))
        monkeypatch.setattr(baselines.llm, "complete", lambda *a, **k: response)

        outcome = baselines.zero_guidance_baseline(_paycode("XYZ", "Something"))
        assert outcome.classification.counts_towards_super == "unclear"

    def test_prompt_never_contains_ato_guidance_or_qe_rules_summary(self, monkeypatch):
        """The one property that actually matters here: this baseline must
        never leak the guidance it's specifically meant to go without."""
        from auditor.prompts import QE_RULES_SUMMARY
        captured_messages = {}

        def fake_complete(messages, **kwargs):
            captured_messages["messages"] = messages
            return _completion_result(json.dumps({"counts_towards_super": "unclear", "reasoning": "x"}))

        monkeypatch.setattr(baselines.llm, "complete", fake_complete)
        baselines.zero_guidance_baseline(_paycode("XYZ", "Something"))

        full_prompt_text = " ".join(m["content"] for m in captured_messages["messages"])
        assert QE_RULES_SUMMARY not in full_prompt_text


class TestRunBaseline:

    def test_runs_keyword_baseline_across_multiple_codes(self):
        codes = [_paycode("OT15", "Overtime 1.5x"), _paycode("COMMQ3", "Commission Q3")]
        outcomes = baselines.run_baseline(baselines.keyword_baseline, codes)
        assert len(outcomes) == 2
        assert outcomes[0].classification.code == "OT15"
        assert outcomes[1].classification.code == "COMMQ3"