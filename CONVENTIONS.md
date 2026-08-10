# CONVENTIONS.md
## Coding Standards for the Auto Trading AI Agent

This file governs how code is written, organized, and reviewed in this
repository. It assumes familiarity with `ARCHITECTURE.md` (system design)
and `CONTEXT.md` (domain vocabulary) — terms used below match those files
exactly; do not introduce synonyms for defined concepts (e.g. always
`Candidate`, never `stock_pick` or `symbol_entry`).

---

## 1. Python Coding Standards

### 1.1 Tooling (non-negotiable, enforced in CI)
- **Formatter:** `black`, default line length (88).
- **Linter:** `ruff` (replaces flake8/isort/pyupgrade) — `ruff check .` must
  pass with zero warnings before merge.
- **Type checking:** `mypy --strict` on all modules under `app/`. No
  `# type: ignore` without an inline comment explaining why.
- **Python version:** 3.11+ (needed for modern typing syntax and
  `asyncio` improvements used throughout).

### 1.2 Type hints are mandatory, everywhere
Every function signature — including private/internal helpers — must be
fully typed. No bare `dict`/`list`; use `dict[str, Any]` at minimum, and
prefer a Pydantic model or `TypedDict` over a raw `dict` for anything that
crosses a function boundary more than once.

```python
# Bad
def compute_factor_scores(df, factor_cols):
    ...

# Required
def compute_factor_scores(
    df: pd.DataFrame, factor_cols: list[str]
) -> pd.DataFrame:
    ...
```

### 1.3 Pydantic models for every agent input/output
Per `ARCHITECTURE.md` §5 (Prompt and Answer Contract), every Agent's
structured output is enforced via schema, not "ask nicely for JSON." Each
schema is a Pydantic model, colocated with the agent that owns it:

```python
class AnalystReport(BaseModel):
    ticker: str
    thematic_relevance_score: float = Field(ge=1, le=5)
    thematic_relevance_rationale: str
    revenue_pct_theme_estimate: float | None
    catalysts: list[str]
    risks: list[str]
    sentiment_label: Literal["bullish", "neutral", "bearish"]
    sentiment_evidence: list[str]
    sources: list[str]
    news: list[dict[str, str]]   # [{headline, url, source, published_at, summary}]
```

Rules:
- Every field that can legitimately be unavailable (per the Analyst
  contract's "output null with a reason") is `X | None`, never a
  sentinel string like `"N/A"`.
- Validate LLM output against the model immediately after the API call
  returns — fail loudly (raise, caught by the node's error handling) rather
  than passing a malformed dict further down the pipeline.
- Never mutate a Pydantic model in place after validation; construct a new
  instance if a value needs to change, so the object stays trustworthy as
  an audit artifact.

### 1.4 Naming conventions
- `snake_case` for functions/variables, `PascalCase` for classes/Pydantic
  models, `SCREAMING_SNAKE_CASE` for module-level constants.
- Agent node functions are always named `{agent_name}_node` (matches
  `ARCHITECTURE.md` §4: `screener_node`, `analyst_node`, `modeling_node`,
  `validator_node`, `trader_node`, `report_node`) — do not rename these
  even for brevity; the mapping between glossary term and function name
  should be immediately obvious.
- Deterministic scoring functions keep the exact names used in
  `ARCHITECTURE.md`: `compute_factor_scores`, `combine_scores`, `rank`.
  If you refactor their internals, keep the public name and signature
  stable — other code and this document both reference them by name.

### 1.5 Docstrings
Every public function gets a docstring stating what it does, and — for
anything touching money, ranking, or agent output — **why**, not just
what, since these are the functions most likely to be revisited months
later during an audit. Google-style docstrings, one blank line before
`Args`/`Returns`:

```python
def combine_scores(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Combine per-factor z-scores into a single composite score.

    Weighted linear combination — see ARCHITECTURE.md §4 for the
    mathematical definition. Weights must sum to 1.0; this is not
    validated here and should be enforced at config-load time.

    Args:
        df: DataFrame with one `{factor}_z` column per factor.
        weights: factor name -> weight mapping.

    Returns:
        Series of composite scores, indexed the same as `df`.
    """
```

### 1.6 Async conventions
- FastAPI route handlers and any I/O-bound code (LLM calls, data vendor
  calls) are `async def`. Never call a blocking HTTP client inside an
  `async def` — use an async client (`httpx.AsyncClient`, async SDK
  methods) throughout.
- Celery tasks that invoke the LangGraph pipeline are synchronous entry
  points (Celery doesn't natively await coroutines) — bridge with
  `asyncio.run()` at the task boundary, not scattered throughout the
  codebase.

---

## 2. Backend Layering

Five layers. Four follow one rule — **each layer only talks to the one
directly below it**, API calls Agents, Agents call Integrations and
Data, nothing calls backward up the chain. `evaluation/` is the
exception: it's a sibling to `agents/`, not part of the request-serving
chain at all — see 2.1 for why.

```
src/app/
├── api/                    # FastAPI routes. HTTP only — no business logic.
│   ├── themes.py
│   └── runs.py
├── agents/                 # One folder per Agent. Everything that Agent
│   ├── screener.py         # needs — LLM call, prompt, and (for Modeling/
│   ├── analyst.py          # Trader) the deterministic logic — lives
│   ├── modeling.py         # together in its own file.
│   ├── trader.py
│   ├── report.py
│   └── graph.py            # Wires the agents above into the LangGraph
│                           # StateGraph (BasketState, nodes, edges).
├── evaluation/             # Groundedness/golden-set checks. Reads agents'
│   └── groundedness.py     # already-persisted output; never called from
│                           # api/, never blocks a Run's completion.
│                           # check_analyst_groundedness, check_report_groundedness
│                           # (ARCHITECTURE.md §8.B).
├── integrations/           # All external calls. One file per provider.
│   ├── deepseek_client.py
│   ├── langfuse_client.py  # READ path — queries traces for evaluation/.
│   │                       # Distinct from the write-side Langfuse callback
│   │                       # attached to LangGraph invocations (§6) —
│   │                       # different API surface, different purpose.
│   ├── fmp.py / finnhub.py / sec_edgar.py / yfinance_client.py / gdelt.py
│   └── pinecone_client.py
├── data/                   # All database access. Models + queries together.
│   ├── models.py           # SQLAlchemy models (ARCHITECTURE.md §2.1)
│   └── queries.py          # Plain functions: get_run(), save_basket(), ...
├── worker.py               # Celery app + task definitions
└── config.py               # Settings (env-driven, see §3.1)

src/scripts/                # One-off/operational entry points, outside src/app/:
└── shadow_compare.py       # Reruns agents/modeling.py's pure functions
                            # against cached data — ARCHITECTURE.md §8.C.
```

### 2.1 The rule, in practice

- **`api/`** — validates the request, calls one function in `agents/`
  (usually `graph.py`) or `data/`, returns the response. No scoring math,
  no LLM calls, no raw SQL here.
- **`agents/`** — where almost all the logic lives. Each file owns one
  Agent end-to-end: its prompt, its LLM call, its Pydantic schema, and —
  for Modeling and Trader specifically — the deterministic scoring/
  constraint functions (`compute_factor_scores`, `combine_scores`, `rank`,
  diversification checks). Keep the deterministic functions as clearly
  separate, plainly-named functions within the file (not interleaved with
  the LLM call) so they stay easy to unit-test on their own — that
  separation is what matters, not which folder they sit in.
- **`evaluation/` — reads, never writes to the pipeline, and is never
  called from `api/`.** `check_analyst_groundedness` and
  `check_report_groundedness` (`ARCHITECTURE.md` §8.B) read a completed
  Run's already-persisted state via `data/` and its Langfuse trace via
  `integrations/langfuse_client.py`, and produce flags for the human
  review gate — they don't gate a Run's completion or feed back into
  `agents/`. Invoked from two places only: a `pytest -m golden` fixture
  test (CI), and a separate operational monitoring job (a Celery task or
  scheduled script) that runs the same checkers against recent real
  runs. If you find yourself calling anything in `evaluation/` from
  `agents/` or `api/`, stop — that's the wrong direction; evaluation
  observes the pipeline, it doesn't participate in it.
- **`integrations/`** — the only place that calls an external API (LLM
  or data vendor). `agents/analyst.py` imports from here; it never calls
  `requests`/`httpx` directly. Note `langfuse_client.py` specifically has
  two unrelated call sites for two different purposes — the write-side
  tracing callback (attached once, per LangGraph invocation, logging
  spans as a Run executes) and this read-side query client (called only
  from `evaluation/`, after a Run is already complete) are separate code
  paths in the same file, not the same client reused both ways.
- **`data/`** — the only place that touches Postgres. Everything else
  calls a plain function like `save_analyst_report(...)`, never opens a
  DB session itself.
- **`scripts/`** — operational entry points that aren't part of the
  request-serving app at all (not deployed as a service, run manually or
  via a one-off job). `shadow_compare.py` lives here rather than in
  `evaluation/` because it isn't a pass/fail check — it's a comparison
  tool an operator runs deliberately before changing
  `config/factor_weights.yaml`.
- **One-line test:** if you're unsure where new code goes, ask "does it
  call an external API?" → `integrations/`. "Does it touch the
  database?" → `data/`. "Does it check/flag already-produced output
  without participating in producing it?" → `evaluation/`. Otherwise →
  the relevant file in `agents/`.

This intentionally merges what would otherwise be separate
`services/`/`domain/`/`repositories/` layers — for a system this size,
one well-organized `agents/` folder per Agent is easier to navigate than
tracing logic across five directories to understand what one Agent does.
`evaluation/` stays separate from `agents/` specifically because it has
a different caller (tests/ops jobs, not the graph) and a different
contract (advisory flags, not pipeline state) — folding it into
`agents/` would blur the "does this participate in producing a Run's
output" question that everything else in this layout is organized around.

---

## 3. Security

### 3.1 Secrets
- All secrets loaded via `pydantic-settings` from environment variables
  only — never hardcoded, never committed, never logged. `config.py`
  defines a `Settings` model; nothing else reads `os.environ` directly.
- Local dev uses `.env` (gitignored); production uses the secrets manager
  named in `ARCHITECTURE.md` §9 (Vault/cloud secrets store) — the app code
  is identical either way since both surface as env vars.
- Never interpolate a secret into a log line, exception message, or
  Langfuse trace attribute. Redact before logging: write a `redact()`
  helper and use it on any dict that might contain vendor API responses
  with echoed auth headers.

### 3.2 Input validation
- Every FastAPI route validates its request body via a Pydantic schema —
  no raw `dict` request bodies.
- Theme `config` (factor weights, screening thresholds) is validated at
  write time (`POST /themes`), not just at Modeling-agent read time —
  reject a theme whose weights don't sum to 1.0 before it's ever persisted.

### 3.3 Prompt injection
Per `ARCHITECTURE.md` §9: all Data Vendor content (news text, filing
text, social posts) fed to an Agent is **untrusted data**, never trusted
instruction. Concretely:
- When constructing a tool-result message for the LLM, wrap external text
  in a clearly delimited data block (e.g. inside an explicit
  `<tool_result>` tag or a dedicated message role) — never concatenate raw
  fetched text directly into a system/instruction-bearing message.
- Do not let any Agent's output (e.g. Analyst's `catalysts`/`risks` text)
  be re-interpreted as instructions by a downstream Agent — Report/
  Validator prompts should treat upstream Agent output as data to
  summarize, stated explicitly in their system prompts (already the case
  per `ARCHITECTURE.md` §5).

### 3.4 Least privilege
- The Postgres role used by `fastapi`/`celery-worker` should have
  `SELECT`/`INSERT`/`UPDATE` on domain tables only — no `DROP`/`ALTER`,
  no access to Langfuse's database (separate instance already enforces
  this at the infra level per the compose file).
- LLM/Data Vendor API keys are scoped to the minimum permissions each
  provider offers (e.g. read-only where available).

### 3.5 Dependency management
- Pin exact versions in `requirements.txt`/`pyproject.toml` (no bare
  `>=`), and run `pip-audit` (or equivalent) in CI to catch known CVEs
  before merge.

### 3.6 Rate limiting
- API-layer rate limiting (per `ARCHITECTURE.md` §9) on
  `POST /themes/{id}/runs` specifically — this is the one endpoint that
  can exhaust shared free-tier Data Vendor quotas if triggered
  excessively; enforce per-user/org limits here, separate from any
  vendor-side limits handled in `integrations/`.

### 3.7 Compliance
- Every code path that renders a `Report` to the End User must include
  the "not investment advice" disclaimer — enforced by a template/wrapper
  function in `agents/report/`, not left to the prompt alone to remember
  every time.

---

## 4. Agent & LangGraph Conventions

- **One node, one job.** A node function should map to exactly one Agent
  responsibility from `CONTEXT.md`. If a node starts doing two things
  (e.g. Modeling node also writing prose beyond `caveats`), split it.
- **Each Agent's prompt is a plain string constant near the top of its
  file** (e.g. `SCREENER_PROMPT` in `agents/screener.py`) — never
  constructed dynamically via string concatenation of business logic;
  f-string interpolation of *data* (ticker, theme name) into a fixed
  template is fine, generating structurally different prompts at runtime
  is not.
- **Model/temperature choice is explicit and centralized** per Agent, not
  scattered as magic numbers:
  ```python
  # agents/analyst.py
  ANALYST_MODEL = "deepseek-chat"
  ANALYST_TEMPERATURE = 0.1

  # agents/report.py
  REPORT_MODEL = "deepseek-v4-pro"
  REPORT_TEMPERATURE = 0.5

  # agents/screener.py
  SCREENER_MODEL = "deepseek-v4-pro"
  SCREENER_TEMPERATURE = 0.5
  ```
- **Deterministic code stays in its own named functions, never inlined
  into the LLM call.** In `agents/modeling.py`, `compute_factor_scores`/
  `combine_scores`/`rank` are separate functions the node calls into —
  the node function itself should read as "call scoring functions, then
  make one narrow LLM call for `caveats`," not a single blob mixing both.
- **Every node wraps its risky call in try/except** and returns a
  typed error/status field into shared state rather than raising past the
  node boundary (see `ARCHITECTURE.md` §10, Failure Modes) — one ticker's
  failure must not crash the whole `Run`.
- **Cache check precedes any LLM/vendor call.** The Analyst node must call
  `data/queries.py`'s `get_recent_analyst_report()` for a fresh (< 1 day)
  report before invoking the LLM — this isn't an optimization to add
  later, it's required given free-tier Data Vendor rate limits
  (`ARCHITECTURE.md` §6).

---

## 5. Testing

Mirrors the two-track split in `ARCHITECTURE.md` §8:

- **Deterministic functions (`compute_factor_scores`, `combine_scores`,
  `rank`, Trader's constraint checks) — standard pytest unit tests, no
  mocking needed beyond fixture DataFrames.** Property-based tests (via
  `hypothesis`) encouraged for `rank`/`combine_scores` given the
  invariants stated in that section (valid permutation, monotonicity).
- **LLM-driven node logic — mock the LLM client in `integrations/`**,
  never the node function itself (i.e. mock `deepseek_client.complete()`,
  not `analyst_node()` directly) so the actual node logic — cache check,
  schema validation, error handling — is exercised in tests.
- **Golden-set tests run separately from unit tests** (marked
  `@pytest.mark.golden`, excluded from the default fast test run) since
  they hit real APIs/LLMs and cost money — run in CI on a schedule or
  pre-release, not on every commit.
- **`evaluation/` checkers get two separate test treatments, not one:**
  a fast CI unit test against a fixture Langfuse trace (mock
  `langfuse_client.py`'s response, assert the checker's matching logic
  works), and a separate manual/scheduled run against real recent Runs
  for actual quality monitoring. Don't conflate the two — a fixture test
  proves the checker's logic is correct; it says nothing about whether
  today's Analyst reports are actually well-grounded.
- Every bug fix gets a regression test before the fix, not after.

---

## 6. Logging & Observability

- **Structured logging only** (`structlog` or equivalent) — every log
  line includes `run_id` when available, so logs correlate directly with
  a Langfuse trace and the Postgres `runs` row for the same execution.
- **Log levels:** `INFO` for node start/end and cache hits/misses, `WARNING`
  for a single-ticker Analyst failure (run continues), `ERROR` for
  anything that fails the whole `Run`.
- **Langfuse tags:** every LLM call is tagged with the Agent name and
  `run_id` at minimum, so a trace can be filtered per Agent or per Run
  without grepping.
- Never log full prompt/completion text to stdout/application logs —
  that's Langfuse's job; app logs should reference the Langfuse trace ID,
  not duplicate its content.
- **Tagging exists to serve `integrations/langfuse_client.py`'s read
  path, not just human debugging.** `check_analyst_groundedness`
  (`ARCHITECTURE.md` §8.B) queries traces by `run_id` and filters
  `tool_result` spans — if a call isn't tagged with `run_id`, it's
  invisible to that check. Treat the tagging rule above as a hard
  requirement for evaluation to function, not a nice-to-have for the
  Langfuse UI.
