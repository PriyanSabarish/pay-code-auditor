# React frontend

## Implemented

Responsive retro UI, local SVG art, reduced-motion support, HTTP award list, drag/drop CSV inputs, field validation, multipart submission, TanStack Query polling, partial results and progress, sorting/search/status filters, evidence accordion, reviewer queue, optimistic approve/override with rollback, clarifying questions, server report link, draft letter/copy/download, and failure/empty/reset states.

## Run locally

Requires Node 22.12+ (Node 24 works) and Python 3.12. Open two VS Code terminals.

Terminal 1, from repository root:

```powershell
# Skip the first command if .venv already exists.
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r web/requirements-preview.txt
.\.venv\Scripts\python.exe -m uvicorn web.preview_api:app --host 127.0.0.1 --port 8000 --workers 1
```

Terminal 2:

```powershell
cd web
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to port 8000. Click **Explore a sample audit** to send built-in fictional files. The service returns partial results, pauses for a question, and resumes after an answer. Review a code, save a decision, then export or open its letter.

No API key is needed. The preview always returns synthetic findings: it never audits your uploaded payroll. Use fictional data only. Files are checked in memory and never saved or sent to a model.

## Same-origin build rehearsal

```powershell
cd web
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn web.preview_api:app --host 127.0.0.1 --port 8000 --workers 1
```

Restart the server after the first build so it mounts the assets. Open http://127.0.0.1:8000. Both API and compiled React run on this origin. Refresh `/workspace/review` to test the SPA fallback. Missing API and asset paths return 404. This remains a sample-only service.

## API integration

`web/preview_api.py` provides a provisional Pydantic contract for local interface development.

When the application API is running on port 8000:

```powershell
cd web
npm run generate:types
npm run build
```

`src/api/types.ts` is generated; never hand-edit it. Adapt the field mappings in `src/api/client.ts` and the views to the real generated types. Regeneration does not guarantee the provisional contract matches production.

Confirm these assumptions:

- Multipart: `paycodes`, `payruns`, `award_id`, `mode`.
- Awards: array of `{id,name,preview}`; `preview` enables the sample CTA.
- Job: `audit_id`, five statuses, `progress`, `result`, `pending_question`, `error`, `preview`.
- Result: `business`, `summary`, `verdicts`; verdict statuses `correct|under|over|review`.
- Answer body: `{question_id,answer}`; updated job returned.
- Decision body: `{action,treatment,note}`; updated verdict returned.
- Letter: JSON `{code,text,draft}`; optional `?download=true` returns an attachment. Confirm this download option.
- Money: currently JSON numbers; adapt if production Decimal fields serialize as strings.

The preview contains all seven routes, synthetic transitions, server-generated reports, and the static fallback. React links to the report endpoint and does not calculate payroll findings in the browser.

## Checks

```powershell
cd web
npm test
npm run build
cd ..
.\.venv\Scripts\python.exe -m unittest web.test_preview_api -v
```

Tests cover validation mapping, polling boundaries, citation protocols, file checks, HTTP pause/resume, decisions/export, invalid inputs and SPA fallback. They do not verify payroll rules.
