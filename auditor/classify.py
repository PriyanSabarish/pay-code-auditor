"""Cascade classifier (spec section 6.2). The fast tier classifies every code; codes that
come back unclear, low-confidence, or that disagree with a simple keyword check are
escalated to the strong tier. Every LLM call is timed and token-counted from the start.

There is no retrieval yet — `context` lets a caller pass retrieved passages in once
retrieval.py exists (hours 7-10); until then the classifier falls back to the static
QE_RULES_SUMMARY baked into the prompt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from pydantic import ValidationError

from . import llm
from .llm import CompletionResult, ModelTier
from .prompts import (
    CLASSIFICATION_RETRY_SUFFIX,
    CLASSIFICATION_SYSTEM_PROMPT,
    CLASSIFICATION_USER_TEMPLATE,
    QE_RULES_SUMMARY,
)
from . import retrieval
from .schemas import Classification, PayCode, PaymentHistory, SuperCountsStatus

MAX_VALIDATION_ATTEMPTS = 2  # the original call, plus exactly one retry


@dataclass
class ClassificationOutcome:
    classification: Classification
    escalated: bool
    calls: list[CompletionResult] = field(default_factory=list)


# A deliberately simple, naive keyword check (spec 6.2) — not a classifier in its own
# right, just a cheap sanity check the model's answer can disagree with to trigger escalation.
_KEYWORD_RULES: list[tuple[re.Pattern, SuperCountsStatus]] = [
    (re.compile(r"\bovertime\b|\bo\.?t\.?\b|\bot\s*1\.\d\b", re.I), "no"),
    (re.compile(r"\bcommission", re.I), "yes"),
    (re.compile(r"\bordinary\s*hours?\b|\bord\s*hrs?\b", re.I), "yes"),
    (re.compile(r"\bcasual\s*load", re.I), "yes"),
    (re.compile(r"\bshift\s*pen|\bpenalty\b|\bsat\s*pen\b|\bsun\s*pen\b", re.I), "yes"),
    (re.compile(r"\bbonus\b", re.I), "yes"),
    (re.compile(r"\bpiln\b|\bpayment in lieu of notice\b", re.I), "yes"),
    (re.compile(r"\btoil\b.*(cash|payout)|\bcash.?out\b", re.I), "no"),
    (re.compile(r"\bon.?call\b|\bcall.?back\b", re.I), "no"),
    (re.compile(r"\bparental leave\b|\bppl\b", re.I), "no"),
    (re.compile(r"\bredundan|\bunused leave\b|\btermination\b|\bal payout term\b", re.I), "no"),
    (re.compile(r"\breimburs", re.I), "no"),
    (re.compile(r"\bdirector'?s?\s*fees?\b|\bdir fees\b", re.I), "yes"),
    (re.compile(r"\bfirst aid\b|\bleading hand\b|\bhigher duties\b|\bsupervisor\b|\bskill\b", re.I), "yes"),
    (re.compile(r"\btool allow\w*\s*\(?expend", re.I), "no"),
]


def keyword_guess(pay_code: PayCode) -> Optional[SuperCountsStatus]:
    text = f"{pay_code.code} {pay_code.name} {pay_code.description or ''}"
    for pattern, verdict in _KEYWORD_RULES:
        if pattern.search(text):
            return verdict
    return None


def build_context(pay_code: PayCode, top_k: int = 5) -> Optional[str]:
    """Retrieve ATO and award passages for one code (spec 6.2's "award-aware" step).

    The caller decides whether to use this at all — passing context=None to
    classify_code is what makes the "no_rag" eval baseline just a flag, not a fork.
    """

    query = f"{pay_code.code} {pay_code.name} {pay_code.description or ''}".strip()
    kb = retrieval.get_knowledge_base()
    chunks = kb.search(query, top_k=top_k, category="ato_guidance") + kb.search(
        query, top_k=top_k, category="award"
    )
    if not chunks:
        return None

    lines = []
    for chunk in chunks:
        # Surface the ATO page's own qualifying-earnings verdict directly when the chunk
        # carries one, so the model doesn't have to infer it from the passage's wording.
        qe_note = ""
        if chunk.qualifying_earnings is not None:
            qe_note = f" [qualifying earnings: {'yes' if chunk.qualifying_earnings else 'no'}]"
        lines.append(f"- [{chunk.source} — {chunk.reference}]{qe_note} {chunk.text}")
    return "\n".join(lines)


def _payment_pattern_summary(history: Optional[PaymentHistory]) -> str:
    if history is None:
        return "No pay run history available for this code."
    parts = [
        f"Paid in {history.num_pay_runs} of the uploaded pay runs, "
        f"averaging ${history.avg_amount_per_pay_run:,.2f} per run "
        f"to {history.avg_employees_paid:g} employees on average."
    ]
    if history.total_overtime_hours:
        parts.append(f"{history.total_overtime_hours:g} total overtime hours recorded alongside it.")
    return " ".join(parts)


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).rstrip("`").strip()
    return stripped


def _parse_and_validate(pay_code: PayCode, raw_text: str) -> Classification:
    payload = json.loads(_extract_json(raw_text))
    payload["code"] = pay_code.code
    return Classification.model_validate(payload)


def _classify_with_tier(
    pay_code: PayCode,
    history: Optional[PaymentHistory],
    tier: ModelTier,
    context: Optional[str],
) -> tuple[Classification, list[CompletionResult]]:
    """Call one tier, validating the JSON output, retrying once on invalid output, and
    falling back to an "unclear" classification rather than crashing."""

    context_block = f"\nRetrieved context:\n{context}\n" if context else ""
    system_prompt = CLASSIFICATION_SYSTEM_PROMPT.format(
        qe_rules_summary=QE_RULES_SUMMARY, context_block=context_block
    )
    user_prompt = CLASSIFICATION_USER_TEMPLATE.format(
        code=pay_code.code,
        name=pay_code.name,
        description=pay_code.description or "(none given)",
        payroll_category=pay_code.payroll_category or "(none given)",
        payment_pattern=_payment_pattern_summary(history),
    )
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    calls: list[CompletionResult] = []
    last_error: Optional[str] = None
    for attempt in range(MAX_VALIDATION_ATTEMPTS):
        result = llm.complete(messages, tier=tier, temperature=0.0)
        calls.append(result)
        try:
            return _parse_and_validate(pay_code, result.text), calls
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            messages.append({"role": "assistant", "content": result.text})
            messages.append(
                {"role": "user", "content": CLASSIFICATION_RETRY_SUFFIX.format(validation_error=last_error)}
            )

    fallback = Classification(
        code=pay_code.code,
        normalised_name=pay_code.name,
        ato_category="unresolved_parse_error",
        counts_towards_super="unclear",
        confidence="low",
        citations=[],
        reasoning=(
            "The classifier's output could not be validated after one retry "
            f"({last_error}); this code needs manual review."
        ),
        question_for_reviewer="This code needs manual review — the classifier could not produce a valid answer.",
    )
    return fallback, calls


def should_escalate(classification: Classification, pay_code: PayCode) -> bool:
    if classification.counts_towards_super == "unclear":
        return True
    if classification.confidence == "low":
        return True
    guess = keyword_guess(pay_code)
    if guess is not None and guess != classification.counts_towards_super:
        return True
    return False


def classify_code(
    pay_code: PayCode,
    history: Optional[PaymentHistory] = None,
    context: Optional[str] = None,
) -> ClassificationOutcome:
    classification, calls = _classify_with_tier(pay_code, history, "fast", context)

    if not should_escalate(classification, pay_code):
        return ClassificationOutcome(classification=classification, escalated=False, calls=calls)

    escalated_classification, escalated_calls = _classify_with_tier(pay_code, history, "strong", context)
    return ClassificationOutcome(
        classification=escalated_classification,
        escalated=True,
        calls=calls + escalated_calls,
    )


def classify_code_with_retrieval(
    pay_code: PayCode,
    history: Optional[PaymentHistory] = None,
    top_k: int = 3,
) -> ClassificationOutcome:
    """The award-aware entry point (spec's "classifier" eval mode): retrieves context
    first, then classifies with it. classify_code stays the "no_rag" baseline."""

    return classify_code(pay_code, history, build_context(pay_code, top_k=top_k))


def classify_codes(
    pay_codes: list[PayCode],
    histories: Optional[dict[str, PaymentHistory]] = None,
    contexts: Optional[dict[str, str]] = None,
    on_progress: Optional[Callable[[int, int, PayCode], None]] = None,
) -> list[ClassificationOutcome]:
    histories = histories or {}
    contexts = contexts or {}
    outcomes: list[ClassificationOutcome] = []
    for i, pay_code in enumerate(pay_codes):
        outcome = classify_code(pay_code, histories.get(pay_code.code), contexts.get(pay_code.code))
        outcomes.append(outcome)
        if on_progress:
            on_progress(i + 1, len(pay_codes), pay_code)
    return outcomes


def summarize_metrics(outcomes: list[ClassificationOutcome]) -> dict:
    """Aggregate metrics the evaluation plan asks for (spec section 10)."""

    all_calls = [c for outcome in outcomes for c in outcome.calls]
    total_tokens = sum(c.total_tokens or 0 for c in all_calls)
    total_latency = sum(c.latency_seconds for c in all_calls)
    escalated = sum(1 for o in outcomes if o.escalated)
    unclear = sum(1 for o in outcomes if o.classification.counts_towards_super == "unclear")
    return {
        "codes_classified": len(outcomes),
        "llm_calls": len(all_calls),
        "escalated_count": escalated,
        "escalated_share": round(escalated / len(outcomes), 4) if outcomes else 0.0,
        "sent_to_review_share": round(unclear / len(outcomes), 4) if outcomes else 0.0,
        "total_tokens": total_tokens,
        "total_latency_seconds": round(total_latency, 3),
        "avg_latency_seconds_per_call": round(total_latency / len(all_calls), 3) if all_calls else 0.0,
    }
