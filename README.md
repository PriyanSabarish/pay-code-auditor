# Pay Code Auditor

Payday Super started 1 July 2026. Super is now paid every payday, on a new measure —
qualifying earnings. Every pay code has to be mapped by hand, and payroll software
calculates from whatever settings you entered without checking whether they're right. One
wrong code repeats in every pay run, for every employee, at up to a 60% penalty uplift.

Primary customer: bookkeepers and BAS agents who run payroll for many small-business clients at once.

URL: https://pay-code-auditor.onrender.com

## The problem, in plain terms

Since 1 July 2026, employers must pay super every payday instead of every quarter, and the
amount super is calculated on changed from ordinary time earnings to a new measure called
qualifying earnings. Every payroll system has a list of pay codes — Sunday penalty, tool
allowance, commission — and each one has a setting that says whether it counts towards
super. Reviewing that list by hand, one code at a time, is slow and easy to get wrong, and
a wrong setting repeats every single pay run until someone catches it.

## What it does

1. **Ingest.** Parse and validate the two CSV files a bookkeeper uploads: the pay code list and a summary of recent pay runs.
2. **Classify.** A fast model classifies every code, grounded in the actual ATO guidance. Codes it's unsure about, or that disagree with a simple keyword check, escalate to a stronger model.
3. **Investigate.** For anything genuinely unclear, a bounded, tool-using agent looks at the code's real payment history, searches the ATO guidance and the award, and can pause to ask the bookkeeper a specific question when it needs one.
4. **Verify.** A second model call checks any non-obvious conclusion before it's shown to a person.
5. **Calculate impact.** The dollar shortfall or overpayment, and the penalty exposure, is computed entirely in plain Python. No model ever touches the arithmetic.
6. **Review.** A bookkeeper approves or overrides every flag, exports a report, and can generate a draft client letter for anything approved.

Every code comes back correct, underpaid, overpaid, or needs review — with the reasoning
trail, the ATO passage or award clause behind it, and the exact dollar impact.

## Why the AI and the arithmetic are kept apart

The model is used for the one thing it's genuinely good at here: interpreting messy,
inconsistent pay code names and matching them to a legal category. Every dollar figure,
every comparison against a client's current setting, and every penalty calculation is
deterministic Python. This isn't a style choice — a compliance number has to be exact and
repeatable, and a model is the wrong tool for that job even when it's right most of the time.

## How we built it

Python core, FastAPI, React. A two-model cascade classifies every code, grounded in hybrid
retrieval (BM25 + local embeddings) over the ATO guidance, SGR 2009/2 and the client's
award. Suspicious codes go to an agent with five read-only tools, capped at six logged
steps. A second model verifies each conclusion. All money is plain Python, unit tested —
the model never does arithmetic. The LLM layer is provider-agnostic (`LLM_PROVIDER=groq`
or `gemini`), so the whole cascade can run on either without touching call sites.

## Challenges we ran into

Real code names are messy and often ambiguous, which pushed us to investigate how each
code is actually paid rather than what it's called. Tuning when to say "unclear" instead of
guessing took real work.

## Accomplishments that we're proud of

**92.0%** (46/50) on 50 held-out test codes, against **36.0%** (18/50) for a keyword
baseline. The verifier caught [N] wrong conclusions. [N] of 12 planted problems found.
[$X] and [N] minutes per audit, measured.

## What we learned

Retrieval beat model size. Letting the system decline to answer made it better, not worse.
Separating judgement from arithmetic removed a whole class of doubt.

## What's next for Pay Code Auditor

The ongoing per-pay-run check — that's the subscription. Then any payroll export format,
multiple awards per audit, and the edge cases we excluded.

## Architecture

One deployed service. FastAPI serves the API under `/api` and the built React bundle as
static files at the root — no CORS to manage in production, nothing to deploy twice.

```
pay-code-auditor/
  api/
    main.py       # FastAPI app, mounts /api and serves web/dist
    routes.py     # audit endpoints + bundled sample-data endpoints
    jobs.py       # in-memory audit job store (capped, oldest-first eviction), plus fake-data mode
    config.py     # env-driven settings, including FAKE_DATA
  auditor/
    schemas.py    # frozen Pydantic models, the API contract's source of truth
    ingest.py      impact.py      report.py
    classify.py    llm.py         prompts.py     # llm.py: Groq or Gemini, selected by LLM_PROVIDER
    retrieval.py   verifier.py    memory.py      remediation.py
    agent/
      tools.py         # the investigator's five read-only tools
      investigator.py  # the bounded, tool-using reasoning loop (6-step cap)
    knowledge/
      chunks.jsonl          # 67 ATO table rows, grounding every citation
      sources.md             fetch_sources.py     build_chunks.py
      build_cafe_sample.py   build_retail_sample.py   build_construction_sample.py
  data/
    csv_contract.md        # the exact schema every paycodes.csv/payruns.csv follows
    eval/
      dev_set.csv           # 30 labelled codes, allowed inside prompts
      test_set.csv           # 50 labelled codes, held out, never seen by a prompt
    samples/
      cafe/  retail/  construction/   # synthetic businesses with planted errors + a small sanity_check.csv answer key each
      dummy/                          # a tiny smoke-test fixture
    fixtures/
      audit_result_sample.json  chunks_sample.jsonl   # frontend fake-data mode fixtures
  eval/
    run_eval.py      # keyword / no-retrieval / full-pipeline comparison harness
  web/               # React app, Vite, TypeScript — see web/README.md
  tests/             # pytest suite covering every module above
  Dockerfile  render.yaml   # single-service production deploy
```

`web/src/api/types.ts` is generated from the live OpenAPI schema, never hand-edited.

## The API contract

| Endpoint | Behaviour |
|---|---|
| `GET /api/awards` | List of selectable awards |
| `GET /api/samples` | Bundled sample businesses (café, retail, construction) for one-click demo data |
| `GET /api/samples/{id}/paycodes.csv` / `payruns.csv` | Download or fetch a sample's CSVs |
| `POST /api/audits` | Multipart upload of `paycodes.csv` + `payruns.csv` + `award_id` + `mode`. `422` with readable field errors, or `202` with an `audit_id` |
| `GET /api/audits/{id}` | Polling endpoint: `status`, `progress`, partial/full `AuditResult`, `pending_question` |
| `POST /api/audits/{id}/answer` | Answers a clarifying question; resumes the paused investigation |
| `POST /api/audits/{id}/verdicts/{code}` | Approve or override one flag |
| `GET /api/audits/{id}/report.csv` | Server-generated CSV export |
| `GET /api/audits/{id}/letter/{code}` | Draft client letter for one approved flag |

`auditor/schemas.py` is the frozen source of truth for every shape above. A change there
needs to be announced to the whole team, since the frontend generates its TypeScript types
directly from the live OpenAPI schema.

## Model choices

This runs on two interchangeable providers, chosen with `LLM_PROVIDER` in `.env` — `groq` or `gemini`.

Groq is the default. Fast tier is `openai/gpt-oss-20b`, used for bulk classification and
name clean-up. Strong tier is `openai/gpt-oss-120b`, used for escalated codes, the
investigator agent, the verifier, and remediation. These were chosen from what's actually
available on the self-serve Groq catalog right now, not from a preference ranking —
`llama-3.1-8b-instant` and `llama-3.3-70b-versatile`, the models most guides still quote,
moved to enterprise-only pricing on Groq in late August 2026 and are no longer reachable on
a standard account.

Gemini is the fallback, and it exists for a real reason, not a nice-to-have. Groq's free
tier enforces a daily token quota tight enough to run out mid-session during real testing,
with no reset time shown anywhere in the account dashboard. Gemini gives the same cascade a
second, independent quota to fall back to. `gemini-3.1-flash-lite` (or `gemini-3.5-flash-lite`)
is recommended for both tiers here, checked against a live rate-limit page rather than
assumed, since the flagship flash model's free quota measured only twenty requests a day on
the key this was tested against, while the lite model's measured five hundred. Every call
site in the codebase talks to one interface in `auditor/llm.py`, so the provider switch is
contained to one file and nowhere else needs to know which one is active.

Override any of the four model names (`GROQ_FAST_MODEL`, `GROQ_STRONG_MODEL`,
`GEMINI_FAST_MODEL`, `GEMINI_STRONG_MODEL`) in `.env` if either provider's lineup changes again.

## Data

**`paycodes.csv`** columns: `code, name, description (optional), counts_for_super (Y/N), payroll_category (optional)`.

**`payruns.csv`** columns: `pay_date, code, total_amount, employees_paid, overtime_hours (optional)`,
aggregated per code per pay run. No employee names or identifiers are accepted.

Pay frequency and the average amount paid per run are never supplied by the uploader —
they're worked out from the actual pay dates in the file, since a wrong assumption there
would silently misstate every dollar figure downstream.

Two labelled evaluation sets. `data/eval/dev_set.csv` holds 30 codes and may be used inside
prompts as worked examples. `data/eval/test_set.csv` holds 50 held-out codes — the
evaluation harness refuses to run against it unless you pass a flag explicitly, so nobody
can accidentally tune anything against the number that's meant to be the final, honest one.

Three synthetic sample businesses — a café, a retail store, and a construction
subcontractor — each with dozens of realistically messy pay codes and several pay runs,
used for the live demo and for one-click sample data via `/api/samples`. Each has a handful
of deliberately planted configuration errors and at least one payment pattern that should
trip the tool's anomaly detection, plus one deliberately correct code shaped like an
anomaly, included to test the honest false-alarm rate. The full answer key for each
business's complete fixture is kept out of the repository on purpose (gitignored), since
the whole point is for the tool to find the errors in front of an audience — a small,
committed `sanity_check.csv` per business documents the handful of codes used for the
one-click demo, for internal reference.

The ATO knowledge base, `auditor/knowledge/chunks.jsonl`, is 67 rows transcribed from the
live ATO qualifying earnings page, one per table row, across all 14 tables. Every
classification citation points back to a specific row using an id scheme of source, table,
and row number, so a verdict can always be traced to the exact rule it relied on rather
than a vague paraphrase. Full provenance — source URL, retrieval date, and a hash of the
captured page — is recorded in `auditor/knowledge/raw/manifest.json`.

## Evaluation

`eval/run_eval.py` compares three methods against a labelled set: keyword rules alone with
no model call at all; the classifier with no retrieved context, a plain LLM call; and the
real award-aware pipeline with retrieval. This is the comparison table the pitch leans on
to answer the obvious question of why this is more than a wrapper around a chatbot.

Defaults to the 30-code dev set, since that one is safe to look at and tune against.
Running it against the 50-code held-out test set requires an explicit `--allow-test-set`
flag, on purpose, so the one number meant to represent honest accuracy never gets quietly
optimised for.

```bash
python -m eval.run_eval                                          # dev set, all methods
python -m eval.run_eval --dataset data/eval/test_set.csv --allow-test-set   # the one official number
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then add your GROQ_API_KEY, or switch LLM_PROVIDER to gemini and add GOOGLE_API_KEY
```

`FAKE_DATA=1` by default, so the API and frontend can be explored fully with no API key at
all — every audit runs against a fixture with all four verdict statuses and a full
investigation trail. Set `FAKE_DATA=0` once you want the real pipeline.

```bash
pytest -q
```

The retrieval and investigator tests download a small embedding model from Hugging Face on
first run. If that host is blocked by your network, those specific tests will fail with a
clear message rather than a mysterious one — everything else in the suite is unaffected.

```bash
uvicorn api.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for the live OpenAPI page, or `http://localhost:8000/`
once `web/dist` exists (`npm run build` inside `web/`).

Frontend setup, the full feature list, and same-origin build instructions are documented in
[`web/README.md`](web/README.md). Short version: Node 22.12 or newer, `npm ci` then `npm run dev`
inside `web/` — Vite proxies `/api` to port 8000 for local development.

## Deployment

One Docker image, built in two stages. The React app builds first and its output is copied
into the same image FastAPI runs from, so one Render web service serves both the API and
the frontend from a single origin — no split deploy, no CORS to configure. The embedding
model retrieval depends on is baked into the image at build time rather than downloaded on
first request, since Render's filesystem doesn't persist between cold starts, and
re-downloading it on every wake was a measured, real delay in production logs.

`render.yaml` describes the whole service as a Blueprint, so a new deploy is one click
rather than manual dashboard setup, with API keys prompted for once and stored in Render,
never in the repository.

## Current status

Every module named in the architecture section is built and covered by tests: ingestion
and validation, the two-tier classifier with retrieval, the investigator agent, the
verifier, per-bookkeeper memory of clarifying-question answers, the impact calculator, and
a dual-provider setup that keeps the whole pipeline working even when one provider's free
tier runs dry. The frontend is wired to the real API contract. The service is packaged for
a real, single-click deploy, not just a local demo.

## Limitations (state openly)

- Flags issues for professional review; this is not legal or tax advice.
- The rule summaries used to build the labelled datasets are a starting reference — the
  live ATO page and the relevant award are the actual authority, and are cited directly in
  every classification.
- Does not handle the maximum super contribution base, salary sacrifice arrangements,
  award-specific super above the legal minimum, or complex contractor arrangements.
- Payment-pattern findings are review flags for a human, never automatic conclusions.
- The prototype supports one award at a time.
- Accuracy figures come from a test set labelled using the ATO's published guidance, not an
  independent third-party review, and that should be said plainly wherever the figures are shown.

## Sources

- ATO, *What payments are qualifying earnings*:
  https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/what-payments-are-qualifying-earnings
- Full source list with retrieval dates in `auditor/knowledge/sources.md`
