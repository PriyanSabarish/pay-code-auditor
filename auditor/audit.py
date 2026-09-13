"""Real audit orchestration — classify every code, investigate the suspicious ones,
verify non-obvious conclusions, price the exact dollar impact. This is what api/jobs.py
drives in the background once FAKE_DATA=0, and what the eval harness will call directly
later, bypassing HTTP.

Deliberately returns list[CodeVerdict] rather than a full AuditResult: an audit_id,
status and timestamps are job-store concerns (api/jobs.py), not something a pure
function calling the LLM cascade should have to fabricate for itself.

The verifier only runs in "full" mode, and only on non-obvious verdicts (the same test
that triggers investigation) — spec 6.4 is a check on a conclusion someone should
double-check, not a second opinion on every trivially-correct code. Counting how many
times CodeVerdict.verifier_agreed is False across a set of verdicts is the "errors
caught by the verifier" eval metric (spec section 10); no separate counter needed here.
"""

from __future__ import annotations

from typing import Callable, Optional

from . import memory
from .agent.investigator import investigate
from .classify import classify_code, classify_code_with_retrieval, keyword_guess
from .impact import calculate_impact
from .ingest import IngestError, payment_history_for_code
from .schemas import (
    AuditMode,
    Classification,
    ClarifyingQuestion,
    CodeVerdict,
    ImpactResult,
    PayCode,
    PayRunRow,
    PaymentHistory,
    VerdictStatus,
)
from .verifier import verify

AskBookkeeper = Callable[[ClarifyingQuestion], str]
OnVerdict = Callable[[CodeVerdict], None]
OnProgress = Callable[[int, int, str], None]


def _history_for(code: str, payruns: list[PayRunRow]) -> Optional[PaymentHistory]:
    try:
        return payment_history_for_code(code, payruns)
    except IngestError:
        return None


def _keyword_only_classification(pay_code: PayCode) -> Classification:
    guess = keyword_guess(pay_code)
    return Classification(
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


def _status_for(current_setting: str, counts_towards_super: str) -> VerdictStatus:
    if counts_towards_super == "unclear":
        return "needs_review"
    currently_counts = current_setting == "Y"
    should_count = counts_towards_super == "yes"
    if currently_counts == should_count:
        return "correct"
    return "should_count" if should_count else "counts_but_shouldnt"


def _needs_investigation(classification: Classification, status: VerdictStatus) -> bool:
    """Spec 6.3: investigate codes that are unclear, low confidence, or where the
    current payroll setting disagrees with the classification."""

    return classification.counts_towards_super == "unclear" or classification.confidence == "low" or status != "correct"


def _impact_for(pay_code: PayCode, status: VerdictStatus, payruns: list[PayRunRow]) -> Optional[ImpactResult]:
    if status not in ("should_count", "counts_but_shouldnt"):
        return None
    history = _history_for(pay_code.code, payruns)
    if history is None:
        return None
    direction = "should_count_not_counted" if status == "should_count" else "counts_should_not"
    return calculate_impact(pay_code.code, direction, history.avg_amount_per_pay_run, history.pay_runs_per_year)


def _resolve_pending_questions(
    pay_code: PayCode,
    payruns: list[PayRunRow],
    classification: Classification,
    ask_bookkeeper: Optional[AskBookkeeper],
    bookkeeper_id: str,
):
    """Run the investigator, resolving any ask_bookkeeper pause either from memory (spec
    6.5 — an already-answered code pattern for this bookkeeper skips asking again) or,
    failing that, synchronously via the given callback — then remembers the answer for
    next time."""

    outcome = investigate(pay_code, payruns, classification)
    while outcome.status == "awaiting_input":
        question = outcome.pending_question
        steps = outcome.steps
        remembered = memory.get_memory().recall(bookkeeper_id, pay_code.code)
        if remembered is not None:
            answer = remembered.answer
            # Make it visible in the trail that this was answered from memory, not a
            # fresh human pause — otherwise the two are indistinguishable to anyone
            # looking at the results, which makes this feature unverifiable by eye.
            steps = steps[:-1] + [
                steps[-1].model_copy(
                    update={"output": f"Answered from memory (recorded {remembered.stored_at[:10]}): {answer}"}
                )
            ]
        elif ask_bookkeeper is not None:
            answer = ask_bookkeeper(question)
            memory.get_memory().remember(bookkeeper_id, pay_code.code, question.question, answer)
            # Same reasoning as the memory branch above: without this, the evidence
            # trail's ask_bookkeeper step is stuck on tools.py's generic "Paused —
            # waiting on the bookkeeper's answer." forever, even after a real answer
            # resolves it — the question and answer would exist only in the transient
            # pending_question shown while paused, gone from the permanent record once
            # the audit completes.
            steps = steps[:-1] + [
                steps[-1].model_copy(
                    update={"output": f"Bookkeeper asked: \"{question.question}\" — Answered: {answer}"}
                )
            ]
        else:
            break  # no memory of this code and no one to ask — keep the trail, stay unclear
        outcome = investigate(
            pay_code, payruns, classification, resume_steps=steps, resume_answer=answer
        )
    return outcome


def audit_one_code(
    pay_code: PayCode,
    payruns: list[PayRunRow],
    mode: AuditMode,
    ask_bookkeeper: Optional[AskBookkeeper] = None,
    bookkeeper_id: str = memory.DEFAULT_BOOKKEEPER_ID,
) -> CodeVerdict:
    """Classify, optionally investigate, optionally verify, and price one pay code."""

    print(f"[audit] {pay_code.code}: classifying ({mode} mode)...", flush=True)
    investigation: list = []

    if mode == "keyword":
        classification = _keyword_only_classification(pay_code)
    else:
        history = _history_for(pay_code.code, payruns)
        outcome = classify_code(pay_code, history) if mode == "no_rag" else classify_code_with_retrieval(pay_code, history)
        classification = outcome.classification

        status = _status_for(pay_code.counts_for_super, classification.counts_towards_super)
        if mode in ("agent", "full") and _needs_investigation(classification, status):
            print(f"[audit] {pay_code.code}: needs investigation (confidence={classification.confidence}, status={status})", flush=True)
            investigation_outcome = _resolve_pending_questions(
                pay_code, payruns, classification, ask_bookkeeper, bookkeeper_id
            )
            investigation = investigation_outcome.steps
            if investigation_outcome.conclusion is not None:
                classification = investigation_outcome.conclusion

    status = _status_for(pay_code.counts_for_super, classification.counts_towards_super)

    verifier_agreed: Optional[bool] = None
    if mode == "full" and _needs_investigation(classification, status):
        print(f"[audit] {pay_code.code}: verifying conclusion...", flush=True)
        verifier_outcome = verify(classification)
        verifier_agreed = verifier_outcome.agrees
        if verifier_agreed is False:
            status = "needs_review"

    impact = _impact_for(pay_code, status, payruns)

    return CodeVerdict(
        code=pay_code.code,
        name=pay_code.name,
        status=status,
        classification=classification,
        investigation=investigation,
        verifier_agreed=verifier_agreed,
        impact=impact,
    )


def run_audit(
    paycodes: list[PayCode],
    payruns: list[PayRunRow],
    award_id: str,
    mode: AuditMode = "full",
    on_verdict: Optional[OnVerdict] = None,
    on_progress: Optional[OnProgress] = None,
    ask_bookkeeper: Optional[AskBookkeeper] = None,
    bookkeeper_id: str = memory.DEFAULT_BOOKKEEPER_ID,
) -> list[CodeVerdict]:
    """Audit every pay code, in order. award_id is accepted for interface symmetry with
    the API and future award-specific behaviour — retrieval already scopes to one
    knowledge base per the "one award at a time" limitation, so it isn't threaded
    through further yet. bookkeeper_id defaults to a single-tenant stand-in until real
    accounts exist — see memory.py.
    """

    verdicts: list[CodeVerdict] = []
    for i, pay_code in enumerate(paycodes):
        verdict = audit_one_code(pay_code, payruns, mode, ask_bookkeeper, bookkeeper_id)
        verdicts.append(verdict)
        if on_verdict:
            on_verdict(verdict)
        if on_progress:
            on_progress(i + 1, len(paycodes), pay_code.code)
    return verdicts
