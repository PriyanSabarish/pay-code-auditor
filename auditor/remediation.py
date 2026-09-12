"""Draft client letters (spec section 6.7). Dollar figures always come from impact.py;
the model writes only the prose around them. Every output is labelled as a draft.

Full version (LLM-written prose, fix steps, catch-up summary) lands in hours 21-25. This
is a template-only placeholder so GET /api/audits/{id}/letter/{code} works today.
"""

from __future__ import annotations

from .schemas import CodeVerdict, LetterResponse


def draft_letter(verdict: CodeVerdict) -> LetterResponse:
    if verdict.impact is None:
        body = (
            f"We reviewed the pay code '{verdict.code}' ({verdict.name}) as part of your "
            f"Payday Super audit.\n\n{verdict.classification.reasoning}\n\n"
            "This is a draft for your review, not tax or legal advice."
        )
    else:
        direction = (
            "was not counting towards super but should be"
            if verdict.impact.direction == "should_count_not_counted"
            else "was counting towards super but shouldn't be"
        )
        body = (
            f"We reviewed the pay code '{verdict.code}' ({verdict.name}) as part of your "
            f"Payday Super audit and found it {direction}.\n\n"
            f"{verdict.impact.note}\n\n"
            f"{verdict.classification.reasoning}\n\n"
            "This is a draft for your review, not tax or legal advice."
        )
    return LetterResponse(
        code=verdict.code,
        subject=f"Payday Super review: {verdict.code} ({verdict.name})",
        body=body,
        draft=True,
    )
