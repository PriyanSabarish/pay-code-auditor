"""Pydantic models shared across the auditor package and the API.

This file is the single source of truth for the API contract: FastAPI publishes it as
OpenAPI, and `web/` generates TypeScript types from that (never hand-edited). Frozen at
hour 1 of the build — any change here must be announced to Data and IT so ingest.py and
the generated types get updated too.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

ConfidenceLevel = Literal["high", "medium", "low"]
SuperCountsStatus = Literal["yes", "no", "unclear"]
ImpactDirection = Literal["should_count_not_counted", "counts_should_not"]
VerdictStatus = Literal["correct", "should_count", "counts_but_shouldnt", "needs_review"]
ReviewerDecision = Literal["approved", "overridden"]
AuditMode = Literal["keyword", "no_rag", "classifier", "agent", "full"]


class AuditStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETE = "complete"
    FAILED = "failed"


# Input data — what a bookkeeper uploads


class PayCode(BaseModel):
    """One row of paycodes.csv (spec section 9.1)."""

    code: str
    name: str
    description: Optional[str] = None
    counts_for_super: Literal["Y", "N"]
    payroll_category: Optional[str] = None

    @field_validator("counts_for_super", mode="before")
    @classmethod
    def _normalise_yn(cls, v: str) -> str:
        return str(v).strip().upper()


class PayRunRow(BaseModel):
    """One row of payruns.csv: totals for one code in one pay run (spec section 9.2)."""

    pay_date: date
    code: str
    total_amount: float
    employees_paid: int
    overtime_hours: Optional[float] = None


# Classification, retrieval and investigation


class Citation(BaseModel):
    """A passage the classifier or investigator relied on."""

    source: str  # e.g. "ATO qualifying earnings page", "General Retail Industry Award 2020"
    reference: str  # clause/section id, e.g. "cl. 20.2" or "allowances table"
    url: Optional[str] = None
    retrieved_date: Optional[date] = None
    text: Optional[str] = None


class Classification(BaseModel):
    """Structured output of the classifier for one pay code (spec section 6.2)."""

    code: str
    normalised_name: str
    ato_category: str
    counts_towards_super: SuperCountsStatus
    confidence: ConfidenceLevel
    citations: list[Citation] = []
    reasoning: str
    question_for_reviewer: Optional[str] = None


class PaymentHistory(BaseModel):
    """Aggregated pay-run history for one code, used by the impact calculator and the investigator."""

    code: str
    num_pay_runs: int
    avg_amount_per_pay_run: float
    total_amount: float
    avg_employees_paid: float
    total_overtime_hours: float
    pay_runs_per_year: float


class ImpactResult(BaseModel):
    """Exact dollar impact of one misclassified code (spec section 6.6). Always plain Python."""

    code: str
    direction: ImpactDirection
    annual_amount: float
    super_amount: float
    max_penalty_uplift: Optional[float] = None
    note: str


class InvestigationStep(BaseModel):
    """One step of the investigator agent's bounded reasoning loop (spec section 6.3)."""

    step_number: int
    tool: Literal[
        "get_payment_history",
        "search_ato_guidance",
        "search_award",
        "calculate_impact",
        "ask_bookkeeper",
    ]
    input: dict
    output: str
    citation: Optional[Citation] = None


class ClarifyingQuestion(BaseModel):
    """A specific, answerable question the agent asks the bookkeeper (spec section 6.5)."""

    id: str
    code: str
    question: str
    context: Optional[str] = None


class CodeVerdict(BaseModel):
    """The final, reviewable verdict for one pay code."""

    code: str
    name: str
    status: VerdictStatus
    classification: Classification
    investigation: list[InvestigationStep] = []
    verifier_agreed: Optional[bool] = None
    impact: Optional[ImpactResult] = None
    pending_question: Optional[ClarifyingQuestion] = None
    reviewer_decision: Optional[ReviewerDecision] = None
    override_note: Optional[str] = None
    overridden_counts_towards_super: Optional[SuperCountsStatus] = None


# The audit job and what the API returns for it


class AuditProgress(BaseModel):
    total_codes: int
    processed_codes: int
    current_step: Optional[str] = None


class AuditResult(BaseModel):
    """What GET /api/audits/{id} returns — partial while running, full once complete."""

    audit_id: str
    award_id: str
    status: AuditStatus
    progress: AuditProgress
    verdicts: list[CodeVerdict] = []
    pending_question: Optional[ClarifyingQuestion] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AuditJob(BaseModel):
    """Internal job-store record (api/jobs.py). Superset of AuditResult with mode."""

    audit_id: str
    award_id: str
    mode: AuditMode
    status: AuditStatus
    progress: AuditProgress
    verdicts: list[CodeVerdict] = []
    pending_question: Optional[ClarifyingQuestion] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    def to_result(self) -> AuditResult:
        return AuditResult(
            audit_id=self.audit_id,
            award_id=self.award_id,
            status=self.status,
            progress=self.progress,
            verdicts=self.verdicts,
            pending_question=self.pending_question,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


# Request and response bodies for the routes


class AwardOption(BaseModel):
    id: str
    name: str


class AuditCreateResponse(BaseModel):
    audit_id: str


class AnswerRequest(BaseModel):
    question_id: str
    answer: str


class VerdictRequest(BaseModel):
    decision: ReviewerDecision
    note: Optional[str] = None
    # Only meaningful when decision == "overridden": what the reviewer says the correct
    # treatment actually is.
    overridden_counts_towards_super: Optional[SuperCountsStatus] = None


class LetterResponse(BaseModel):
    code: str
    subject: str
    body: str
    draft: bool = True
    # Additive fields (spec 6.7): the bookkeeper's own action checklist and dollar
    # summary, separate from the client-facing letter body above. Both are deterministic
    # — see auditor/remediation.py — never LLM-generated.
    fix_steps: list[str] = []
    catch_up_summary: str = ""
