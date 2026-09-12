# Pay Code Auditor

The frontend follows revision 2 of the team plan: React, TypeScript, Vite, Tailwind, Mantine, and TanStack Query. The retro visual identity is retained.

Frontend setup, handoff notes and deployment instructions: [web/README.md](web/README.md).

Priyan owns production `api/` and the AI `auditor/` package. The data teammate owns ingest, calculations and reports. Varun owns `web/`.

The production API was not yet available in this checkout. `web/preview_api.py` is an isolated synthetic HTTP service for frontend development. Its exact models are provisional and generated to TypeScript through OpenAPI. It does not classify real pay codes, retrieve legal guidance or calculate actual financial impact. Replace its contract with Priyan's OpenAPI before claiming integration.

All changes are left uncommitted for manual review and commit in VS Code.
