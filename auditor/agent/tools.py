"""The investigator's five tools (spec section 6.3). All read-only except
ask_bookkeeper, the one tool allowed to pause the investigation for human input.

Each tool takes only what the model can't already know (a search query, a yes/no
direction) — never numbers it would have to transcribe. calculate_impact re-derives the
payment history itself rather than trusting the model to repeat amounts back correctly;
"the AI never does arithmetic" extends to not even copying arithmetic inputs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from .. import retrieval
from ..impact import calculate_impact as _calculate_impact_dollars
from ..ingest import IngestError, payment_history_for_code
from ..schemas import Citation, ClarifyingQuestion, ImpactDirection, ImpactResult, PaymentHistory, PayRunRow

TOOL_NAMES = (
    "get_payment_history",
    "search_ato_guidance",
    "search_award",
    "calculate_impact",
    "ask_bookkeeper",
)


@dataclass
class ToolResult:
    """What a tool call produces: a one-line summary for the trail, an optional
    citation, and the structured payload (not shown in the trail, but available to
    whoever's driving the investigation loop)."""

    summary: str
    citation: Optional[Citation] = None
    data: object = None


def get_payment_history(code: str, payruns: list[PayRunRow]) -> ToolResult:
    try:
        history: PaymentHistory = payment_history_for_code(code, payruns)
    except IngestError:
        return ToolResult(summary=f"No pay run history found for {code!r} in the uploaded file.")

    summary = (
        f"Paid in {history.num_pay_runs} pay run(s), averaging ${history.avg_amount_per_pay_run:,.2f} "
        f"per run to {history.avg_employees_paid:g} employees on average"
    )
    if history.total_overtime_hours:
        summary += f", with {history.total_overtime_hours:g} total overtime hours recorded alongside it."
    else:
        summary += "."
    return ToolResult(summary=summary, data=history)


def _format_chunks(chunks: list[retrieval.KnowledgeChunk]) -> str:
    # Show every result, not just the top one — a real auditor scanning search results
    # would see the list and notice two rows disagree; hiding the rest behind "N more
    # found" is exactly what let the agent miss a genuine conflict in testing. Surface
    # the ATO page's own qualifying-earnings verdict explicitly too: without it, the
    # model has to infer counts/doesn't-count from the passage's wording alone, and a
    # live run showed it getting that backwards on "on-call allowance ... outside
    # ordinary hours" (correctly retrieved, then misread as counting when it doesn't).
    lines = []
    for c in chunks:
        qe_note = ""
        if c.qualifying_earnings is not None:
            qe_note = f" [qualifying earnings: {'yes' if c.qualifying_earnings else 'no'}]"
        lines.append(f"{c.reference}:{qe_note} {c.text}")
    return " | ".join(lines)


def search_ato_guidance(query: str, top_k: int = 3) -> ToolResult:
    kb = retrieval.get_knowledge_base()
    chunks = kb.search(query, top_k=top_k, category="ato_guidance")
    if not chunks:
        return ToolResult(summary="No relevant ATO guidance found for this query.")
    citations = [c.to_citation() for c in chunks]
    return ToolResult(summary=_format_chunks(chunks), citation=citations[0], data=citations)


def search_award(query: str, top_k: int = 3) -> ToolResult:
    kb = retrieval.get_knowledge_base()
    chunks = kb.search(query, top_k=top_k, category="award")
    if not chunks:
        return ToolResult(summary="No relevant award clause found for this query.")
    citations = [c.to_citation() for c in chunks]
    return ToolResult(summary=_format_chunks(chunks), citation=citations[0], data=citations)


def calculate_impact(code: str, direction: ImpactDirection, payruns: list[PayRunRow]) -> ToolResult:
    try:
        history = payment_history_for_code(code, payruns)
    except IngestError:
        return ToolResult(
            summary=f"Cannot calculate an impact for {code!r} — no pay run history was found for it."
        )
    result: ImpactResult = _calculate_impact_dollars(
        code, direction, history.avg_amount_per_pay_run, history.pay_runs_per_year
    )
    return ToolResult(summary=result.note, data=result)


def ask_bookkeeper(code: str, question: str, context: Optional[str] = None) -> ToolResult:
    clarifying_question = ClarifyingQuestion(
        id=uuid.uuid4().hex[:12], code=code, question=question, context=context
    )
    return ToolResult(
        summary="Paused — waiting on the bookkeeper's answer.",
        data=clarifying_question,
    )
