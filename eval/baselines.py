"""

The two baselines Both return a classify.ClassificationOutcome so eval/run_eval.py 
can loop over every method in the four-way comparison through one uniform shape, keyword,
zero-guidance, guidance-augmented, full cascade, without special-casing any
of them.

Where each of the four spec comparison points actually lives:

  1. Keyword rules only       -> baselines.keyword_baseline (this file)
  2. Model, no ATO guidance   -> baselines.zero_guidance_baseline (this file)
  3. Model, with ATO guidance -> classify.classify_code_with_retrieval
  4. Full cascade (the product) -> audit.run_audit(mode="full")

Baseline 1 deliberately replicates audit.py's _keyword_only_classification
logic exactly, same category, confidence and reasoning text, rather than
inventing a different keyword baseline. That keeps the "keyword" row
identical whether it's produced by calling run_audit(mode="keyword") or by
calling this function directly, so the two code paths can never quietly
disagree with each other.

Baseline 2 exists because every mode already in classify.py, including the
one named "no_rag", unconditionally bakes the static QE_RULES_SUMMARY into
its prompt. "no_rag" means no retrieved passages, not no guidance. Nothing
in the codebase represents a genuinely zero-guidance call before this file,
the exact thing spec section 8's second comparison row asks for: what a
general chatbot, asked with no reference material at all, would answer. A
single fast-tier call, no retries, no escalation, no citations, deliberately
the cheapest and least informed method in the comparison.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from auditor import llm
from auditor.classify import ClassificationOutcome, keyword_guess
from auditor.schemas import Classification, PayCode, PaymentHistory, SuperCountsStatus

ZERO_GUIDANCE_SYSTEM_PROMPT = (
    "You are helping a bookkeeper review Australian payroll. For each pay "
    "code, decide whether payments under that code count towards the "
    "employee's superannuation guarantee earnings base. Answer using only "
    "your own knowledge, you have not been given any reference material.\n\n"
    "Respond with strict JSON only, no other text:\n"
    '{"counts_towards_super": "yes" | "no" | "unclear", "reasoning": "one or two sentences"}'
)

ZERO_GUIDANCE_USER_TEMPLATE = (
    "Pay code: {code}\n"
    "Name: {name}\n"
    "Description: {description}\n"
    "Payroll category: {payroll_category}\n\n"
    "Does this pay code count towards superannuation guarantee earnings?"
)


def _extract_json(text: str) -> str:
    """Duplicated from classify.py's private helper rather than imported,
    it's three lines and this keeps baselines.py from depending on another
    module's internal, underscore-prefixed implementation detail."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).rstrip("`").strip()
    return stripped


def keyword_baseline(
    pay_code: PayCode, history: Optional[PaymentHistory] = None
) -> ClassificationOutcome:
    """Deterministic, zero model calls, zero cost, zero latency. Matches
    audit.py's mode="keyword" path exactly."""
    guess: Optional[SuperCountsStatus] = keyword_guess(pay_code)
    classification = Classification(
        code=pay_code.code,
        normalised_name=pay_code.name,
        ato_category="keyword_match" if guess else "no_keyword_match",
        counts_towards_super=guess or "unclear",
        confidence="medium" if guess else "low",
        citations=[],
        reasoning=(
            f"Matched a simple keyword rule (counts_towards_super={guess})."
            if guess
            else "No keyword rule matched this code name."
        ),
        question_for_reviewer=None if guess else "No keyword rule matched; needs manual classification.",
    )
    return ClassificationOutcome(classification=classification, escalated=False, calls=[])


def zero_guidance_baseline(
    pay_code: PayCode, history: Optional[PaymentHistory] = None
) -> ClassificationOutcome:
    """One fast-tier call, no ATO guidance in the prompt at all, not even
    the static rules summary every other mode includes unconditionally.
    Never retries, never escalates, since the whole point is showing what
    the cheapest possible approach gets wrong."""
    messages = [
        {"role": "system", "content": ZERO_GUIDANCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": ZERO_GUIDANCE_USER_TEMPLATE.format(
                code=pay_code.code,
                name=pay_code.name,
                description=pay_code.description or "(none given)",
                payroll_category=pay_code.payroll_category or "(none given)",
            ),
        },
    ]
    result = llm.complete(messages, tier="fast", temperature=0.0)

    verdict: SuperCountsStatus = "unclear"
    reasoning = "(no reasoning given)"
    try:
        payload = json.loads(_extract_json(result.text))
        candidate = payload.get("counts_towards_super", "unclear")
        if candidate in ("yes", "no", "unclear"):
            verdict = candidate
        reasoning = payload.get("reasoning", reasoning)
    except (json.JSONDecodeError, AttributeError):
        reasoning = f"Could not parse a JSON verdict from the model's response: {result.text[:200]!r}"

    classification = Classification(
        code=pay_code.code,
        normalised_name=pay_code.name,
        ato_category="zero_guidance_baseline",
        counts_towards_super=verdict,
        confidence="low",
        citations=[],
        reasoning=reasoning,
        question_for_reviewer=None,
    )
    return ClassificationOutcome(classification=classification, escalated=False, calls=[result])


def run_baseline(
    baseline_fn,
    pay_codes: list[PayCode],
    histories: Optional[dict[str, PaymentHistory]] = None,
) -> list[ClassificationOutcome]:
    """Runs any baseline function across a list of pay codes. Takes the
    baseline function itself as the first argument so eval/run_eval.py can
    loop over {"keyword": keyword_baseline, "zero_guidance": zero_guidance_baseline}
    without writing a separate loop for each one."""
    histories = histories or {}
    return [baseline_fn(pay_code, histories.get(pay_code.code)) for pay_code in pay_codes]