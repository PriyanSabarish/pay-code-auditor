"""Tests for the remediation writer. The core guarantee under test: the model never
sees real dollar figures, so it cannot mistype or invent one — this checks that
guarantee mechanically (by stubbing a completion that doesn't use the placeholders at
all, and one that does), not just that the happy path looks right.
"""

from __future__ import annotations

from auditor import remediation
from auditor.llm import CompletionResult
from auditor.schemas import Citation, Classification, CodeVerdict, ImpactResult


def _result(text: str) -> CompletionResult:
    return CompletionResult(
        text=text, tier="strong", model="stub-strong", latency_seconds=0.01,
        prompt_tokens=50, completion_tokens=30, total_tokens=80,
    )


def _classification(reasoning="Compensates for adverse conditions.") -> Classification:
    return Classification(
        code="SITE ALLOW", normalised_name="Site Allowance", ato_category="allowance",
        counts_towards_super="yes", confidence="high",
        citations=[Citation(source="ATO qualifying earnings page", reference="Table 8, row 2")],
        reasoning=reasoning,
    )


def make_verdict(status="should_count", impact=None) -> CodeVerdict:
    return CodeVerdict(
        code="SITE ALLOW", name="Site Allowance", status=status,
        classification=_classification(), investigation=[], impact=impact,
    )


def make_impact(direction="should_count_not_counted", annual=29250.0, super_amount=3510.0, uplift=2106.0):
    return ImpactResult(
        code="SITE ALLOW", direction=direction, annual_amount=annual,
        super_amount=super_amount, max_penalty_uplift=uplift,
        note="stub note",
    )


def test_build_fix_steps_for_should_count():
    steps = remediation.build_fix_steps(make_verdict(status="should_count"))
    assert any("N to Y" in s for s in steps)


def test_build_fix_steps_for_counts_but_shouldnt():
    steps = remediation.build_fix_steps(make_verdict(status="counts_but_shouldnt"))
    assert any("Y to N" in s for s in steps)


def test_build_fix_steps_for_needs_review_does_not_prescribe_a_change():
    steps = remediation.build_fix_steps(make_verdict(status="needs_review"))
    assert any("manual review" in s.lower() for s in steps)
    assert not any("Y to N" in s or "N to Y" in s for s in steps)


def test_catch_up_summary_uses_impacts_own_numbers_exactly():
    impact = make_impact()
    verdict = make_verdict(status="should_count", impact=impact)
    summary = remediation.build_catch_up_summary(verdict)
    assert "$29,250.00" in summary
    assert "$3,510.00" in summary
    assert "$2,106.00" in summary


def test_catch_up_summary_overpayment_has_no_uplift_language():
    impact = make_impact(direction="counts_should_not", annual=12480.0, super_amount=1497.6, uplift=None)
    verdict = make_verdict(status="counts_but_shouldnt", impact=impact)
    summary = remediation.build_catch_up_summary(verdict)
    assert "$1,497.60" in summary
    assert "uplift" not in summary.lower()


def test_catch_up_summary_with_no_impact_is_honest_about_it():
    summary = remediation.build_catch_up_summary(make_verdict(status="needs_review", impact=None))
    assert "no dollar impact" in summary.lower()


def test_draft_letter_substitutes_placeholders_with_exact_impact_figures(monkeypatch):
    monkeypatch.setattr(
        remediation.llm, "complete",
        lambda messages, **kwargs: _result(
            "We found that this code {{ANNUAL_AMOUNT}} annually, creating a shortfall of "
            "{{SUPER_AMOUNT}} per year, with penalty exposure up to {{UPLIFT}}."
        ),
    )
    verdict = make_verdict(status="should_count", impact=make_impact())
    letter = remediation.draft_letter(verdict)
    assert "$29,250.00" in letter.body
    assert "$3,510.00" in letter.body
    assert "$2,106.00" in letter.body
    assert "{{" not in letter.body  # no placeholder leaked through unsubstituted


def test_draft_letter_never_passes_real_numbers_into_the_prompt(monkeypatch):
    """The model must not be able to see, and therefore cannot invent or mistype, a
    real dollar figure — this checks the prompt content itself, not just the output."""

    captured = {}

    def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        return _result("Draft body with {{SUPER_AMOUNT}}.")

    monkeypatch.setattr(remediation.llm, "complete", fake_complete)
    verdict = make_verdict(status="should_count", impact=make_impact())
    remediation.draft_letter(verdict)

    full_prompt_text = " ".join(m["content"] for m in captured["messages"])
    assert "29,250" not in full_prompt_text
    assert "3,510" not in full_prompt_text
    assert "2,106" not in full_prompt_text


def test_draft_letter_with_no_impact_offers_no_placeholders(monkeypatch):
    captured = {}

    def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        return _result("Draft body with no dollar figures needed.")

    monkeypatch.setattr(remediation.llm, "complete", fake_complete)
    verdict = make_verdict(status="needs_review", impact=None)
    letter = remediation.draft_letter(verdict)
    assert "none" in captured["messages"][0]["content"].lower()
    assert letter.body  # still produces something sensible


def test_letter_always_carries_the_draft_disclaimer_and_flag(monkeypatch):
    monkeypatch.setattr(remediation.llm, "complete", lambda *a, **k: _result("Body text."))
    letter = remediation.draft_letter(make_verdict(impact=make_impact()))
    assert letter.draft is True
    assert "draft for your review" in letter.body.lower()


def test_letter_includes_fix_steps_and_catch_up_summary(monkeypatch):
    monkeypatch.setattr(remediation.llm, "complete", lambda *a, **k: _result("Body text."))
    letter = remediation.draft_letter(make_verdict(status="should_count", impact=make_impact()))
    assert letter.fix_steps
    assert letter.catch_up_summary
    assert "$3,510.00" in letter.catch_up_summary
