"""The seven API endpoints of the contract (spec section 4). Behind FAKE_DATA, every
route returns fixture data so Data and IT can build against real HTTP from hour 2.
"""

from __future__ import annotations

import io
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
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
    LetterResponse,
    SampleBusiness,
    VerdictRequest,
)

from . import jobs
from .config import FAKE_DATA

router = APIRouter()

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "audit_result_sample.json"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"

AWARDS = [
    # Matches the award Data fetched and cited for the café sample business
    # (auditor/knowledge/sources.md, source S4). Update together if that ever changes.
    AwardOption(id="hospitality_ma000009", name="Hospitality Industry (General) Award MA000009"),
]

# All three currently point at the same award: it's the only one in AWARDS above, since
# only the café business has matching award clauses indexed (source S4). Retail and
# construction still run — codes get classified against the ATO rules either way — they
# just won't return an award-specific citation, only ATO ones.
SAMPLE_BUSINESSES = [
    SampleBusiness(
        id="cafe", name="Café", award_id="hospitality_ma000009",
        description="A small café's payroll with a few pay codes deliberately set up incorrectly to find.",
        paycode_count=0,
    ),
    SampleBusiness(
        id="retail", name="Retail store", award_id="hospitality_ma000009",
        description="A retail store's payroll covering weekend trading and commission-vs-bonus cases.",
        paycode_count=0,
    ),
    SampleBusiness(
        id="construction", name="Construction site", award_id="hospitality_ma000009",
        description="A construction crew's payroll covering RDO, site allowance, and portable LSL cases.",
        paycode_count=0,
    ),
]

# The website serves a small "sanity check" subset (~8 codes) of each business's real
# fixture rather than the full ~40-code file Data maintains — fast enough for a reviewer
# to run end-to-end without waiting through (or exhausting a free-tier LLM quota on) a
# full audit, while keeping a couple of genuinely interesting contrast cases (e.g.
# HEIGHTSALLOW vs CONFINEDALLOW) rather than just the easy, obviously-correct codes.
_SAMPLE_FILENAME_MAP = {"paycodes.csv": "sanity_paycodes.csv", "payruns.csv": "sanity_payruns.csv"}


@lru_cache(maxsize=1)
def _sample_businesses_with_counts() -> list[SampleBusiness]:
    """Fills in paycode_count from the actual served file rather than hand-maintaining a
    number that drifts — counted once and cached since these files don't change while
    the server is running."""

    businesses = []
    for business in SAMPLE_BUSINESSES:
        path = SAMPLES_DIR / business.id / _SAMPLE_FILENAME_MAP["paycodes.csv"]
        count = max(0, sum(1 for _ in path.open(encoding="utf-8")) - 1) if path.exists() else 0
        businesses.append(business.model_copy(update={"paycode_count": count}))
    return businesses


def _sample_file_path(business_id: str, filename: str) -> Path:
    if business_id not in {b.id for b in SAMPLE_BUSINESSES}:
        raise HTTPException(status_code=404, detail=f"no sample business {business_id!r}")
    on_disk_name = _SAMPLE_FILENAME_MAP.get(filename, filename)
    path = SAMPLES_DIR / business_id / on_disk_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"sample file {filename!r} not found for {business_id!r}")
    return path


@lru_cache(maxsize=1)
def _fixture_verdicts() -> tuple[CodeVerdict, ...]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return tuple(CodeVerdict.model_validate(v) for v in raw)


def _validation_error(field: str, message: str) -> JSONResponse:
    # Same shape FastAPI's own request validation already returns, so the frontend has
    # one error format to handle regardless of whether we or FastAPI raised it.
    return JSONResponse(status_code=422, content={"detail": [{"loc": ["body", field], "msg": message}]})


@router.get("/awards", response_model=list[AwardOption])
async def list_awards() -> list[AwardOption]:
    return AWARDS


@router.get("/samples", response_model=list[SampleBusiness])
async def list_samples() -> list[SampleBusiness]:
    return _sample_businesses_with_counts()


@router.get("/samples/{business_id}/paycodes.csv")
async def get_sample_paycodes(business_id: str) -> Response:
    path = _sample_file_path(business_id, "paycodes.csv")
    return Response(content=path.read_text(encoding="utf-8"), media_type="text/csv")


@router.get("/samples/{business_id}/payruns.csv")
async def get_sample_payruns(business_id: str) -> Response:
    path = _sample_file_path(business_id, "payruns.csv")
    return Response(content=path.read_text(encoding="utf-8"), media_type="text/csv")


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
        # Each audit must own its verdict objects. Reviewer decisions mutate verdicts,
        # so reusing the cached fixture instances would leak one client's decisions
        # into every audit created afterwards.
        verdicts = [verdict.model_copy(deep=True) for verdict in _fixture_verdicts()]
        jobs.start_fake_audit(job, verdicts)
    else:
        jobs.start_real_audit(job, paycode_rows, payrun_rows, award_id, mode)

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
        return jobs.set_verdict_decision(
            job, code, body.decision, body.note, body.overridden_counts_towards_super
        )
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
async def get_letter(audit_id: str, code: str, download: bool = Query(False)):
    job = jobs.get_job(audit_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no audit found with id {audit_id!r}")
    verdict = next((v for v in job.verdicts if v.code == code), None)
    if verdict is None:
        raise HTTPException(status_code=404, detail=f"no verdict found for code {code!r}")
    letter = draft_letter(verdict)
    if download:
        steps = "\n".join(f"{i}. {step}" for i, step in enumerate(letter.fix_steps, start=1))
        content = (
            f"{letter.subject}\n\n{letter.body}\n\n"
            f"--- For the bookkeeper's own reference (not part of the client letter) ---\n\n"
            f"Fix steps:\n{steps}\n\n"
            f"Catch-up summary:\n{letter.catch_up_summary}"
        )
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="letter_{code}.txt"'},
        )
    return letter
