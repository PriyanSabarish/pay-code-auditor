# React frontend

## Implemented

Responsive retro UI, local SVG art, reduced-motion support, HTTP award list, drag/drop CSV inputs, field validation, multipart submission, TanStack Query polling (including while the tab is backgrounded), results table with reasoning-trail evidence panel, sorting/search/status filters, optimistic approve/override with rollback, clarifying questions with real pause/resume, server report link, draft letter/copy/download, and failure/empty/reset states.

## Wired to the real API

`src/api/client.ts` and `src/api/types.ts` are generated from and target **`api/main.py`** (the real FastAPI app at the repo root, `auditor/schemas.py` is its source of truth) — not `web/preview_api.py`. `preview_api.py` was an earlier provisional mock used before the real contract existed; it's superseded now and safe to ignore (or delete) since the frontend no longer talks to it. If you still want to poke at it standalone, its own README instructions (`uvicorn web.preview_api:app`) still work, but building the frontend against it will no longer match — the shapes have diverged (see the real contract in `auditor/schemas.py`: `status` is `correct/should_count/counts_but_shouldnt/needs_review`, impact is a nested `ImpactResult` with `annual_amount`/`super_amount`, verdicts sit directly on `AuditResult.verdicts`, decisions are flat fields on `CodeVerdict`, etc.).

## Run locally

Requires Node 22.12+ (Node 24 works) and Python 3.12. Open two terminals from the repository root.

Terminal 1 — the real API:

```powershell
# Skip the first two lines if .venv already exists.
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

`FAKE_DATA=1` by default (see `api/config.py`), so no Groq key is needed to exercise the full contract — every audit runs against the fixture in `data/fixtures/audit_result_sample.json` (8 codes, all 4 statuses, a full 5-step trail, one paused clarifying question).

Terminal 2 — the frontend:

```powershell
cd web
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to port 8000. Upload any CSV pair (or the sample files) and pick an award — the audit progresses, pauses on a clarifying question, resumes after you answer, then lets you approve/override, export the report, and view a draft letter.

## Same-origin build rehearsal

```powershell
cd web
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Restart the server after the first build so it mounts `web/dist`. Open http://127.0.0.1:8000. Both API and compiled React run on this origin. Refresh a client-side route to test the SPA fallback (any unmatched path serves `index.html`).

## Regenerating types after a schema change

`auditor/schemas.py` is frozen and announced when it changes — regenerate types whenever it does:

```powershell
# with the API running locally
cd web
npm run generate:types
npm run build
```

`src/api/types.ts` is generated; never hand-edit it.

## Checks

```powershell
cd web
npm test
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest -q
```

`npm test` covers the HTTP error-parsing boundary, polling behavior, citation URL safety, and file validation. `pytest` covers the full backend contract, including the pause/resume flow, against the real API.
