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
COPY api ./api
COPY auditor ./auditor
COPY data ./data
COPY --from=web-build /app/web/dist ./web/dist

# Render sets $PORT at runtime; uvicorn must bind to it, not a hardcoded port.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
