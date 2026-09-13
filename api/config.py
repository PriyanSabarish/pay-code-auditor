"""Runtime settings for the API layer, env-driven so FAKE_DATA survives into the real build."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# On by default: the fake-data server is the hour-2 deliverable everyone else builds
# against. Flip to "0" once the real classifier/investigator/verifier are wired in.
FAKE_DATA = os.getenv("FAKE_DATA", "1") == "1"

# Dev-only CORS origins for `npm run dev` (Vite) talking to a locally running API.
# Not needed when FastAPI serves the built bundle itself (the default, single-service
# deploy) — only required if the frontend is deployed separately (e.g. Vercel) from the
# API (e.g. Render), in which case set CORS_ORIGINS to the deployed frontend's origin(s).
DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
EXTRA_CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
CORS_ORIGINS = DEV_CORS_ORIGINS + EXTRA_CORS_ORIGINS

# How long the fake-data job simulation pauses between codes, so polling has something
# to show rather than jumping straight to "complete".
FAKE_STEP_DELAY_SECONDS = float(os.getenv("FAKE_STEP_DELAY_SECONDS", "0.4"))
