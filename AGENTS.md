# Agent Definitions
This is the authoritative control surface for all coding agents. Read this first.

**Terminology note (per `CONTEXT.md`):** this is a **Automated Trading system with basket construction** 
— it screens, analyzes, ranks, and proposes a basket with a rationale document. It never places, modifies, or executes
live orders.

## 0. Doc Read Order
Before making changes, read documents in this order:

1. `AGENTS.md` (this file)
2. `CONTEXT.md` — shared vocabulary; use these terms exactly, no synonyms
3. `ARCHITECTURE.md` — system design, data model, API contracts, decision log
4. skills in `skills/` — canonical implementation + hard rules for the
   specific file(s) you're about to touch (see §2.1 for which skill maps
   to which part of the codebase)
5. `CONVENTIONS.md` — Python standards, layering, security, testing

## 1. Repository Map

```
src/web/                      # Next.js 16 (App Router) — theme creation, run, trigger, live run progress, basket + report display
src/app/                      # FastAPI + Celery backend
├── api/                      # FastAPI routes — HTTP only, no business logic
├── agents/                   # One file per pipeline agent:
│   ├── screener.py           # Theme → Candidate Universe
│   ├── analyst.py            # Per-ticker qualitative research (fan-out)
│   ├── modeling.py           # Factor scoring + ranking (deterministic)
│   ├── trader.py             # Basket construction (deterministic)
│   ├── report.py             # Rationale document synthesis
│   └── graph.py              # LangGraph StateGraph assembly (BasketState, edges)
├── integrations/             # External API clients only — one file per vendor:
│   ├── news.py, sec_edgar.py, social_sentiment.py      # (Analyst agent)
│   ├── fundamentals.py, prices.py, factor_panel.py     # (Modeling agent)
│   ├── reference_universe.py, etf_holdings.py          # (Screener agent)
│   ├── openai_client.py, deepseek_client.py
│   └── pinecone_client.py
├── data/                     # All database access
│   ├── models.py             # SQLAlchemy models (ARCHITECTURE.md §2.1)
│   └── queries.py            # Plain functions: get_run(), save_basket(), ...
├── worker.py                 # Celery app + task definitions
└── config.py                 # Settings (env-driven; ARCHITECTURE.md/CONVENTIONS.md §3.1)
infra/                        # docker-compose.yml + observability configs (Postgres, Redis, Langfuse)
skills/                       # ANALYST_SKILL.md, MODELING_SKILL.md...
```

This layout is normative — see `CONVENTIONS.md` §2 for the one-directional
dependency rule (`api/` → `agents/` → `integrations/`/`data/`) and the
one-line test for where new code belongs.

## 2. Primary Agents

*(These are coding-agent roles for building the system. They are distinct
from the system's own pipeline agents — Screener/Analyst/Modeling/
Validator/Trader/Report — which are product code these roles implement,
not roles themselves.)*

### design-architect
- **Role**: Owns system-level design decisions — data model, API
  contracts, pipeline topology, third-party integration choices.
- **Constraints**: Any new decision must be added to `ARCHITECTURE.md` §7
  (decision log) in the same PR, including the rejected alternative and
  why. Must not silently diverge from an existing decision without
  updating the log.
- **Validation**: Design changes must not contradict `CONTEXT.md`
  terminology or the deterministic-ranking boundary
  (`ARCHITECTURE.md` §4, §7).

### pipeline-engineer
- **Role**: Implements and maintains the six pipeline agents in
  `src/app/agents/` and their `integrations/` dependencies.
- **Scope**: `src/app/agents/`, `src/app/integrations/`
- **Constraints**:
  - Working on `screener.py`/`reference_universe.py`/`etf_holdings.py` →
    load `skills/SCREENER_SKILL.md` first.
  - Working on `analyst.py`/`news.py`/`sec_edgar.py`/`social_sentiment.py`
    → load `skills/ANALYST_SKILL.md` first.
  - Working on `modeling.py`/`fundamentals.py`/`prices.py`/
    `factor_panel.py` → load `skills/MODELING_SKILL.md` first.
  - Ranking (`compute_factor_scores`/`combine_scores`/`rank`) and basket
    construction (`trader.py`) must remain deterministic — never let an
    LLM call replace this math (`ARCHITECTURE.md` §7, `MODELING_SKILL.md`
    Hard Rule 1).
  - Every fan-out node (`analyst_node`) must check the relevant cache
    table before calling any vendor API or LLM (`ARCHITECTURE.md` §6).
- **Validation**: Skill file "Hard rules" and "Test fixtures" sections
  for whichever agent was touched must be satisfied — treat these as
  acceptance criteria, not optional guidance.

### api-engineer
- **Role**: Builds FastAPI routes and the Celery task-enqueue boundary.
- **Scope**: `src/app/api/`, `src/app/worker.py`
- **Constraints**:
  - OpenAPI-documented, Pydantic-v2-validated, async endpoints.
  - `POST /themes/{id}/runs` must enqueue and return immediately — never
    execute the LangGraph pipeline synchronously in a request handler
    (`ARCHITECTURE.md` §3, §10).
  - `composite_score` is a required field (not optional/debug-only) on
    `/runs/{run_id}/basket` and `/runs/{run_id}/rankings` responses —
    treat removing or renaming it as a breaking change (`ARCHITECTURE.md`
    §3).
- **Validation**: Above 80% endpoint test coverage. Contract changes
  require a `frontend-engineer` check (see §2.1).

### frontend-engineer
- **Role**: Builds the Next.js UI — theme creation, run triggering, live
  progress, basket/report display.
- **Scope**: `src/web/`
- **Constraints**:
  - Next.js 16 App Router, React Server Components by default, client
    components only for interactivity (run-progress polling/SSE).
  - Must display `composite_score` alongside each basket holding
    directly, not only in an expandable detail view (`ARCHITECTURE.md`
    §3).
  - Must render the "not investment advice" disclaimer on every Report
    view (`ARCHITECTURE.md` §9, `CONTEXT.md`).
- **Validation**: Above 80% component test coverage (Vitest + React
  Testing Library).

### infra-engineer
- **Role**: Owns `infra/docker-compose.yml` and the observability stack.
- **Scope**: `infra/`
- **Constraints**:
  - Langfuse gets its own dedicated Postgres instance, never shared with
    the domain DB (`ARCHITECTURE.md` §6, §10).
  - New services need healthchecks and a corresponding row in
    `ARCHITECTURE.md` §10's failure-mode table.
  - No scheduler/cron — this system is request-triggered only
    (`ARCHITECTURE.md`, Decision: No Scheduler). Do not add Celery Beat
    or a periodic job runner.
- **Validation**: `docker compose config` must validate; new secrets must
  appear in `.env.example` with no real values committed.

### 2.1 Agent Collaboration Rules

| When this changes... | These roles must re-run validation |
|---|---|
| `ARCHITECTURE.md` §4–§7 (pipeline design, agent contracts, decisions) | `design-architect` → `pipeline-engineer` → `api-engineer` |
| A `SKILL.md`'s "Reference implementation" (scoring formulas, factor sources) | `pipeline-engineer` (self) — and the corresponding `ARCHITECTURE.md` §4/§7 section must be updated in the same PR so the two never drift apart |
| `src/app/api/` routes or response schemas | `api-engineer` (self), `frontend-engineer` (contract check) |
| `src/app/data/models.py` (DB schema) | `pipeline-engineer` (self), `api-engineer` (contract check) |
| `src/web/components/basket/*` or `src/web/components/report/*` | `frontend-engineer` (self), `api-engineer` (contract check) |
| `infra/docker-compose.yml` | `infra-engineer` (self) — must update `ARCHITECTURE.md` §10 failure-mode table if a new service is added |
| A theme's factor `weights` config | `pipeline-engineer` — run the shadow-mode comparison from `ARCHITECTURE.md` §8 before promoting new weights |

**Handoff artifacts:**
- `design-architect` adds/updates a decision row in `ARCHITECTURE.md` §7
  before `pipeline-engineer` implements it.
- `pipeline-engineer` produces or updates the relevant `SKILL.md` file
  before or alongside implementation — a coding agent should never
  implement scoring/candidate-generation/research logic that isn't
  reflected in its skill file.
- `api-engineer` keeps the OpenAPI spec in sync with `ARCHITECTURE.md` §3
  before `frontend-engineer` builds against a new/changed endpoint.

## 3. Quality Expectations

### Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.
- If a change would affect whether ranking/basket-construction stays
  deterministic (`ARCHITECTURE.md` §7), flag it explicitly before
  proceeding — this is the one boundary in this codebase that should
  never be crossed silently.

### Simplicity First
Minimum code that solves the problem. Nothing speculative.
- No hardcoding environment variables in all files.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios — but per-ticker failures in
  a fan-out *are* an expected scenario (`ARCHITECTURE.md` §10) and must
  degrade gracefully, not be treated as exceptional.
- If you write 200 lines and it could be 50, rewrite it.

### Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

## 4. Command

```bash
# Run — full stack via Docker Compose
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml up fastapi celery-worker   # backend only
docker compose -f infra/docker-compose.yml --profile tracing up -d    # + Tempo

# Run — local dev, outside compose
uvicorn main:app --reload --port 8000
celery -A app.worker worker --loglevel=info
pnpm --dir frontend dev

# Test & Lint — backend
ruff check .                # lint
mypy --strict app/          # type check
pytest                      # unit + integration tests (fast, default run)
pytest -m golden            # LLM golden-set tests (hits real APIs — not run by default)

# Test & Lint — frontend
pnpm --dir frontend lint
pnpm --dir frontend build   # type check + build
pnpm --dir frontend test    # Vitest + React Testing Library

# Structural checks
pnpm check:structure        # layer boundary tests (api/ → agents/ → integrations//data/)
```

## 5. Workflow: Feature Development

### 5.1 Plan
Agent analyzes the task, references `ARCHITECTURE.md` and `CONVENTIONS.md`.
- Touches Screener/candidate generation → `pipeline-engineer` leads, load
  `skills/SCREENER_SKILL.md`
- Touches Analyst/per-ticker research → `pipeline-engineer` leads, load
  `skills/ANALYST_SKILL.md`
- Touches Modeling/scoring/ranking → `pipeline-engineer` leads, load
  `skills/MODELING_SKILL.md` — flag any change here to `design-architect`
  per the determinism boundary in §3
- Touches Trader/basket construction or Validator → `pipeline-engineer`
  leads, per `ARCHITECTURE.md` §4/§5.4/§5.5
- Touches API contracts or run triggering → `api-engineer` leads
- Touches basket/report UI or run-progress display → `frontend-engineer`
  leads
- Touches Docker/observability → `infra-engineer` leads

### 5.2 Implement
Code with type hints, docstrings, error handling (`CONVENTIONS.md` §1).
- `pipeline-engineer`: follow the loaded skill's Hard Rules exactly —
  cache-before-fetch, per-ticker try/except with error stubs (never
  raise past a node boundary), deterministic math with no LLM override.
- `api-engineer`: Pydantic v2 models, async endpoints, enqueue-not-execute
  for run triggering, structured logging correlated by `run_id`.
- `frontend-engineer`: TypeScript strict mode, React hooks for SSE/
  polling, shadcn/ui components, `composite_score` always visible.
- `infra-engineer`: healthchecked services, secrets via `.env`/secrets
  manager only — never hardcoded (`CONVENTIONS.md` §3.1).

### 5.3 Test
- Unit tests for everything in `agents/modeling.py`'s pure functions and
  `agents/trader.py`'s constraint logic — no mocking needed beyond
  fixture DataFrames.
- Mocked-LLM-boundary tests for `analyst_node`/`screener_node`/etc. — mock
  the `integrations/` client, not the node function itself
  (`CONVENTIONS.md` §5).
- Golden-set tests (`pytest -m golden`) run separately, not on every
  commit, since they cost money.
- `frontend-engineer`: component tests + mock SSE/poll-response tests.

### 5.4 Review
Self-review against `CONVENTIONS.md`, and against the loaded skill's Hard
Rules if `app/agents/` or `app/integrations/` were touched.

### 5.5 Validate
CI pipeline must pass before completion:
- `ruff check .` / `mypy --strict app/` — backend lint + types
- `pytest` — backend unit + integration tests
- `pnpm check:structure` — layer boundary tests
- `pnpm --dir frontend build` / `pnpm --dir frontend test` — frontend
  type check, build, and component tests
- Golden-set tests run on a schedule/pre-release, not required for every
  merge
