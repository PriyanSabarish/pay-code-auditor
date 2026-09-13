"""In-memory audit job store, plus the fake-data background simulation for the hour-2
contract (spec section 4/8).

A single dict in the process — this is why the deploy note in the spec insists on ONE
uvicorn worker. If this ever needs more than one worker, move this store to SQLite first.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from auditor.audit import run_audit
from auditor.schemas import (
    AuditJob,
    AuditMode,
    AuditProgress,
    AuditStatus,
    ClarifyingQuestion,
    CodeVerdict,
    PayCode,
    PayRunRow,
    ReviewerDecision,
    SuperCountsStatus,
)

from .config import FAKE_STEP_DELAY_SECONDS

_jobs: dict[str, AuditJob] = {}
_resume_events: dict[str, threading.Event] = {}
_pending_answers: dict[str, str] = {}
_lock = threading.Lock()


class JobError(Exception):
    """Raised for invalid job operations: unknown id, wrong state, stale question id."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_job(award_id: str, mode: AuditMode) -> AuditJob:
    audit_id = uuid.uuid4().hex[:12]
    now = _now()
    job = AuditJob(
        audit_id=audit_id,
        award_id=award_id,
        mode=mode,
        status=AuditStatus.QUEUED,
        progress=AuditProgress(total_codes=0, processed_codes=0),
        verdicts=[],
        pending_question=None,
        created_at=now,
        updated_at=now,
    )
    with _lock:
        _jobs[audit_id] = job
    return job


def get_job(audit_id: str) -> Optional[AuditJob]:
    with _lock:
        return _jobs.get(audit_id)


def _save(job: AuditJob) -> None:
    job.updated_at = _now()
    with _lock:
        _jobs[job.audit_id] = job


def set_verdict_decision(
    job: AuditJob,
    code: str,
    decision: ReviewerDecision,
    note: str | None,
    overridden_counts_towards_super: SuperCountsStatus | None = None,
) -> CodeVerdict:
    for v in job.verdicts:
        if v.code == code:
            v.reviewer_decision = decision
            v.override_note = note
            v.overridden_counts_towards_super = overridden_counts_towards_super
            _save(job)
            return v
    raise JobError(f"no verdict found for code {code!r} in audit {job.audit_id}")


def answer_question(job: AuditJob, question_id: str, answer: str) -> AuditJob:
    if job.status != AuditStatus.AWAITING_INPUT or job.pending_question is None:
        raise JobError(f"audit {job.audit_id} is not awaiting a question")
    if job.pending_question.id != question_id:
        raise JobError(f"question {question_id!r} does not match the pending question")

    event = _resume_events.get(job.audit_id)
    if event is None:
        raise JobError(f"audit {job.audit_id} has no investigation to resume")
    _pending_answers[job.audit_id] = answer
    event.set()
    return job


def start_fake_audit(job: AuditJob, verdicts: list[CodeVerdict]) -> None:
    """Simulate a real run: stream verdicts in one at a time, pausing on the first one
    that carries a pending question, exactly like the real investigator will."""

    job.progress = AuditProgress(total_codes=len(verdicts), processed_codes=0)
    job.status = AuditStatus.RUNNING
    _save(job)

    event = threading.Event()
    _resume_events[job.audit_id] = event

    thread = threading.Thread(target=_run_fake_audit, args=(job.audit_id, verdicts), daemon=True)
    thread.start()


def _run_fake_audit(audit_id: str, verdicts: list[CodeVerdict]) -> None:
    for verdict in verdicts:
        time.sleep(FAKE_STEP_DELAY_SECONDS)
        job = get_job(audit_id)
        if job is None:
            return

        if verdict.pending_question is not None:
            job.pending_question = verdict.pending_question
            job.status = AuditStatus.AWAITING_INPUT
            job.progress.current_step = f"Waiting on your answer for {verdict.code}"
            _save(job)

            event = _resume_events.get(audit_id)
            if event is not None:
                event.wait()
                event.clear()

            job = get_job(audit_id)
            if job is None:
                return
            job.pending_question = None
            job.status = AuditStatus.RUNNING

        job.verdicts.append(verdict)
        job.progress.processed_codes += 1
        job.progress.current_step = f"Classified {verdict.code}"
        _save(job)

    job = get_job(audit_id)
    if job is not None:
        job.status = AuditStatus.COMPLETE
        job.progress.current_step = None
        _save(job)
    _resume_events.pop(audit_id, None)


def start_real_audit(
    job: AuditJob, paycodes: list[PayCode], payruns: list[PayRunRow], award_id: str, mode: AuditMode
) -> None:
    """Run the real classifier/investigator pipeline in the background. Pauses on a
    genuine ask_bookkeeper call exactly like the fake simulation does, via the same
    threading.Event mechanism — the only difference is the answer text actually flows
    back into investigate(resume_answer=...) instead of being ignored."""

    job.progress = AuditProgress(total_codes=len(paycodes), processed_codes=0)
    job.status = AuditStatus.RUNNING
    _save(job)

    event = threading.Event()
    _resume_events[job.audit_id] = event

    thread = threading.Thread(
        target=_run_real_audit, args=(job.audit_id, paycodes, payruns, award_id, mode), daemon=True
    )
    thread.start()


def _make_ask_bookkeeper(audit_id: str):
    def ask(question: ClarifyingQuestion) -> str:
        job = get_job(audit_id)
        if job is None:
            return ""
        job.pending_question = question
        job.status = AuditStatus.AWAITING_INPUT
        job.progress.current_step = f"Waiting on your answer for {question.code}"
        _save(job)

        event = _resume_events.get(audit_id)
        if event is not None:
            event.wait()
            event.clear()
        answer = _pending_answers.pop(audit_id, "")

        job = get_job(audit_id)
        if job is not None:
            job.pending_question = None
            job.status = AuditStatus.RUNNING
            _save(job)
        return answer

    return ask


def _run_real_audit(
    audit_id: str, paycodes: list[PayCode], payruns: list[PayRunRow], award_id: str, mode: AuditMode
) -> None:
    def on_verdict(verdict: CodeVerdict) -> None:
        job = get_job(audit_id)
        if job is None:
            return
        job.verdicts.append(verdict)
        job.progress.processed_codes += 1
        job.progress.current_step = f"Classified {verdict.code}"
        _save(job)

    try:
        run_audit(
            paycodes,
            payruns,
            award_id,
            mode=mode,
            on_verdict=on_verdict,
            ask_bookkeeper=_make_ask_bookkeeper(audit_id),
        )
    except Exception as exc:  # a code crashing the pipeline shouldn't hang the job forever
        job = get_job(audit_id)
        if job is not None:
            job.status = AuditStatus.FAILED
            job.error = str(exc)
            _save(job)
        _resume_events.pop(audit_id, None)
        return

    job = get_job(audit_id)
    if job is not None:
        job.status = AuditStatus.COMPLETE
        job.progress.current_step = None
        _save(job)
    _resume_events.pop(audit_id, None)
