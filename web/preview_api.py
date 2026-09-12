"""ISOLATED UI PREVIEW ONLY. This is not a production API or payroll engine.

Run from repository root: python -m uvicorn web.preview_api:app --port 8000
All verdicts/figures are synthetic. No uploads are saved or sent to a model.
The document specifies routes but not exact models. These provisional models
exist to generate frontend types and must be replaced with the application contract.
"""
import asyncio
import csv
import io
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Pay Code Auditor — provisional UI preview contract", version="0.1.0-preview")
VerdictStatus = Literal["correct", "under", "over", "review"]


class Award(BaseModel):
    id: str
    name: str
    preview: bool = True


class Citation(BaseModel):
    clause: str
    text: str
    url: str | None = None


class Step(BaseModel):
    tool: str
    summary: str


class Decision(BaseModel):
    action: Literal["approve", "override"]
    treatment: Literal["yes", "no", "unclear"]
    note: str = Field(default="", max_length=2000)


class Verdict(BaseModel):
    code: str
    name: str
    status: VerdictStatus
    counts_towards_super: Literal["yes", "no", "unclear"]
    confidence: Literal["high", "medium", "low"]
    annual_impact: float
    reasoning: str
    citations: list[Citation]
    steps: list[Step]
    verifier: str
    decision: Decision | None = None


class Summary(BaseModel):
    shortfall: float
    overpayment: float


class AuditResult(BaseModel):
    business: str
    verdicts: list[Verdict]
    summary: Summary


class Progress(BaseModel):
    completed: int
    total: int
    message: str


class Question(BaseModel):
    id: str
    code: str
    text: str
    context: str


class AuditJob(BaseModel):
    audit_id: str
    status: Literal["queued", "running", "awaiting_input", "complete", "failed"]
    progress: Progress
    result: AuditResult | None = None
    pending_question: Question | None = None
    error: str | None = None
    preview: bool = True


class AuditCreated(BaseModel):
    audit_id: str


class Answer(BaseModel):
    question_id: str
    answer: str = Field(min_length=1, max_length=2000)


class Letter(BaseModel):
    code: str
    text: str
    draft: bool = True


jobs: dict[str, AuditJob] = {}


def get_job(audit_id: str) -> AuditJob:
    """Return a stored preview job or a readable not-found response."""
    if audit_id not in jobs:
        raise HTTPException(404, "This audit is unavailable. The preview server may have restarted. Start a new review.")
    return jobs[audit_id]


def sample_result() -> AuditResult:
    """Build the fictional findings used to demonstrate the interface."""
    examples = [("ORD_HRS", "Ordinary hours", "correct", "yes", 0), ("BASE_PAY", "Base pay", "correct", "yes", 0), ("SHIFT_X", "Shift payment X", "under", "yes", 720), ("PAYMENT_Y", "Payment Y", "over", "no", 240), ("SITE_ALLOW", "Site allowance", "review", "unclear", 0), ("OTHER_01", "Other payment", "review", "unclear", 0), ("STANDARD", "Standard earnings", "correct", "yes", 0), ("REGULAR", "Regular earnings", "correct", "yes", 0)]
    trail = [Step(tool="get_payment_history", summary="Loaded fictional payment history for this example."), Step(tool="search_ato_guidance", summary="Preview placeholder: real source retrieval belongs to the connected backend."), Step(tool="search_award", summary="Preview placeholder: the production award and clause are not selected."), Step(tool="calculate_impact", summary="Displayed an illustrative amount; no payroll calculation was performed."), Step(tool="verifier", summary="Preview placeholder: no model verification was performed.")]
    verdicts = [Verdict(code=c, name=n, status=s, counts_towards_super=t, confidence="low" if s == "review" else "medium", annual_impact=a, reasoning="This fictional case demonstrates the review interface. It does not establish the treatment of any real payment.", citations=[Citation(clause="Illustrative evidence placeholder", text="The connected audit will return an actual source passage and its clause identifier here. This is not an ATO quotation.")], steps=trail, verifier="Not verified — interface sample") for c,n,s,t,a in examples]
    return AuditResult(business="Sunday Corner Cafe", verdicts=verdicts, summary=Summary(shortfall=720, overpayment=240))


@app.get("/api/awards", response_model=list[Award])
def awards():
    """List award contexts available to the local preview."""
    return [Award(id="demo-award", name="Sample award context · preview only")]


async def advance(audit_id: str):
    """Populate a preview job gradually, then pause it for reviewer input."""
    job = jobs[audit_id]
    fixture = sample_result()
    job.status = "running"
    job.result = fixture.model_copy(deep=True)
    job.result.verdicts = []
    job.result.summary = Summary(shortfall=0, overpayment=0)
    for index, verdict in enumerate(fixture.verdicts):
        await asyncio.sleep(0.45)
        job.result.verdicts.append(verdict)
        job.result.summary = Summary(shortfall=sum(v.annual_impact for v in job.result.verdicts if v.status == "under"), overpayment=sum(v.annual_impact for v in job.result.verdicts if v.status == "over"))
        job.progress = Progress(completed=index+1, total=8, message="Reviewing sample pay codes")
    job.status = "awaiting_input"
    job.progress.message = "One question needs your context"
    job.pending_question = Question(id="q-site", code="SITE_ALLOW", text="What does this allowance cover?", context="Describe the purpose of this payment. In this preview your answer demonstrates pause and resume; it does not trigger legal classification.")


@app.post("/api/audits", status_code=202, response_model=AuditCreated)
async def create_audit(paycodes: UploadFile = File(...), payruns: UploadFile = File(...), award_id: str = Form(...), mode: Literal["keyword", "no_rag", "classifier", "agent", "full"] = Form("full")):
    """Validate uploaded CSV files and start a bounded synthetic audit job."""
    errors = []
    if award_id != "demo-award":
        errors.append({"loc":["body","award_id"],"msg":"Select the sample award context."})
    for field, upload in [("paycodes", paycodes), ("payruns", payruns)]:
        content = await upload.read(5 * 1024 * 1024 + 1)
        try:
            if not upload.filename or not upload.filename.lower().endswith(".csv") or not 0 < len(content) <= 5 * 1024 * 1024:
                raise ValueError("Choose a non-empty CSV smaller than 5 MB.")
            text = content.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("Export this file as CSV UTF-8.")
            rows = list(csv.reader(io.StringIO(text), strict=True))
            if len(rows) < 2 or len(rows[0]) < 2:
                raise ValueError("Include headings and at least one data row in two or more columns.")
            headings = [name.strip() for name in rows[0]]
            if not all(headings) or len(set(headings)) != len(headings):
                raise ValueError("Use unique, non-empty column headings.")
            if any(len(row) != len(headings) for row in rows[1:] if row):
                raise ValueError("Every row must have the same number of columns as the headings.")
        except (ValueError, UnicodeDecodeError, csv.Error) as exc:
            errors.append({"loc":["body",field],"msg":str(exc) if not isinstance(exc, UnicodeDecodeError) else "Export this file as CSV UTF-8."})
    if errors:
        raise HTTPException(422, errors)
    # Keep the in-memory preview store bounded.
    if len(jobs) >= 100:
        terminal = next((key for key,value in jobs.items() if value.status in ("complete","failed")), None)
        if terminal:
            jobs.pop(terminal)
        else:
            raise HTTPException(429, "Preview capacity reached. Restart the preview server.")
    audit_id = uuid4().hex
    jobs[audit_id] = AuditJob(audit_id=audit_id, status="queued", progress=Progress(completed=0,total=8,message="Preparing sample records"))
    asyncio.create_task(advance(audit_id))
    return AuditCreated(audit_id=audit_id)


@app.get("/api/audits/{audit_id}", response_model=AuditJob)
def poll(audit_id: str):
    """Return the latest state of a preview audit."""
    return get_job(audit_id)


@app.post("/api/audits/{audit_id}/answer", response_model=AuditJob)
def answer(audit_id: str, body: Answer):
    """Record reviewer context and complete the paused preview audit."""
    job = get_job(audit_id)
    if job.status != "awaiting_input" or not job.pending_question or body.question_id != job.pending_question.id:
        raise HTTPException(409, "That question is no longer pending. Refresh the audit.")
    if not body.answer.strip():
        raise HTTPException(422, "Enter an answer before continuing.")
    verdict = next(v for v in job.result.verdicts if v.code == job.pending_question.code)
    verdict.steps.append(Step(tool="ask_bookkeeper", summary="Reviewer context received: " + body.answer.strip()))
    verdict.reasoning = "Your context was recorded. This sample remains needs review because no real classification was run."
    job.pending_question = None
    job.status = "complete"
    job.progress.message = "Sample review ready"
    return job


@app.post("/api/audits/{audit_id}/verdicts/{code}", response_model=Verdict)
def decide(audit_id: str, code: str, body: Decision):
    """Save a reviewer approval or documented override for one finding."""
    job = get_job(audit_id)
    if job.status != "complete":
        raise HTTPException(409, "Complete the investigation before recording decisions.")
    verdict = next((v for v in job.result.verdicts if v.code == code), None)
    if verdict is None:
        raise HTTPException(404, "Pay code not found.")
    if body.action == "override" and not body.note.strip():
        raise HTTPException(422, "Add a reason for the override.")
    if body.action == "approve" and body.treatment != verdict.counts_towards_super:
        raise HTTPException(422, "An approval must retain the recommended treatment.")
    verdict.decision = body
    return verdict


def csv_safe(value):
    """Prevent spreadsheet software from interpreting exported values as formulas."""
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@app.get("/api/audits/{audit_id}/report.csv")
def report(audit_id: str):
    """Export completed preview findings as a CSV attachment."""
    job = get_job(audit_id)
    if job.status != "complete":
        raise HTTPException(409, "The audit is not complete.")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sample_only", "code", "status", "illustrative_annual_impact", "decision", "reviewed_treatment", "reviewer_note"])
    for v in job.result.verdicts:
        writer.writerow(["TRUE",v.code,v.status,v.annual_impact,v.decision.action if v.decision else "unreviewed",v.decision.treatment if v.decision else "",csv_safe(v.decision.note) if v.decision else ""])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":'attachment; filename="sample-audit.csv"'})


@app.get("/api/audits/{audit_id}/letter/{code}", response_model=Letter)
def letter(audit_id: str, code: str, download: bool = False):
    """Create a review-ready draft letter for a decided finding."""
    job = get_job(audit_id)
    verdict = next((v for v in (job.result.verdicts if job.result else []) if v.code == code), None)
    if not verdict or not verdict.decision:
        raise HTTPException(409, "Record a reviewer decision before opening the draft letter.")
    text = f"DRAFT FOR PROFESSIONAL REVIEW — FICTIONAL SAMPLE\n\nDear client,\n\nWe have recorded a reviewer decision for {code}. The selected treatment is '{verdict.decision.treatment}'.\n\nPlease verify the applicable guidance and calculations before making any payroll changes. This letter is an interface example and contains no legal conclusion.\n\nReviewer note: {verdict.decision.note or 'No additional note.'}\n\nYour bookkeeping team"
    if download:
        return Response(text, media_type="text/plain", headers={"Content-Disposition":'attachment; filename="draft-letter.txt"'})
    return Letter(code=code,text=text)


DIST = Path(__file__).resolve().parent / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Serve compiled frontend files while preserving API 404 responses."""
    if path == "api" or path.startswith("api/") or path.startswith("assets/"):
        raise HTTPException(404, "Not found")
    candidate = (DIST / path).resolve()
    if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    if DIST.exists():
        return FileResponse(DIST / "index.html")
    raise HTTPException(503, "Build the React frontend with npm run build, or use the Vite dev server.")
