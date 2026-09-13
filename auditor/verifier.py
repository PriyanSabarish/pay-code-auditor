"""The verifier (spec section 6.4). A second model checks one thing only: does the
conclusion's own cited rule actually support it? It never re-derives the answer from
scratch — that would just be a second, uncorrelated guess, not a check.

Runs on every non-obvious verdict in "full" mode (see audit.py); disagreement sends the
code to needs_review. Counting how many disagreements happen across an audit is what
shows the verifier earns its place — see spec section 10's "Errors caught by the
verifier" metric — and falls straight out of counting CodeVerdict.verifier_agreed is
False across the results, no extra bookkeeping needed here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, ValidationError

from . import llm
from .classify import _extract_json  # shared JSON-fence stripping, not worth duplicating
from .prompts import VERIFIER_SYSTEM_PROMPT, VERIFIER_USER_TEMPLATE
from .schemas import Classification

MAX_VALIDATION_ATTEMPTS = 2  # the original call, plus exactly one retry


class _VerifierResponse(BaseModel):
    agrees: bool
    note: str


@dataclass
class VerifierOutcome:
    # None only means the verifier's own output couldn't be validated — a shrug, not a
    # disagreement. Only an explicit False should ever send a code to needs_review.
    agrees: Optional[bool]
    note: str
    calls: list[llm.CompletionResult] = field(default_factory=list)


def _format_citations(classification: Classification) -> str:
    if not classification.citations:
        return "(no citations given)"
    return "; ".join(f"{c.source} — {c.reference}" for c in classification.citations)


def verify(classification: Classification) -> VerifierOutcome:
    messages: list[dict] = [
        {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": VERIFIER_USER_TEMPLATE.format(
                code=classification.code,
                normalised_name=classification.normalised_name,
                counts_towards_super=classification.counts_towards_super,
                reasoning=classification.reasoning,
                citations=_format_citations(classification),
            ),
        },
    ]

    calls: list[llm.CompletionResult] = []
    last_error: Optional[str] = None
    for attempt in range(MAX_VALIDATION_ATTEMPTS):
        result = llm.complete(messages, tier="strong", temperature=0.0)
        calls.append(result)
        try:
            payload = json.loads(_extract_json(result.text))
            parsed = _VerifierResponse.model_validate(payload)
            return VerifierOutcome(agrees=parsed.agrees, note=parsed.note, calls=calls)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            messages.append({"role": "assistant", "content": result.text})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response was not valid: {last_error}\nReply again with ONLY the corrected JSON object.",
                }
            )

    return VerifierOutcome(
        agrees=None,
        note=f"The verifier's own output could not be validated after one retry ({last_error}); treat this conclusion as unverified.",
        calls=calls,
    )
