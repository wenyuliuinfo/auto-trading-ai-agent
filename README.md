# Auto Trading AI Agent

LangGraph based multi-agent theme-driven basket research: given an investment theme, the pipeline
screens a Candidate Universe, analyzes each Candidate, ranks it with
deterministic factor math, constructs a 5-10 name Basket, and writes a
grounded Rationale Report. It never places, modifies, or executes live
orders.

## Overview

End users create or select a Theme through the Next.js UI, trigger a Run,
and review the resulting Basket and Rationale Report. A Run is a single,
on-demand execution of the full pipeline from Screener through Report:
the Screener bounds the universe, the Analyst fan-out builds a
source-cited evidence base per ticker, deterministic Modeling code
produces the Ranked List, the Trader constructs the Basket under hard
diversification and liquidity constraints, and the Report synthesizes a
grounded rationale document.

Runs are request-triggered only, never scheduled. Outputs are research
artifacts for human review, not investment advice; every generated Report
carries a mandatory "not investment advice, for research purposes only"
disclaimer.

### How it works

1. The user creates or selects a Theme (name, definition, and config such
   as sub-exposures, screens, and weighting scheme)
2. The user triggers a Run via `POST /themes/{id}/runs`; FastAPI enqueues
   a Celery task and returns a `run_id` immediately, never executing the
   pipeline synchronously in the request handler
3. The Screener converts the Theme into a bounded Candidate Universe of
   50-100 tickers using thematic ETF holdings, GICS sub-industries, and
   semantic search
4. The Analyst runs once per candidate in parallel, checking the same-day
   cache before any vendor API or LLM call, and produces a grounded
   Analyst Report per ticker
5. Modeling builds the Factor Panel and computes deterministic Composite
   Scores, Factor Contributions, and the Ranked List; the LLM only
   converts qualitative signals and writes `caveats`, never the ranking
   itself
6. The optional Validator runs an adversarial bull/bear check on the top
   ~12 ranked names
7. The Trader constructs the 5-10 name Basket with deterministic code
   under liquidity, market cap, sub-exposure diversification, and sizing
   constraints, recording near-misses and explicit `swap_reason` entries
8. The Report agent synthesizes the full Run state into a grounded
   Rationale Report, and code appends the disclaimer unconditionally
9. The UI polls run progress (or subscribes via SSE) and displays the
   Basket with `composite_score` next to each holding, plus the final
   Report

### Key design decisions

| Decision | Rationale |
|---|---|
| Deterministic code for ranking and basket construction | Reproducibility and auditability: the same inputs must always produce the same rank and Basket ([ARCHITECTURE.md](ARCHITECTURE.md) §7) |
| Redis + Celery for the task queue | No durable multi-consumer streaming need at current scale; simpler to operate than Kafka |
| Postgres for LangGraph checkpointing | One persistence layer for both domain data and run state; avoids a second store with no clear benefit |
| Request-triggered runs only, no scheduler | Explicit product requirement: no cron, no nightly refresh, no Celery Beat |
| Free-tier data vendors with load-bearing caching | Cost-effective at current scale; caching is required to survive rate limits |
| Langfuse + Prometheus/Grafana | Self-hosted LLM/agent tracing plus infra metrics; complementary, not overlapping |
| Bounded retry loop (max 2) on basket completeness | Gives the Screener a chance to widen the pool without infinite loops |
| Validator scoped to the top ~12 names | Cost control: full-universe debate does not scale to 100+ candidates |
| `STUB_AGENTS=true` deterministic stub mode | Offline and CI-friendly development without live API keys; stub output can never mutate scoring or basket math |

### Live Agent Overview

The following is the Live Auto Trading AI Agent screen capture.
<p align="center">
  <img src="docs/images/auto-trading-agent-homepage.png" alt="Auto Trading Homepage" width="900">
</p>

<p align="center">
  <img src="docs/images/auto-trading-agent-basket.png" alt="Auto Trading Basket page" width="900">
</p>

<p align="center">
  <img src="docs/images/auto-trading-agent-report.png" alt="Auto Trading Report page" width="900">
</p>

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 |
| Backend | FastAPI, Pydantic v2, Python 3.12 |
| Orchestration | LangGraph StateGraph, Celery + Redis |
| Relational DB | PostgreSQL (SQLAlchemy asyncpg + PostgresSaver checkpoints) |
| Vector DB | Pinecone |
| LLM | DeepSeek |
| Data sources | FMP, Finnhub, SEC EDGAR, yfinance, Stooq, GDELT, SerpApi |
| Observability | Langfuse, Prometheus, Grafana |
| Task runner | pnpm |

## Project Structure

```
.
├── src/
│   ├── app/                    # FastAPI + Celery backend
│   │   ├── api/                # HTTP-only FastAPI routes
│   │   ├── agents/             # Screener, Analyst, Modeling, Trader, Report, graph
│   │   ├── evaluation/         # Groundedness/golden-set checks (advisory only)
│   │   ├── integrations/       # One file per external provider
│   │   ├── data/               # SQLAlchemy models + queries
│   │   ├── worker.py           # Celery app + task definitions
│   │   └── config.py           # Pydantic settings (env-driven)
│   ├── web/                    # Next.js 16 App Router UI
│   └── scripts/
│       └── shadow_compare.py   # Reruns Modeling pure functions on cached data
├── config/                     # Factor weights, ETF holdings, theme schemas
├── prompts/                    # Per-agent system prompts
├── skills/                     # Canonical implementation skills per agent
├── infra/                      # docker-compose + observability configs
├── AGENTS.md                   # Agent definitions and collaboration rules
├── ARCHITECTURE.md             # System design and decision log
├── CONTEXT.md                  # Shared vocabulary / domain glossary
└── CONVENTIONS.md              # Python standards, layering, testing
```

## Prerequisites

- **Node.js** >= 20 and **pnpm** >= 9
- **Python** 3.12 with a virtual environment at `src/app/.venv`
- **Docker** + Docker Compose for Postgres, Redis, Pinecone local, and Langfuse
- **DeepSeek API key** and data vendor keys (FMP, Finnhub, SerpApi), optional when `STUB_AGENTS=true`

## Setup

1. Clone and install dependencies
```bash
git clone <repo-url>
cd auto-trading-ai-agent
pnpm install
cd src/app && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

2. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys and database URL.
```

3. Start services (Postgres, Redis, Pinecone, Langfuse, Nextjs, Celery Worker, FastAPI)
```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
```


`pnpm dev` from the repo root starts both the Next.js app and the FastAPI
API concurrently.

## Scripts

| Command | Description |
|---|---|
| `pnpm dev` | Start frontend + backend concurrently |
| `pnpm dev:web` | Next.js dev server only |
| `pnpm dev:api` | FastAPI dev server only (`:8000`) |
| `pnpm build` | Production build (frontend) |
| `pnpm lint` | Frontend lint (ESLint) |
| `pnpm lint:api` | Backend lint (ruff) |
| `pnpm test:api` | Backend unit + integration tests (pytest) |
| `pnpm test:eval` | Golden-set eval tests |
| `pnpm --dir src/web test` | Frontend component tests (Vitest + React Testing Library) |
| `pnpm check:structure` | Layer boundary / structural tests |
| `pnpm typecheck:api` | Backend strict type check (mypy) |

Golden-set tests that hit real APIs are also runnable separately with
`pytest -m golden` and are not part of the default test run.

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/themes` | Yes | Create a Theme (`name`, `definition`, `sub_exposures`, optional `screens`/`weighting_scheme`/`validator_enabled`) |
| `GET` | `/themes/{theme_id}` | Session-scoped | Fetch a Theme's definition/config |
| `POST` | `/themes/{theme_id}/runs` | Yes | Trigger a Run; enqueues to Celery and returns `{run_id, status: "queued"}` immediately |
| `GET` | `/runs/{run_id}` | Session-scoped | Run status/progress |
| `GET` | `/runs/{run_id}/events` | Session-scoped | SSE stream of run progress events |
| `GET` | `/runs/{run_id}/basket` | Session-scoped | Final Basket with `composite_score` per holding |
| `GET` | `/runs/{run_id}/report` | Session-scoped | Final Rationale Report (markdown) |
| `GET` | `/runs/{run_id}/rankings` | Session-scoped | Full Ranked List with Factor Contributions and `composite_score` |

`composite_score` is a required contract field on both the Basket and
Rankings responses; the UI displays it directly next to each holding.

## Testing

The test suite covers the deterministic pipeline math, the mocked-LLM
agent boundaries, and structural invariants:

- Unit tests for `compute_factor_scores`, `combine_scores`, and `rank`,
  including edge cases and property tests
- Trader constraint tests verifying liquidity floors, market cap floors,
  sector diversification, and sizing are never violated
- Mocked-LLM-boundary tests for `screener_node`/`analyst_node`/etc. that
  mock the integration client, not the node function itself
- Structural tests enforcing the one-directional dependency rule
  (`api/` -> `agents/` -> `integrations/` + `data/`)
- Frontend component tests (Vitest + React Testing Library) covering
  run-progress views, the always-visible `composite_score`, and the
  mandatory disclaimer on Report views

Run them with:

```bash
pnpm lint
pnpm lint:api
pnpm test:api
pnpm --dir src/web test
pnpm check:structure
pnpm build
```

## Evaluation

Evaluation is advisory and separate from Run completion:

- **Groundedness checks** verify Analyst `sources` trace back to real
  tool-call results and that Report numbers match upstream outputs
  (`src/app/evaluation/groundedness.py`)
- **Golden-set checks** validate candidate coverage against known
  theme-mapped ETF holdings and flag implausible baskets
- **Shadow-mode comparison** reruns only the deterministic Modeling and
  basket-construction functions against cached data when factor weights
  change (`src/scripts/shadow_compare.py`), with no LLM or vendor calls
- **Forward performance tracking** records each Basket's forward return
  against its theme reference ETF as a monitoring/feedback-loop signal
- **Human review gate** is required before any Basket/Report is treated
  as client-facing output, especially when a groundedness check flags an
  unmatched number

## Documentation

- **[AGENTS.md](AGENTS.md)** - Coding-agent control surface: roles,
  collaboration rules, and validation expectations
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Full system design: data
  model, API contracts, LangGraph orchestration, integrations, failure
  modes, decision log
- **[CONTEXT.md](CONTEXT.md)** - Shared vocabulary and domain glossary
- **[CONVENTIONS.md](CONVENTIONS.md)** - Python standards, layering,
  security, and testing conventions
- **[skills/](skills/)** - Canonical implementation and hard rules for
  the Screener, Analyst, Modeling, Trader, and Report agents

## Environment Variables

See [.env.example](.env.example) for the full template. Key variables:

| Variable | Purpose |
|---|---|
| `POSTGRES_DATABASE_URL` | Domain PostgreSQL connection string (asyncpg) |
| `STUB_AGENTS` | `true` runs the pipeline deterministically with stubs; `false` uses live integrations |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | DeepSeek LLM provider |
| `PINECONE_API_KEY` / `PINECONE_HOST_URL` / `PINECONE_INDEX_NAME` | Vector store connection |
| `FMP_API_KEY` / `FINNHUB_API_KEY` / `SERP_API_KEY` | Free-tier data vendor keys |
| `LANGFUSE_DB_PASSWORD` / `LANGFUSE_NEXTAUTH_SECRET` / `LANGFUSE_SALT` | Self-hosted Langfuse configuration |
