"""The seven API endpoints of the contract (spec section 4). Behind FAKE_DATA, every
route returns fixture data so Data and IT can build against real HTTP from hour 2.
"""

from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from auditor.ingest import IngestError, load_paycodes, load_payruns
from auditor.remediation import draft_letter
from auditor.report import generate_report_csv
from auditor.schemas import (
    AnswerRequest,
    AuditCreateResponse,
    AuditMode,
    AuditResult,
    AwardOption,
    CodeVerdict,
    FieldError,
    LetterResponse,
    ValidationErrorResponse,
    VerdictRequest,
)

from . import jobs
from .config import FAKE_DATA

router = APIRouter()

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "audit_result_sample.json"

AWARDS = [
    AwardOption(id="general_retail_2020", name="General Retail Industry Award 2020"),
    AwardOption(id="restaurant_2020", name="Restaurant Industry Award 2020"),
]


@lru_cache(maxsize=1)
def _fixture_verdicts() -> tuple[CodeVerdict, ...]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return tuple(CodeVerdict.model_validate(v) for v in raw)


def _validation_error(field: str, message: str) -> JSONResponse:
    body = ValidationErrorResponse(errors=[FieldError(field=field, message=message)])
    return JSONResponse(status_code=422, content=body.model_dump())


@router.get("/awards", response_model=list[AwardOption])
async def list_awards() -> list[AwardOption]:
    return AWARDS


@router.post("/audits", status_code=202, response_model=AuditCreateResponse)
async def create_audit(
    paycodes: UploadFile = File(...),
    payruns: UploadFile = File(...),
    award_id: str = Form(...),
    mode: AuditMode = Form("full"),
):
    try:
        paycodes_text = (await paycodes.read()).decode("utf-8-sig")
        paycode_rows = load_paycodes(io.StringIO(paycodes_text))
    except IngestError as exc:
        return _validation_error("paycodes", str(exc))
    except Exception as exc:  # malformed file entirely (not valid CSV at all)
        return _validation_error("paycodes", f"could not read file: {exc}")

    try:
        payruns_text = (await payruns.read()).decode("utf-8-sig")
        payrun_rows = load_payruns(io.StringIO(payruns_text))
    except IngestError as exc:
        return _validation_error("payruns", str(exc))
    except Exception as exc:
        return _validation_error("payruns", f"could not read file: {exc}")

    if not paycode_rows:
        return _validation_error("paycodes", "file has no rows")
    if not payrun_rows:
        return _validation_error("payruns", "file has no rows")

    if award_id not in {a.id for a in AWARDS}:
        return _validation_error("award_id", f"unknown award_id {award_id!r}")

    job = jobs.create_job(award_id=award_id, mode=mode)

    if FAKE_DATA:
        jobs.start_fake_audit(job, list(_fixture_verdicts()))
    else:
        raise HTTPException(status_code=501, detail="The real audit pipeline is not wired up yet.")

    return AuditCreateResponse(audit_id=job.audit_id)


@router.get("/audits/{audit_id}", response_model=AuditResult)
async def get_audit(audit_id: str) -> AuditResult:
    job = jobs.get_job(audit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no audit found with id {audit_id!r}")
    return job.to_result()


@router.post("/audits/{audit_id}/answer", response_model=AuditResult)
async def answer_audit_question(audit_id: str, body: AnswerRequest) -> AuditResult:
    job = jobs.get_job(audit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no audit found with id {audit_id!r}")
    try:
        job = jobs.answer_question(job, body.question_id, body.answer)
    except jobs.JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job.to_result()


@router.post("/audits/{audit_id}/verdicts/{code}", response_model=CodeVerdict)
async def set_verdict(audit_id: str, code: str, body: VerdictRequest) -> CodeVerdict:
    job = jobs.get_job(audit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no audit found with id {audit_id!r}")
    try:
        return jobs.set_verdict_decision(job, code, body.decision, body.note)
    except jobs.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/audits/{audit_id}/report.csv")
async def get_report_csv(audit_id: str) -> Response:
    job = jobs.get_job(audit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no audit found with id {audit_id!r}")
    csv_text = generate_report_csv(job.verdicts)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_{audit_id}_report.csv"'},
    )


@router.get("/audits/{audit_id}/letter/{code}", response_model=LetterResponse)
async def get_letter(audit_id: str, code: str) -> LetterResponse:
    job = jobs.get_job(audit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no audit found with id {audit_id!r}")
    verdict = next((v for v in job.verdicts if v.code == code), None)
    if verdict is None:
        raise HTTPException(status_code=404, detail=f"no verdict found for code {code!r}")
    return draft_letter(verdict)
