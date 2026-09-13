"""The remediation writer (spec section 6.7). For each flagged code: fix steps and a
catch-up dollar summary are built directly from data — impact.py's own numbers and the
verdict's own fields — no LLM involved, because a setting change and a dollar total are
facts, not judgement calls. Only the client-facing letter's prose is LLM-written, and
even there the model never sees the actual dollar figures: it writes placeholder tokens
("{{SUPER_AMOUNT}}") and a deterministic substitution step inserts the real numbers
afterward. This is the literal reading of "dollar figures are inserted into a template" —
not "the model is told the numbers and asked nicely to copy them correctly."

Every output is labelled as a draft for professional review.
"""

from __future__ import annotations

from . import llm
from .prompts import REMEDIATION_SYSTEM_PROMPT, REMEDIATION_USER_TEMPLATE
from .schemas import CodeVerdict, LetterResponse

DRAFT_DISCLAIMER = "This is a draft for your review, not tax or legal advice."


def _direction_description(verdict: CodeVerdict) -> str:
    if verdict.status == "should_count":
        return "currently excluded from super, but should count"
    if verdict.status == "counts_but_shouldnt":
        return "currently counted towards super, but shouldn't"
    return "flagged for manual review — no confirmed setup error yet"


def build_fix_steps(verdict: CodeVerdict) -> list[str]:
    """Deterministic — a setting change is a fact, not a judgement call."""

    if verdict.status == "should_count":
        return [
            f"Open the payroll system's pay code settings for '{verdict.code}' ({verdict.name}).",
            "Change 'Counts towards super' from N to Y.",
            "Re-run the super calculation for any pay runs already processed since the "
            "setup error began, to determine the exact catch-up amount owed.",
        ]
    if verdict.status == "counts_but_shouldnt":
        return [
            f"Open the payroll system's pay code settings for '{verdict.code}' ({verdict.name}).",
            "Change 'Counts towards super' from Y to N.",
            "Check whether any excess super already paid can be adjusted in a future "
            "contribution, or needs separate advice.",
        ]
    return [
        f"Confirm the correct qualifying-earnings treatment for '{verdict.code}' "
        "before making any change — this code was sent for manual review, not a "
        "confirmed setup error."
    ]


def _placeholder_values(verdict: CodeVerdict) -> dict[str, str]:
    impact = verdict.impact
    if impact is None:
        return {}
    values = {
        "{{ANNUAL_AMOUNT}}": f"${impact.annual_amount:,.2f}",
        "{{SUPER_AMOUNT}}": f"${impact.super_amount:,.2f}",
    }
    if impact.max_penalty_uplift is not None:
        values["{{UPLIFT}}"] = f"${impact.max_penalty_uplift:,.2f}"
    return values


_PLACEHOLDER_DESCRIPTIONS = {
    "{{ANNUAL_AMOUNT}}": "the annual amount paid on this code",
    "{{SUPER_AMOUNT}}": "the estimated super shortfall or overpayment this creates per year",
    "{{UPLIFT}}": "the maximum administrative uplift exposure, if this is an underpayment",
}


def build_catch_up_summary(verdict: CodeVerdict) -> str:
    """Deterministic, from impact.py's own numbers — never re-derived or restated by a
    model. Used for the bookkeeper's own reference, separate from the client letter."""

    impact = verdict.impact
    if impact is None:
        return (
            "No dollar impact has been calculated for this code yet — it has been sent "
            "for manual review rather than priced as a confirmed shortfall or overpayment."
        )
    if impact.direction == "should_count_not_counted":
        uplift = (
            f", plus an administrative uplift of up to ${impact.max_penalty_uplift:,.2f} and interest"
            if impact.max_penalty_uplift is not None
            else ""
        )
        return (
            f"At the current rate, this setup error is worth approximately ${impact.annual_amount:,.2f} "
            f"a year in payments that should count towards super — an estimated ${impact.super_amount:,.2f} "
            f"a year in unpaid super{uplift}. The exact catch-up amount depends on how long the code has "
            "been set up incorrectly and should be confirmed against the client's full payment history."
        )
    return (
        f"At the current rate, this code pays approximately ${impact.annual_amount:,.2f} a year that is "
        f"being counted towards super when it shouldn't be — an estimated ${impact.super_amount:,.2f} a "
        "year in super contributions paid in excess of what's required."
    )


def draft_letter(verdict: CodeVerdict) -> LetterResponse:
    placeholders = _placeholder_values(verdict)
    if placeholders:
        available = ", ".join(f"{token} ({_PLACEHOLDER_DESCRIPTIONS[token]})" for token in placeholders)
    else:
        available = "(none — no dollar impact has been calculated for this code; write around that rather than guessing a figure)"

    messages = [
        {"role": "system", "content": REMEDIATION_SYSTEM_PROMPT.format(available_placeholders=available)},
        {
            "role": "user",
            "content": REMEDIATION_USER_TEMPLATE.format(
                code=verdict.code,
                name=verdict.name,
                direction_description=_direction_description(verdict),
                reasoning=verdict.classification.reasoning,
            ),
        },
    ]
    # Some warmth for natural prose — unlike classification/verification, nothing here
    # needs to be exact; the one thing that must be exact (the dollar figures) never
    # passes through the model at all.
    result = llm.complete(messages, tier="strong", temperature=0.4)

    body = result.text.strip()
    for token, value in placeholders.items():
        body = body.replace(token, value)
    body = f"{body}\n\n{DRAFT_DISCLAIMER}"

    return LetterResponse(
        code=verdict.code,
        subject=f"Payday Super review: {verdict.code} ({verdict.name})",
        body=body,
        draft=True,
        fix_steps=build_fix_steps(verdict),
        catch_up_summary=build_catch_up_summary(verdict),
    )
