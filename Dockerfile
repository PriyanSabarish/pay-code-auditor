# One deployed service (see api/main.py): FastAPI serves both /api and the built React
# bundle from the same origin, so a single Render Web Service is enough — no separate
# Vercel deploy, no CORS wiring, no split-origin API base URL to configure.

FROM node:20-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Bake fastembed's model into the image at build time instead of downloading it at
# runtime. Render's filesystem is ephemeral, so without this, every cold start (spin-
# down wake, an OOM restart, any redeploy) re-fetches ~130MB from Hugging Face before
# the first classification can even begin retrieval — observed directly in production
# logs ("Fetching 5 files...") adding a real, measured ~12s on top of everything else.
# fastembed defaults its cache to tempfile.gettempdir() (/tmp in this image) — pinned to
# a normal image path instead, since some container runtimes mount /tmp as a fresh
# tmpfs at start, which would silently discard whatever got baked in here at build time.
# The model name must match auditor/retrieval.py's EMBEDDING_MODEL_NAME.
ENV FASTEMBED_CACHE_PATH=/app/.fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY api ./api
COPY auditor ./auditor
COPY data ./data
COPY --from=web-build /app/web/dist ./web/dist

# Render sets $PORT at runtime; uvicorn must bind to it, not a hardcoded port.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
