# Pay Code Auditor

An AI agent that audits a business's payroll pay codes against Australia's Payday Super
"qualifying earnings" (QE) rules — the way a senior payroll auditor would: read the pay
codes, check them against the ATO guidance and the business's award, investigate how each
code is actually paid, calculate the exact dollar impact of any error in plain Python, and
draft the fix and a client letter. A person approves every change.

Primary customer: bookkeepers and BAS agents who run payroll for many small-business clients.

## Architecture

One deployed service. FastAPI serves the API under `/api` and the built React bundle as
static files at the root — no CORS in production, no second deploy target.

```
pay-code-auditor/
  api/
    main.py     # FastAPI app; mounts /api and serves web/dist
    routes.py   # the seven endpoints below
    jobs.py     # in-memory audit job store + fake-data simulation
  auditor/      # core package — unchanged in substance from the original spec
    schemas.py  ingest.py  impact.py  report.py
    llm.py      # Groq client + cascade tier selection
    knowledge/  agent/  (retrieval.py, prompts.py, classify.py, verifier.py, memory.py,
                 remediation.py land through the build)
  web/          # React app (Vite + TypeScript + Tailwind)
  data/  eval/  tests/
```

`web/src/api/types.ts` is generated, never hand-edited — see below.

## Current backend status

- [x] `auditor/schemas.py` frozen — `PayCode`, `PayRunRow`, `Citation`, `Classification`, `InvestigationStep`, `ClarifyingQuestion`, `CodeVerdict`, `AuditResult`, `AuditJob`, plus the API request/response bodies
- [x] All seven API routes live behind `FAKE_DATA=1` (default), backed by a fixture with all four verdict statuses, a full five-step investigation trail, and a paused clarifying question
- [x] `api/jobs.py` — in-memory job store with real pause/resume semantics (`awaiting_input` → `answer` → resume), so the frontend's polling code is exercised for real before the actual agent exists
- [x] FastAPI serves `web/dist` at the root with a catch-all for client-side routes (graceful fallback message until `web/` is built)
- [x] `auditor/llm.py` — Groq client wrapper for the two-tier cascade
- [x] Unit + API test suite: 19 passing (`pytest -q`)
- [ ] `classify.py` (cascade + citations) — next, hours 2–7
- [ ] `retrieval.py` (award-aware hybrid search) — hours 7–10
- [ ] `agent/tools.py` + `agent/investigator.py` (bounded 6-step loop) — hours 10–13
- [ ] `verifier.py` — hours 13–14
- [ ] `memory.py` + real pause/resume wiring — hours 21–23
- [ ] `remediation.py` (LLM-written prose; currently template-only) — hours 23–25
- [ ] Flip `FAKE_DATA=0` once the real pipeline lands

## The API contract

| Endpoint | Behaviour |
|---|---|
| `GET /api/awards` | List of selectable awards (static for the prototype) |
| `POST /api/audits` | Multipart upload of `paycodes.csv` + `payruns.csv` + `award_id` + `mode`. `422` with readable field errors, or `202` with an `audit_id` |
| `GET /api/audits/{id}` | Polling endpoint: `status`, `progress`, partial/full `AuditResult`, `pending_question` |
| `POST /api/audits/{id}/answer` | Answers a clarifying question; resumes the paused investigation |
| `POST /api/audits/{id}/verdicts/{code}` | Approve or override one flag |
| `GET /api/audits/{id}/report.csv` | Server-generated CSV export |
| `GET /api/audits/{id}/letter/{code}` | Draft client letter for one approved flag |

`GET /openapi.json` is live once the API is running — that's what
`npx openapi-typescript http://localhost:8000/openapi.json -o src/api/types.ts`, run inside
`web/`, generates the frontend types. `auditor/schemas.py` is the source of truth; schema
changes require regenerating the TypeScript definitions.

## Model choices

This build uses **Groq only** (not the Claude cascade in the original spec), via `auditor/llm.py`:

| Tier | Model (default) | Used for |
|---|---|---|
| `fast` | `openai/gpt-oss-20b` | Bulk classification, name clean-up |
| `strong` | `openai/gpt-oss-120b` | Escalated codes, investigator agent, verifier, remediation |

Picked from what's actually enabled on this Groq account — `llama-3.1-8b-instant` /
`llama-3.3-70b-versatile` returned 404s. Override either with `GROQ_FAST_MODEL` /
`GROQ_STRONG_MODEL` in `.env`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then add your GROQ_API_KEY
```

Run the tests:

```bash
pytest -q
```

Run the API (fake-data mode by default — no key needed to explore the contract):

```bash
uvicorn api.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for the live OpenAPI page, or `http://localhost:8000/`
once `web/dist` exists.

Frontend setup and development checks are documented in [`web/README.md`](web/README.md).

## Data format

**`paycodes.csv`**: `code, name, description?, counts_for_super (Y/N), payroll_category?`

**`payruns.csv`**: `pay_date, code, total_amount, employees_paid, overtime_hours?` —
aggregated per code per pay run, no employee names or IDs.

## Limitations (state openly)

- Flags issues for professional review; this is not legal or tax advice.
- The rules reference in the spec is a starting point — the ATO page and the award are the authority.
- Does not handle the maximum contribution base, salary sacrifice, award-specific super above the legal minimum, or complex contractor arrangements.
- Payment-pattern findings are review flags, not conclusions.
- The prototype supports one award at a time.
