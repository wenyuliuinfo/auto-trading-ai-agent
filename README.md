# Auto Trading AI Agent

Theme-driven basket research system: given an investment theme, the
pipeline screens a Candidate Universe, analyzes each Candidate, ranks it
with deterministic factor math, constructs an 8-10 name Basket, and
writes a grounded Rationale Report. It never places or executes orders.

## Stack

- `src/web` - Next.js 16 App Router UI (theme creation, run progress,
  Basket + Report views)
- `src/app` - FastAPI + Celery + LangGraph backend
- `infra/docker-compose.yml` - Postgres, Redis, Pinecone local, Langfuse

## Quickstart

```bash
# 1. Infra (Postgres, Redis, Pinecone, Langfuse)
docker compose --env-file .env -f infra/docker-compose.yml up -d

# 2. Backend API + Celery worker
cd src/app
../.venv/bin/uvicorn main:app --reload --port 8000
../.venv/bin/celery -A app.worker worker --loglevel=info

# 3. Frontend
cd src/web
pnpm dev
```

Set `STUB_AGENTS=true` in `.env` (or the shell) to run the whole
pipeline deterministically without network access or LLM spend. With
real API keys and `STUB_AGENTS=false`, the integrations call FMP,
Finnhub, GDELT, SEC EDGAR, yfinance, and DeepSeek.

## Validation

```bash
cd src/app && ../.venv/bin/ruff check . && ../.venv/bin/mypy --strict app/
cd src/app && ../.venv/bin/python -m pytest
cd src/web && ./node_modules/.bin/eslint . && ./node_modules/.bin/vitest run && ./node_modules/.bin/next build --webpack
```

See `AGENTS.md`, `CONTEXT.md`, and `ARCHITECTURE.md` for the full
vocabulary, contracts, and decision log.
