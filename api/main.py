"""FastAPI app: mounts /api and serves the built React bundle as static files at the
root (spec section 3). One deployed service — no CORS, no second deploy target.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CORS_ORIGINS
from .routes import router

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="Pay Code Auditor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

if WEB_DIST.exists():
    assets_dir = WEB_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Catch-all so a hard refresh on a client-side route (e.g. /results) still works."""

        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")

else:

    @app.get("/")
    async def no_frontend_built() -> JSONResponse:
        return JSONResponse(
            {
                "detail": (
                    "web/dist is not built yet. Run `npm run build` in web/, "
                    "or use the API directly under /api (see /docs)."
                )
            }
        )
