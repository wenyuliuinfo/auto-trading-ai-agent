# ARCHITECTURE.md
## Thematic Stock/ETF Basket Multi-Agent System

This document is the single source of truth for implementation decisions.
If a coding agent (human or AI) is unsure how something should be built,
this file should answer it before guessing.

---

## 0. Purpose & Scope

Given an investment theme (e.g. "grid modernization"), the system:
1. Screens a candidate universe of tickers relevant to the theme.
2. Analyzes each candidate (fundamentals, news, sentiment).
3. Scores and ranks the universe with a deterministic quantitative model.
4. Constructs an 8-10 name basket under diversification/liquidity constraints.
5. Produces a written rationale document.

Runs are **triggered on-demand by a user request** — there is no scheduled
refresh (see §8, Decision: No Scheduler).

**Non-goals:** this is not a real-time trading/execution system, not a
brokerage integration, and does not place live orders. Output is research
and a proposed basket, not investment advice (see §9, Compliance).

---

## 1. Architecture Diagram

```
┌─────────────┐      ┌──────────────┐      ┌───────────────────┐
│  Next.js 16  │◄────►│   FastAPI     │◄────►│  Redis (queue +    │
│  (UI)        │ SSE/ │  (API layer)  │      │  cache)            │
└─────────────┘ poll  └──────┬───────┘      └─────────┬─────────┘
                              │ enqueue run             │ tasks
                              ▼                         ▼
                       ┌──────────────────────────────────────┐
                       │        Celery Worker(s)                │
                       │  ┌──────────────────────────────────┐  │
                       │  │     LangGraph Pipeline (§4)        │  │
                       │  │ Screener→Analyst(xN)→Modeling→     │  │
                       │  │ Validator→Trader→Report            │  │
                       │  └───────────┬────────────┬──────────┘  │
                       └──────────────┼────────────┼─────────────┘
                                      │            │
                     ┌────────────────┼────────────┼──────────────┐
                     ▼                ▼            ▼              ▼
              ┌────────────┐  ┌──────────────┐ ┌─────────┐  ┌───────────┐
              │ PostgreSQL │  │ LLM Providers │ │Pinecone │  │ Free data │
              │ (system of │  │ OpenAI +      │ │(semantic│  │ APIs (§6) │
              │ record +   │  │ DeepSeek      │ │ search, │  │ FMP/      │
              │ checkpoint)│  │               │ │ memory) │  │ Finnhub/  │
              └────────────┘  └──────────────┘ └─────────┘  │ GDELT/etc │
                                                              └───────────┘
              ┌──────────────────────┐   ┌───────────────────────────┐
              │  Langfuse (LLM/agent │   │ Prometheus + Grafana        │
              │  tracing)            │   │ (infra metrics/dashboards)  │
              └──────────────────────┘   └───────────────────────────┘
```

**Request flow:** Next.js → `POST /themes/{id}/runs` on FastAPI → FastAPI
enqueues a Celery task and returns `run_id` immediately → Celery worker
executes the LangGraph pipeline → Next.js polls `GET /runs/{run_id}` or
subscribes via SSE for progress → on completion, `GET /runs/{run_id}/basket`
and `/report` return final artifacts.

---

## 2. Data Model

### 2.1 Primary store: PostgreSQL (system of record + LangGraph checkpointer)

```sql
CREATE TABLE themes (
    theme_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    definition      TEXT NOT NULL,
    config          JSONB NOT NULL,        -- sub-exposures, factor weights, screens
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id        UUID REFERENCES themes(theme_id),
    requested_at    TIMESTAMPTZ DEFAULT now(),
    status          TEXT NOT NULL,          -- queued | running | complete | failed
    retry_count     INT DEFAULT 0,
    error_detail    TEXT
);

CREATE TABLE candidates (
    candidate_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID REFERENCES runs(run_id),
    ticker           TEXT NOT NULL,
    company_name     TEXT,
    gics_subindustry TEXT,
    sub_exposure_tag TEXT,
    market_cap       NUMERIC,
    avg_dollar_volume NUMERIC,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE analyst_reports (
    report_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID REFERENCES runs(run_id),
    ticker           TEXT NOT NULL,
    thematic_relevance_score     NUMERIC,
    thematic_relevance_rationale TEXT,
    revenue_pct_theme_estimate   NUMERIC,
    catalysts        JSONB,
    risks            JSONB,
    sentiment_label  TEXT,
    sentiment_evidence JSONB,
    sources          JSONB,
    fetched_at       TIMESTAMPTZ DEFAULT now(),   -- used for same-day cache lookups
    UNIQUE (ticker, run_id)
);
-- Cache lookup: reuse a report if one exists for `ticker` with
-- fetched_at > now() - interval '1 day', regardless of run_id, before
-- calling the Analyst LLM/tools again.

CREATE TABLE factor_panel (
    factor_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES runs(run_id),
    ticker          TEXT NOT NULL,
    as_of_date      DATE NOT NULL,
    factor_name     TEXT NOT NULL,       -- 'pe_ratio', 'roe', 'momentum_6m', ...
    raw_value       NUMERIC,
    z_score         NUMERIC
);

CREATE TABLE rankings (
    ranking_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID REFERENCES runs(run_id),
    ticker           TEXT NOT NULL,
    composite_score  NUMERIC,
    rank             INT,
    factor_contributions JSONB,
    caveats          JSONB
);

CREATE TABLE baskets (
    basket_row_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES runs(run_id),
    ticker          TEXT NOT NULL,
    weight          NUMERIC NOT NULL,
    rank            INT,
    sub_exposure    TEXT,
    swap_reason     TEXT
);

CREATE TABLE reports (
    report_doc_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES runs(run_id) UNIQUE,
    report_md       TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Populated manually/on-demand (no scheduler); feeds an eventual
-- learned-ranker feedback loop once enough history accumulates.
CREATE TABLE basket_performance (
    perf_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID REFERENCES runs(run_id),
    as_of_date       DATE NOT NULL,
    realized_return  NUMERIC,
    benchmark_return NUMERIC,
    alpha            NUMERIC
);
```

LangGraph's own state persistence uses `PostgresSaver` against this same
Postgres instance, in its own schema/tables — **do not** stand up MongoDB
for this; one database for both domain data and checkpointing keeps
operations simpler (see §8 for the Mongo decision).

### 2.2 Pinecone (vector store) — scoped to two specific uses only

Do not treat Pinecone as a generic "memory" bucket. It has exactly two
jobs in this system:
1. **Semantic candidate discovery**: embeddings of company business
   descriptions (10-K/10-Q text), queried by kNN against an embedded theme
   description, to supplement ETF-holdings/GICS-based screening in the
   Screener agent.
2. **Cross-run memory for the feedback loop**: embeddings of past run
   reports + realized performance from `basket_performance`, retrieved to
   give the Report or Modeling agent few-shot context from similar past
   theme runs.

If neither of these is implemented yet, Pinecone should be provisioned but
not assumed to be doing anything.

### 2.3 MongoDB — not used unless a specific need arises

Do not add MongoDB by default. Postgres JSONB columns (`catalysts`,
`risks`, `sources`, `factor_contributions`, `caveats`) already cover
semi-structured agent output. Only introduce Mongo if a genuine need for
large, schema-inconsistent raw document storage appears (e.g. archiving
full raw scraped news text) — and if so, scope it to that single
responsibility, not as a second system of record.

---

## 3. API Design (FastAPI)

| Endpoint | Method | Purpose |
|---|---|---|
| `/themes` | POST | Create a theme (name, definition, config: sub-exposures, factor weights) |
| `/themes/{theme_id}` | GET | Fetch a theme's definition/config |
| `/themes/{theme_id}/runs` | POST | Trigger a pipeline run for this theme. Enqueues to Celery, returns `{run_id, status: "queued"}` immediately — never runs the graph synchronously in the request handler. |
| `/runs/{run_id}` | GET | Run status/progress (`queued \| running \| complete \| failed`, plus `progress: {analyzed: 42, total: 120}` while running) |
| `/runs/{run_id}/events` | GET (SSE) | Streamed progress events for live UI updates, sourced from LangGraph's streaming interface |
| `/runs/{run_id}/basket` | GET | Final basket (ticker, weight, rank, sub_exposure) once complete |
| `/runs/{run_id}/report` | GET | Final rationale document (markdown) once complete |
| `/runs/{run_id}/rankings` | GET | Full ranked list + factor contributions (for transparency/debugging, not just the top 8-10) |

All write endpoints require auth (see §9). Read endpoints for run status
may be public within an authenticated session but should still be scoped
to the requesting user/org, not globally open.

---

## 4. Multi-Agent Orchestration Implementation

### 4.1 Agents and their responsibility boundary

| Agent | Job | LLM-driven? |
|---|---|---|
| Screener | Theme → bounded candidate list (50-150 tickers) | Yes — theme decomposition is language reasoning |
| Analyst (fan-out) | Per-ticker qualitative research → structured report | Yes — one call per candidate, parallelized |
| Modeling | Factor scoring + cross-sectional ranking | **No** for the ranking math — deterministic code. LLM only converts qualitative signals to numeric inputs and writes `caveats` text. |
| Validator (optional) | Bull/bear check on top ~12 ranked names | Yes — adversarial debate, bounded to top candidates only |
| Trader | Basket construction under constraints | **No** for selection/sizing — deterministic code. LLM only writes `swap_reason` prose. |
| Report | Synthesize everything into a rationale document | Yes — prose generation, strictly fact-bound to upstream outputs |

This split is intentional and load-bearing: ranking and portfolio
construction must be reproducible given the same inputs, so they are never
delegated to an LLM's judgment (see §8, Decision: Deterministic Ranking).

### 4.2 LangGraph state and fan-out/fan-in

```python
from typing import TypedDict, Annotated, List
import operator
from langgraph.graph import StateGraph, END
from langgraph.types import Send

class BasketState(TypedDict):
    theme: str
    theme_config: dict
    candidates: List[dict]
    analyst_reports: Annotated[List[dict], operator.add]   # fan-in accumulator
    factor_panel: List[dict]
    ranked_list: List[dict]
    basket: List[dict]
    near_misses: List[dict]
    report_md: str
    retry_count: int

def screener_node(state: BasketState) -> dict:
    return {"candidates": run_screener_agent(state["theme"], state["theme_config"])}

def fan_out_to_analysts(state: BasketState) -> List[Send]:
    return [
        Send("analyst_node", {"ticker": c["ticker"], "theme": state["theme"],
                               "theme_config": state["theme_config"]})
        for c in state["candidates"]
    ]

def analyst_node(state: dict) -> dict:
    # Check analyst_reports cache (fetched_at < 1 day) before calling LLM/tools
    report = run_analyst_agent(state["ticker"], state["theme"], state["theme_config"])
    return {"analyst_reports": [report]}

def modeling_node(state: BasketState) -> dict:
    factor_panel = fetch_factor_panel([r["ticker"] for r in state["analyst_reports"]])
    scored = compute_factor_scores(state["analyst_reports"], factor_panel)
    combined = combine_scores(scored, state["theme_config"]["weights"])
    return {"ranked_list": rank(combined), "factor_panel": factor_panel}

def validator_node(state: BasketState) -> dict:
    return {"ranked_list": run_bull_bear_check(state["ranked_list"][:12])}

def trader_node(state: BasketState) -> dict:
    basket, near_misses = construct_basket(state["ranked_list"], state["theme_config"])
    return {"basket": basket, "near_misses": near_misses}

def report_node(state: BasketState) -> dict:
    return {"report_md": run_report_agent(state)}

def check_basket_complete(state: BasketState) -> str:
    if len(state["basket"]) >= 8 or state.get("retry_count", 0) >= 2:
        return "report"
    return "screener_retry"   # widen candidate pool and retry, capped at 2 attempts

graph = StateGraph(BasketState)
graph.add_node("screener", screener_node)
graph.add_node("analyst_node", analyst_node)
graph.add_node("modeling", modeling_node)
graph.add_node("validator", validator_node)
graph.add_node("trader", trader_node)
graph.add_node("report", report_node)

graph.set_entry_point("screener")
graph.add_conditional_edges("screener", fan_out_to_analysts, ["analyst_node"])
graph.add_edge("analyst_node", "modeling")
graph.add_edge("modeling", "validator")
graph.add_edge("validator", "trader")
graph.add_conditional_edges("trader", check_basket_complete,
                            {"screener_retry": "screener", "report": "report"})
graph.add_edge("report", END)

app = graph.compile(checkpointer=postgres_checkpointer)
```

**Critical implementation notes:**
- The `Annotated[List[dict], operator.add]` reducer on `analyst_reports` is
  what makes fan-in work — omitting it causes parallel branches to
  overwrite each other instead of accumulating.
- Wrap `run_analyst_agent` in try/except; a single ticker's failure should
  return an `{"ticker": ..., "status": "error"}` stub into the same
  reducer, not crash the whole run. `modeling_node` filters these out.
- Rate-limit concurrency inside the tool clients used by `analyst_node`
  (semaphore or bounded executor), not at the graph level — this matters
  especially given free-tier data source rate limits (§6).
- Collaboration pattern is a **fixed pipeline/DAG**, not a free-form
  supervisor — the only two non-linear points are the bounded retry loop
  (screener re-entry, capped at 2) and the validator's narrow
  re-ordering of `ranked_list`. Do not introduce an LLM router deciding
  "what happens next" more broadly than this.

---

## 5. Prompt and Answer Contract

Each agent has a fixed system prompt and a strict output schema enforced
via the LLM provider's native structured-output/tool-calling feature
(not "please respond in JSON" in prose) — this is what makes downstream
parsing safe.

### 5.1 Screener
**Contract:** theme string + config → `List[CandidateStock]` JSON, no
ranking or opinion.
```
SystemMessage: You are a Universe Screener for a thematic equity research
desk. Convert a theme into a bounded, verifiable candidate list — do not
judge or rank. Decompose into 3-6 sub-exposures, call search_holdings/
search_sector for each (never invent tickers from memory), dedupe, and
output 50-150 candidates as JSON: {ticker, company_name, gics_subindustry,
sub_exposure_tag, market_cap, avg_dollar_volume}. Flag (don't exclude)
ADV < $5M or market cap < $300M. If a sub-exposure returns <5 candidates,
say so rather than padding the list.
```

### 5.2 Analyst
**Contract:** ticker + theme → `AnalystReport` JSON, every claim sourced.
```
SystemMessage: You are a Thematic Equity Analyst. Given one ticker and a
theme, call get_news(ticker, lookback_days=90) and get_fundamentals(ticker)
against connected sources. Score thematic relevance 1-5 with rationale and
a revenue % estimate. Note catalysts and risks. Output strictly as JSON:
{ticker, thematic_relevance_score, thematic_relevance_rationale,
revenue_pct_theme_estimate, catalysts[], risks[], sentiment_label,
sentiment_evidence[], sources[]}. Every claim must cite a tool-result
source. Missing data → null with a reason, never filled from general
knowledge. You are not ranking or selecting stocks.
```

### 5.3 Modeling
**Contract:** all `AnalystReport`s + factor panel → `RankedList` JSON
(deterministic; LLM touches only the `caveats` field and numeric
conversion of qualitative inputs).
```
SystemMessage: You are a Quantitative Ranking Agent. You do not use
subjective judgment to order stocks. Convert thematic_relevance_score and
sentiment_label to numeric inputs, then call compute_factor_scores,
combine_scores, and rank (deterministic functions — do not substitute your
own weighting). Output: {ticker, composite_score, factor_contributions,
rank, caveats[]}. If a result looks wrong (e.g. a thin microcap ranking
#1 on momentum alone), flag it in caveats — do not silently re-order.
```

### 5.4 Validator (optional)
**Contract:** top ~12 `RankedList` entries → re-ordered/annotated subset,
bull/bear debate transcript retained for audit.
```
SystemMessage (bull persona / bear persona / synthesis, 3 roles): Argue
the strongest case for/against including {ticker} in the basket, grounded
only in the provided AnalystReport and factor_contributions — do not
introduce outside facts. [Synthesis role]: given both cases across
{max_rounds} rounds, output a verdict: keep, demote, or flag for manual
review, with a one-sentence justification.
```

### 5.5 Trader
**Contract:** ranked list → `Basket` JSON (deterministic selection/sizing;
LLM touches only `swap_reason` prose).
```
SystemMessage: You are a Portfolio Construction Agent. Select top-ranked
names, applying hard screens (ADV < $5M, cap < $300M, caveats="exclude"),
sector diversification (max 3 per GICS sub-industry per basket), and
position sizing (equal-weight default; if score-weighted, floor 5%/cap
20%). If diversification forces skipping a higher-ranked name, log the
swap and reason explicitly. Output: {ticker, weight, rank, sub_exposure,
swap_reason?} plus near_misses (ranks 11-15).
```

### 5.6 Report
**Contract:** full run state → markdown document, zero new facts.
```
SystemMessage: You are an Investment Rationale Writer. Using only the
theme definition, AnalystReports, factor_contributions, and the final
Basket — write: (1) 2-3 sentence thesis, (2) per-holding rationale
(2-4 sentences, vary sentence structure, ground in thematic_relevance_
rationale + top factor contributions + catalysts), (3) considered-but-
excluded section from near_misses, (4) aggregated basket-level risk
section (risks shared across ≥2 holdings called out once, not repeated
per-stock). Do not introduce facts not present in the upstream data.
```

---

## 6. Third-Party Integrations

| Category | Provider | Notes |
|---|---|---|
| LLM (high-volume, low-stakes: Analyst fan-out) | DeepSeek | Cost-optimized for 50-150 calls/run |
| LLM (low-volume, high-stakes: Modeling caveats, Validator, Report) | OpenAI | Higher reasoning quality where it matters most |
| LLM fallback | `.with_fallbacks()` chain, OpenAI ⇄ DeepSeek | Handles rate-limit/outage on either provider |
| Fundamentals | Financial Modeling Prep (free tier), Finnhub (free tier), SEC EDGAR (free, primary source cross-check) | Free tiers are rate-capped — caching (§2.1) is load-bearing, not optional |
| Price/technical | yfinance, Stooq | yfinance is unofficial/ToS gray area — acceptable for internal/prototype use, revisit before commercial deployment |
| News | GDELT (free, high volume), NewsAPI (free tier, dev-only cap) | Spread load across both rather than relying on one |
| Sentiment | Reddit API, StockTwits API (both free tier) | |
| ETF holdings/constituents | Issuer CSVs (iShares/SPDR/Invesco), Wikipedia index lists, stockanalysis.com | Less complete for niche thematic ETFs — may need manual curation per theme |
| Vector store | Pinecone | Scoped uses only — see §2.2 |
| Queue/cache | Redis + Celery | Chosen over Kafka — no multi-consumer streaming need at current scale |
| Tracing | Langfuse (self-hosted) | LLM/agent-level tracing: prompts, completions, token usage, cost, nested spans. Native LangChain callback integration. |
| Metrics/dashboards | Prometheus + Grafana (self-hosted) | Infra-level: API latency, queue depth, container health — complements, does not replace, Langfuse |

---

## 7. Technical Decisions (rationale log)

| Decision | Rejected alternative | Why |
|---|---|---|
| Deterministic code for ranking (Modeling) and basket construction (Trader) | LLM-driven ranking/selection | Reproducibility and auditability — same inputs must always produce the same rank/basket |
| Redis + Celery for queue | Kafka | No durable multi-consumer streaming need at current scale; simpler to operate |
| Postgres for LangGraph checkpointing | MongoDB | Avoids a second persistence layer with no clear added benefit |
| MongoDB not used by default | Using it for agent output storage | Postgres JSONB already covers semi-structured fields |
| Pinecone scoped to 2 named use cases | Generic "memory" store | Prevents provisioning infra with no defined job |
| Request-triggered runs only, no scheduler | Daily/hourly refresh + Celery Beat | Explicit product requirement — simplifies infra (no cron, no nightly ETL) |
| Free-tier data sources | Bloomberg/Morningstar/YCharts | Cost — but requires aggressive caching to survive rate limits, and accepting thinner estimate-revision data |
| Langfuse + Prometheus/Grafana | LangSmith | Self-hosted requirement; Langfuse purpose-built for LLM tracing, Prometheus/Grafana for infra metrics — complementary, not overlapping |
| Bounded retry loop (max 2) on basket completeness | Unlimited retry / hard failure | Avoids infinite loops while giving the Screener a chance to widen the pool once or twice |
| Validator scoped to top ~12 only | Debate over full universe (TradingAgents-style) | Cost control — full-universe debate doesn't scale to 100+ candidates |

---

## 8. Evaluation Plan

Because two of the five agents are deliberately deterministic, evaluation
splits cleanly into two tracks:

**A. Deterministic components (Modeling math, Trader constraints) — unit-testable, standard software testing:**
- Unit tests on `compute_factor_scores`, `combine_scores`, `rank` against
  known input/output pairs (including edge cases: all-NaN factor column,
  tied composite scores, single-candidate universe).
- Property tests: composite score must be monotonic in each factor
  holding others fixed; rank must be a valid permutation of 1..N.
- Trader constraint tests: verify sector caps and liquidity floors are
  never violated in the output basket, across randomized ranked-list
  fixtures.

**B. LLM-driven components (Screener, Analyst, Validator, Report) — golden-set + groundedness checks:**
- Maintain a small golden set of themes with manually-reviewed expected
  candidate coverage (not exact match, but "does the candidate list
  include the known obvious names for this theme").
- Schema validation on every agent output (already enforced at runtime via
  structured output, but re-verify in CI against the Pydantic/JSON schema).
- Groundedness check on Analyst reports: every `sources` entry must
  correspond to an actual tool call made in that run (catch hallucinated
  citations) — this can be automated by cross-referencing the Langfuse
  trace against the claimed sources.
- Report agent: automated check that no numeric claim in `report_md`
  is absent from the upstream `analyst_reports`/`rankings` state (a
  simple entity/number extraction + presence check catches invented
  figures).

**C. System-level:**
- Shadow-mode comparison whenever `factor_weights` in a theme's config
  change — rerun the same candidate set with old vs. new weights and diff
  the resulting basket before promoting the new weights.
- Once `basket_performance` accumulates enough history (populated
  on-demand, per §2.1), backtest composite score against realized forward
  return to validate the ranking is actually predictive, not just
  self-consistent.
- Human review gate: no theme's basket should be treated as
  client-facing output until at least one manual review pass, especially
  early on given free-tier data source limitations (§6).

---

## 9. Security and Compliance Controls

- **Secrets management:** vendor API keys (LLM providers, data sources)
  in a secrets manager (Vault, cloud provider secrets store, or Docker
  secrets at minimum) — never in env vars baked into images.
- **Auth:** FastAPI endpoints require authenticated sessions (JWT or
  OAuth2, scoped per user/org); run status/results are scoped to the
  requesting identity, not globally readable.
- **Rate limiting at the API layer**, separate from the data-vendor rate
  limits — protects against a user triggering excessive concurrent runs
  that would exhaust shared free-tier quotas for everyone.
- **Data vendor ToS compliance:** yfinance in particular sits in a legal
  gray area re: Yahoo's terms of service — acceptable for internal/
  prototype use; flag for replacement with a licensed source before any
  commercial/client-facing deployment.
- **Prompt-injection surface:** the Analyst agent ingests third-party
  news/web content as tool results. Treat all fetched text as untrusted —
  it should never be interpreted as instructions to the agent (e.g. an
  article containing "ignore previous instructions" must not alter
  agent behavior). Sanitize/wrap tool results clearly as data, not as
  message-role content the model would treat as directives.
- **Audit trail immutability:** `reports`, `rankings`, and
  `analyst_reports` rows should not be mutated after a run completes —
  append-only, tied to an immutable `run_id`, so any output can be traced
  back to the exact evidence that produced it, indefinitely.
- **Disclaimers:** every generated report must carry a clear "not
  investment advice, for research purposes only" disclaimer — this is
  a compliance requirement given the output resembles investment
  research, not just a nice-to-have footer.
- **Data retention:** define a retention policy for `analyst_reports`/
  `candidates` (raw news/fundamentals snapshots) — these may need
  time-bounded retention depending on vendor ToS and your own data
  governance policy, not indefinite storage by default.

---

## 10. Runtime Topology and Failure Modes

### 10.1 Docker Compose service inventory

`nextjs`, `fastapi`, `celery-worker` (scalable replica count), `redis`,
`postgres`, `langfuse` (+ its own dedicated Postgres instance — do not
share with the domain DB), `prometheus`, `grafana`, `tempo` (if using
OpenTelemetry alongside Langfuse for infra traces).

### 10.2 Failure modes

| Failure | Detection | Mitigation |
|---|---|---|
| Single ticker's Analyst call fails (data vendor error, LLM error) | try/except in `analyst_node` returns an error stub into the reducer | `modeling_node` filters error stubs; run continues with remaining tickers; logged to Langfuse |
| Free-tier data source rate limit exhausted mid-run | HTTP 429 from vendor API | Exponential backoff + fall back to a secondary free source for that data type (§6); if all exhausted, that field returns null per the Analyst contract rather than blocking the run |
| LLM provider outage/rate limit (OpenAI or DeepSeek) | Provider error response | `.with_fallbacks()` chain routes to the other provider automatically |
| Trader can't fill 8 slots after constraints | `check_basket_complete` conditional edge | Bounded retry (max 2) back to Screener with widened parameters; beyond that, Report agent explicitly notes the shortfall rather than the system silently failing |
| Worker process crashes mid-fan-out (100+ tickers, partway through) | Celery task failure / missing heartbeat | LangGraph's `PostgresSaver` checkpoint allows resume from the last completed step, not a full restart from Screener |
| Postgres unavailable | Connection error at any DB-touching node | Run marked `failed` with `error_detail`; Celery retry policy with backoff; no silent data loss since nothing is checkpointed to memory only |
| Redis unavailable | Celery task enqueue fails | FastAPI returns a clear 5xx to the client rather than silently accepting a request it can't fulfill; no in-request fallback to synchronous execution |
| Pinecone unavailable | Query error in Screener/Report | Screener degrades to ETF-holdings/GICS-only candidate generation (semantic search is a supplement, not the sole method, per §2.2) |

---

## 11. Open Questions / Future Work

- Learning-to-rank (e.g. `LGBMRanker`) to replace hand-set factor weights,
  once `basket_performance` history is sufficient — deferred until there's
  real historical data to train on.
- Formal auth/access-control model (roles, org boundaries) — deferred
  while internal/prototype, must be resolved before any external users.
- Whether to license a paid fundamentals/news data source once free-tier
  limitations (thin estimate-revision data, yfinance's ToS standing)
  become a real constraint on output quality.
- Whether the Validator (bull/bear) step is worth its added cost/latency
  in practice — recommend running with it optional/toggleable per theme
  until there's evidence it changes basket composition meaningfully.
