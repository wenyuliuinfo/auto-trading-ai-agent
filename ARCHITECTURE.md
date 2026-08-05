# ARCHITECTURE.md
## Auto Trading Stock/ETF Basket Multi-Agent System

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
│  Next.js 16 │◄────►│   FastAPI    │◄────►│  Redis (queue +   │
│  (UI)       │ SSE/ │  (API layer) │      │  cache)           │
└─────────────┘ poll └──────┬───────┘      └─────────┬─────────┘
                            │ enqueue run            │ tasks
                            ▼                        ▼
                ┌──────────────────────────────────────┐
                │        Celery Worker(s)              │
                │  ┌──────────────────────────────────┐│
                │  │     LangGraph Pipeline (§4)      ││
                │  │ Screener→Analyst(xN)→Modeling→   ││
                │  │ Validator→Trader→Report          ││
                │  └───────────┬────────────┬─────────┘│
                └──────────────┼────────────┼──────────┘
                               │            │
              ┌────────────────┼────────────┼──────────────┐
              ▼                ▼            ▼              ▼
          ┌────────────┐  ┌──────────────┐ ┌─────────┐  ┌───────────┐
          │ PostgreSQL │  │ LLM Providers│ │Pinecone │  │ Free data │
          │ (system of │  │ OpenAI +     │ │(semantic│  │ APIs (§6) │
          │ record +   │  │ DeepSeek     │ │ search, │  │ FMP/      │
          │ checkpoint)│  │              │ │ memory) │  │ Finnhub/  │
          └────────────┘  └──────────────┘ └─────────┘  │ GDELT/etc │
                                                        └───────────┘
                        ┌──────────────────────┐  
                        │  Langfuse (LLM/agent │
                        │  tracing)            │ 
                        └──────────────────────┘
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
                                            -- (config.factor_weights is REQUIRED and
                                            -- SYSTEM-POPULATED ONLY — see the rule
                                            -- immediately below)
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

**`config.factor_weights` sourcing rule — never user input, in any form:**
factor weighting policy lives in exactly one place in the whole system:
`config/factor_weights.yaml`, a hand-maintained, ops/quant-owned file
(same pattern as `config/sub_exposure_etf_map.yaml`). It is loaded
**exactly once**, by the `POST /themes` handler, and copied verbatim into
`config.factor_weights` at theme-creation time. There is **no API field,
no UI control, and no code path that lets a caller supply or override
it** — the actual client-facing request schema,
`config/theme_create_request.schema.json`, has no `factor_weights`
property at all, and a request that includes one is rejected with a 422
rather than silently ignored (silently ignoring it would let a caller
believe they'd customized weighting policy when they hadn't).
`modeling_node` must **only** read `theme_config["factor_weights"]` from
already-persisted state and must raise, never fall back to any default,
if it's missing. This is what makes weights real persisted data —
diffable and safe to shadow-test (§8.C) — while keeping the weighting
*methodology* entirely out of user reach, unlike `screens` and
`weighting_scheme`, which remain legitimate per-theme request input (see
`config/theme_create_request.schema.json` for that distinction spelled
out). See `config/theme_config.schema.json` for the full stored shape.


```sql

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
    -- Deliberately NO composite_score column — it already lives in
    -- `rankings`, keyed by (run_id, ticker). See TRADER_SKILL.md Hard
    -- Rule 5 and get_basket_with_scores() in §3 below: the API layer and
    -- Report agent both join baskets + rankings at read time rather than
    -- storing the value twice, where it could drift out of sync with
    -- what Modeling actually computed.
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

---

## 3. API Design (FastAPI)

| Endpoint | Method | Purpose |
|---|---|---|
| `/themes` | POST | Create a theme (`name`, `definition`, `sub_exposures`, optionally `screens`/`weighting_scheme`/`validator_enabled` — see `config/theme_create_request.schema.json`). **`factor_weights` is never accepted here or anywhere** — it's loaded server-side from `config/factor_weights.yaml`; a request that includes it gets a 422. |
| `/themes/{theme_id}` | GET | Fetch a theme's definition/config |
| `/themes/{theme_id}/runs` | POST | Trigger a pipeline run for this theme. Enqueues to Celery, returns `{run_id, status: "queued"}` immediately — never runs the graph synchronously in the request handler. |
| `/runs/{run_id}` | GET | Run status/progress (`queued \| running \| complete \| failed`, plus `progress: {analyzed: 42, total: 120}` while running) |
| `/runs/{run_id}/events` | GET (SSE) | Streamed progress events for live UI updates, sourced from LangGraph's streaming interface |
| `/runs/{run_id}/basket` | GET | Final basket (ticker, weight, rank, sub_exposure, **composite_score**) once complete |
| `/runs/{run_id}/report` | GET | Final rationale document (markdown) once complete |
| `/runs/{run_id}/rankings` | GET | Full ranked list + factor contributions + **composite_score** (for transparency/debugging, not just the top 8-10) |

All write endpoints require auth (see §9). Read endpoints for run status
may be public within an authenticated session but should still be scoped
to the requesting user/org, not globally open.

**Contract rule:** `composite_score` is not an optional/debug-only field —
it must be present on every ticker returned by `/runs/{run_id}/basket`
and `/runs/{run_id}/rankings`, since the UI displays it directly next to
each holding (not just in an expandable "details" view) and the Report
agent's contract (§5.5) depends on it being available in Run state at
generation time. **Implementation:** since `baskets` has no
`composite_score` column by design (§2.1), both this endpoint and the
Report agent's context assembly get it via the same shared join function,
`get_basket_with_scores()` (`TRADER_SKILL.md`) — do not reimplement the
`baskets`/`rankings` join in the API handler separately from the one
`REPORT_SKILL.md` uses. Any refactor of the `rankings`/`baskets` schema
(§2.1) must preserve this field's presence — treat dropping or renaming
it as a breaking API change requiring a version bump, not a routine
cleanup.


---

## 4. Multi-Agent Orchestration Implementation

### 4.1 Agents and their responsibility boundary

| Agent | Job | LLM-driven? | Implementation skill |
|---|---|---|---|
| Screener | Theme → bounded candidate list (50-150 tickers) | Yes — theme decomposition is language reasoning | `SCREENER_SKILL.md` |
| Analyst (fan-out) | Per-ticker qualitative research → structured report | Yes — one call per candidate, parallelized | `ANALYST_SKILL.md` |
| Modeling | Factor scoring + cross-sectional ranking | **No** for the ranking math — deterministic code. LLM only converts qualitative signals to numeric inputs and writes `caveats` text. | `MODELING_SKILL.md` |
| Validator (optional) | Bull/bear check on top ~12 ranked names | Yes — adversarial debate, bounded to top candidates only | *(none yet — flagged gap, §11)* |
| Trader | Basket construction under constraints | **No** for selection/sizing — deterministic code. LLM only writes `swap_reason` prose. | `TRADER_SKILL.md` |
| Report | Synthesize everything into a rationale document | Yes — prose generation, strictly fact-bound to upstream outputs | `REPORT_SKILL.md` |

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
    weights = state["theme_config"]["factor_weights"]  # REQUIRED, system-populated
                                                          # at theme creation from
                                                          # config/factor_weights.yaml —
                                                          # never user input; see §2.1
    combined = combine_scores(scored, weights)
    return {"ranked_list": rank(combined), "factor_panel": factor_panel}

def validator_node(state: BasketState) -> dict:
    return {"ranked_list": run_bull_bear_check(state["ranked_list"][:12])}

def trader_node(state: BasketState) -> dict:
    # construct_basket is pure/deterministic (TRADER_SKILL.md Hard Rule 1);
    # swap_events is structured data, turned into swap_reason prose by a
    # narrow LLM call inside trader_node — see TRADER_SKILL.md for the
    # full implementation, this is the state-shape summary only.
    basket, near_misses, swap_events = construct_basket(
        state["ranked_list"], state["theme_config"]
    )
    if swap_events:
        basket = attach_swap_reasons(basket, swap_events)  # TRADER_SKILL.md
    save_basket(state["run_id"], basket)  # ticker/weight/rank/sub_exposure/
                                            # swap_reason only — composite_score
                                            # is NOT duplicated here (§2.1)
    return {"basket": basket, "near_misses": near_misses}

def report_node(state: BasketState) -> dict:
    # assemble_report_context joins basket+rankings (via get_basket_with_scores,
    # defined once in data/queries.py, shared with the /runs/{run_id}/basket
    # API handler — §3) and pre-clusters shared risks before the single LLM
    # call. apply_disclaimer wraps the result unconditionally. Full
    # implementation in REPORT_SKILL.md.
    context = assemble_report_context(state["run_id"], state["theme"], state["near_misses"])
    report_md = apply_disclaimer(run_report_agent(context))
    save_report(state["run_id"], report_md)
    return {"report_md": report_md}

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
SystemMessage:

You are a Universe Screener for a thematic equity research desk. Your job is
to convert an investment theme into a bounded, verifiable list of candidate
tickers — not to judge or rank them.

Given a theme (e.g. "grid modernization," "GLP-1 supply chain," "onshoring
of semiconductor capacity"), you will:

1. Decompose the theme into 3-6 sub-exposures (e.g. for "grid modernization":
   transmission equipment, smart meters, grid software, utilities capex
   beneficiaries, battery storage).
2. For each sub-exposure, call the `search_holdings` and `search_sector`
   tools to pull constituent tickers from relevant thematic ETFs, GICS
   sub-industries, and index membership — do not invent tickers from memory.
3. Deduplicate and output a candidate list of 50-150 US and major
   international listed equities/ETFs with: ticker, company name, GICS
   sub-industry, sub-exposure tag, market cap, and average daily dollar
   volume (for a later liquidity filter).
4. Flag (but do not exclude) any name with ADV under $5M or market cap
   under $300M — the Trader agent will apply the final liquidity screen.

Do not include an investment opinion. Do not rank. Output only the
structured candidate table as JSON matching the provided schema. If a
sub-exposure returns fewer than 5 candidates, say so explicitly rather than
padding the list with loosely related names.
```

### 5.2 Analyst
**Contract:** ticker + theme → `AnalystReport` JSON, every claim sourced.
```
SystemMessage:

You are a Thematic Equity Analyst. You will receive one ticker at a time
from a pre-screened candidate universe and a theme definition. Your job is
to produce a grounded, source-cited analysis — not a recommendation.

For the given ticker:

1. Call `get_news(ticker, lookback_days=90)` against the connected
   data sources (GDELT/NewsAPI (news), SEC EDGAR (business description/segment revenue), StockTwits/Reddit (sentiment)) and summarize
   only what is reported — do not speculate beyond the sources.
2. Assess thematic relevance on a 1-5 scale: does this company's revenue
   meaningfully derive from the theme, or is the connection tangential?
   State the % of revenue tied to the theme if disclosed, or your best
   sourced estimate with a confidence flag if not.
3. Note near-term catalysts (next 2 quarters: earnings, product launches,
   regulatory decisions) and key risks (customer concentration, regulatory,
   competitive, balance sheet).

Output strictly as JSON matching the AnalystReport schema: 
{ticker, thematic_relevance_score, thematic_relevance_rationale,
 revenue_pct_theme_estimate, catalysts[], risks[], sentiment_label,
 sentiment_evidence[], sources[]}.

Every factual claim must cite a source from the tool results. If data is
unavailable for a field, output null and say why — do not fill gaps with
generic knowledge. You are not selecting or ranking stocks; you are
building the evidence base another agent will score.
```

### 5.3 Modeling
**Contract:** all `AnalystReport`s + factor panel → `RankedList` JSON
(deterministic; LLM touches only the `caveats` field and numeric
conversion of qualitative inputs).
```
SystemMessage:

You are a Quantitative Ranking Agent. You do not write prose analysis and
you do not use subjective judgment to order stocks. You compute a
transparent, reproducible composite score for every stock in the universe
and output a ranked table.

You will be given, for each ticker: the structured Analyst report (Step 1)
and a quantitative factor panel (valuation, growth, quality, momentum,
liquidity — supplied via the `get_factor_panel` tool).

Procedure (do this exactly, do not substitute your own weighting scheme
unless explicitly instructed):

1. Convert the Analyst's `thematic_relevance_score` (1-5) and
   `sentiment_label` into numeric factor inputs.
2. Call `compute_factor_scores(universe)` to z-score every quantitative
   factor cross-sectionally against the candidate universe (not the
   broader market).
3. Call `combine_scores(factor_scores, weights)` using the supplied
   weighting config to produce one composite score per ticker.
4. Call `rank(composite_scores)` to produce the final ordered list with
   each factor's contribution shown (for auditability).
5. Do not override the computed rank with your own opinion. If a result
   looks wrong (e.g. a thinly-traded microcap ranks #1 purely on momentum),
   flag it in a `caveats` field rather than silently re-ordering.

Output: ranked table with ticker, composite_score, factor_contributions
{thematic, valuation, growth, quality, momentum, sentiment}, rank,
caveats[]. This output must be reproducible — given the same inputs, the
same ranking must result.
```

### 5.4 Trader
**Contract:** ranked list → `Basket` JSON (deterministic selection/sizing;
LLM touches only `swap_reason` prose). **Canonical implementation:**
`TRADER_SKILL.md` — `construct_basket()` performs constraints 1-4 below
as plain code; the LLM is invoked once, only if a diversification skip
occurred, over the structured `swap_events` the code already produced —
it never decides which ticker was skipped or why, only phrases the
explanation.
```
SystemMessage:

You are a Portfolio Construction Agent. You take the ranked list from the
Modeling Agent and construct an 8-10 name basket. You are not re-analyzing
company merits — the ranking is your primary input.

Constraints you must enforce:
1. Select top-ranked names, but skip any that fail the hard screens: 
   ADV < $5M, market cap < $300M, or a `caveats` flag marked "exclude"
   from the Modeling Agent.
2. Sector/sub-exposure diversification: no single GICS sub-industry may
   account for more than 3 of the 8-10 positions, so the basket reflects
   the theme's breadth, not one sub-exposure.
3. Position sizing: default to equal_weight unless `weighting_scheme` is
   set to score_weighted (`config/theme_create_request.schema.json` —
   these are the only two valid values). If score_weighted, normalize
   composite scores to sum to 100%, floor any position below 5%, cap any
   position above 20%, then renormalize the clipped weights so the
   basket still sums to 100% (`TRADER_SKILL.md` Hard Rule 4).
4. If enforcing constraint 2 requires skipping a higher-ranked name for a
   lower-ranked one in an underrepresented sub-exposure, log that swap
   explicitly with the reason.

Output: final basket {ticker, weight, rank, sub_exposure, swap_reason if
applicable}, plus a list of near-miss names (ranked 11-15) for the Report
Agent to reference as "considered but excluded."
```

### 5.5 Report
**Contract:** full run state → markdown document, zero new facts.
**Canonical implementation:** `REPORT_SKILL.md` — `assemble_report_context()`
gathers `analyst_reports`, `basket` (joined with `composite_score` via
`get_basket_with_scores()`, §3), and `near_misses` into one dict before
the single LLM call; `group_shared_risks()` pre-clusters risk overlaps
across holdings by code (point 4 below is a code-verified fact the model
describes, not a pattern it has to spot unaided); `apply_disclaimer()`
appends the required "not investment advice" notice unconditionally
after generation — never left to the prompt to remember.
```
SystemMessage:

You are an Investment Rationale Writer. You will receive the full audit
trail: theme definition, Analyst reports, Modeling Agent factor
breakdowns (including composite_score), and the Trader Agent's final
basket with weights.

Write a client-ready rationale document with:
1. A 2-3 sentence theme thesis.
2. Per-holding rationale (2-4 sentences each): why it's in the basket,
   grounded specifically in its thematic_relevance_rationale, composite_score
   and top-2 factor_contributions, and any near-term catalyst — not
   generic boilerplate. Do not repeat the same sentence structure for
   every name.
3. A short "considered but excluded" section referencing 2-3 near-miss
   names and why they didn't make the cut (this builds credibility).
4. A risk section: describe the pre-clustered risk_clusters you were
   given (each already verified to be shared by ≥2 holdings) as
   basket-level risks, not per-stock footnotes — do not attempt to find
   additional overlaps yourself beyond what's provided.

Ground every claim in the upstream agent outputs — do not introduce new
facts. If the Modeling Agent flagged a caveat on a held position, surface
it here rather than omitting it. This is not a research report from
scratch; it is a faithful synthesis of the pipeline's own outputs.
```

---

## 6. Third-Party Integrations

| Category | Provider | Notes |
|---|---|---|
| LLM (high-volume, low-stakes: Analyst fan-out) | DeepSeek | Cost-optimized for 50-150 calls/run |
| LLM (low-volume, high-stakes: Modeling caveats, Validator, Report) | DeepSeek v4 pro | Higher reasoning quality where it matters most |
| Fundamentals | Financial Modeling Prep (free tier), Finnhub (free tier), SEC EDGAR (free, primary source cross-check) | Free tiers are rate-capped — caching (§2.1) is load-bearing, not optional |
| Price/technical | yfinance, Stooq | yfinance is unofficial/ToS gray area — acceptable for internal/prototype use, revisit before commercial deployment |
| News | GDELT (free, high volume), SerpApi's Google News (free tier) | Spread load across both rather than relying on one |
| Sentiment | StockTwits API (free tier) | |
| ETF holdings/constituents | Issuer CSVs (iShares/SPDR/Invesco), Wikipedia index lists, stockanalysis.com | Less complete for niche thematic ETFs — may need manual curation per theme |
| Vector store | Pinecone | Scoped uses only — see §2.2 |
| Queue/cache | Redis + Celery | Chosen over Kafka — no multi-consumer streaming need at current scale |
| Tracing | Langfuse (self-hosted) | LLM/agent-level tracing: prompts, completions, token usage, cost, nested spans. Native LangChain callback integration. |

---

## 7. Technical Decisions (rationale log)

| Decision | Rejected alternative | Why |
|---|---|---|
| Deterministic code for ranking (Modeling) and basket construction (Trader) | LLM-driven ranking/selection | Reproducibility and auditability — same inputs must always produce the same rank/basket |
| Redis + Celery for queue | Kafka | No durable multi-consumer streaming need at current scale; simpler to operate |
| Postgres for LangGraph checkpointing | MongoDB | Avoids a second persistence layer with no clear added benefit |
| Pinecone scoped to 2 named use cases | Generic "memory" store | Prevents provisioning infra with no defined job |
| Request-triggered runs only, no scheduler | Daily/hourly refresh + Celery Beat | Explicit product requirement — simplifies infra (no cron, no nightly ETL) |
| Free-tier data sources | Bloomberg/Morningstar/YCharts | Cost — but requires aggressive caching to survive rate limits, and accepting thinner estimate-revision data |
| Langfuse + Prometheus/Grafana | LangSmith | Self-hosted requirement; Langfuse purpose-built for LLM tracing, Prometheus/Grafana for infra metrics — complementary, not overlapping |
| Bounded retry loop (max 2) on basket completeness | Unlimited retry / hard failure | Avoids infinite loops while giving the Screener a chance to widen the pool once or twice |
| Validator scoped to top ~12 only | Debate over full universe (TradingAgents-style) | Cost control — full-universe debate doesn't scale to 100+ candidates |

---

## 8. Evaluation Plan

Because two of the five agents are deliberately deterministic, evaluation
splits cleanly into two tracks, plus a third for evaluation logic that
needs its own home in the codebase.

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
- **Candidate coverage golden set**: pull the top 10-15 holdings of each
  theme's mapped ETFs (`config/sub_exposure_etf_map.yaml`) as the "known
  obvious names" a theme's Candidate Universe should generally include.
  Not exact-match — flags a gap if the Screener systematically misses
  well-known names for a theme.
- **Basket plausibility check (soft overlap, not exact match)**: verify
  the final basket has *some* non-trivial overlap (≥2-3 tickers) with the
  union of top-15 holdings across a theme's mapped ETFs. Zero overlap
  across every relevant ETF is a signal worth a reviewer's attention
  (possible Screener/Modeling malfunction); partial overlap is expected
  and often desirable — the system intentionally scores on different
  factors than ETF cap-weighting, so full agreement isn't the goal and
  shouldn't be tested for. This is explicitly *not* the same check as
  candidate coverage above: it's evaluating the Trader's final picks, not
  the Screener's raw universe.
- Schema validation on every agent output (already enforced at runtime via
  structured output, but re-verify in CI against the Pydantic/JSON schema).
- **Groundedness check on Analyst reports** (`app/evaluation/groundedness.py`,
  `check_analyst_groundedness`): every `sources` entry must correspond to
  an actual tool-call result recorded in that run's Langfuse trace (catch
  hallucinated citations). Implemented via a new `integrations/langfuse_client.py`
  read path (querying traces is a different API surface than the
  write-side callback already used for logging) that pulls `tool_result`
  spans and builds a known-source set to check `sources` against. Split
  into two runs, not one: a CI unit test against a fixture trace (fast,
  deterministic, mocked Langfuse response), and a separate operational
  job that runs the same checker against real recent runs for ongoing
  quality monitoring — the latter is a post-hoc audit and must not block
  a run's completion.
- **Groundedness check on the Report** (`app/evaluation/groundedness.py`,
  `check_report_groundedness`): regex-extract every number/percentage/
  dollar figure from `report_md`, build the "allowed" set from that run's
  `analyst_reports`/`rankings`/`baskets`, flag any extracted number that
  doesn't match within a small rounding tolerance. This cannot be a hard
  blocking assertion at 100% precision — legitimate rephrasing ("roughly
  15%" vs. `14.7`) will produce some false positives — so treat flagged
  numbers as input to the human review gate (§8.C), not an automatic
  failure.

**C. System-level:**
- **Shadow-mode comparison** whenever `config/factor_weights.yaml` is
  proposed to change (an ops/quant-owned edit — never a user-triggered
  action): reuses a sample of recent runs' already-persisted
  `analyst_reports` and `factor_panel` rows — no re-fetching, no LLM
  calls — and reruns only `compute_factor_scores` →
  `combine_scores(df, new_weights)` → `rank` → basket construction with
  the proposed weights (`scripts/shadow_compare.py`). Diffs old vs. new:
  tickers entered/left, rank deltas, composite score deltas. Kept
  ephemeral (a diff report, not a persisted table) unless there's a
  specific need for historical shadow-run tracking. This is only
  possible because weights are config-file data, diffable between two
  file versions, rather than a code-level constant that would make
  "compare old vs. new weights" mean redeploying between runs — and it
  stays entirely an internal/ops workflow, since there is no user-facing
  surface that touches weighting policy at all (§2.1).
- **Forward-looking performance tracking** (not a trailing-lookback
  metric): each run's basket gets its *forward* return tracked in
  `basket_performance` from its `requested_at` date onward, benchmarked
  against the theme's own mapped reference ETF (`sub_exposure_etf_map.yaml`)
  rather than a flat index or a fixed percentage target — this gives the
  existing `alpha` column real, theme-relative meaning. Explicitly a
  monitoring/feedback-loop signal (feeding the eventual learning-to-rank
  work in §11), not a per-run pass/fail gate: by the time forward return
  data exists for a given run, that run is long finished, so there's
  nothing to "fail" retroactively. A trailing-lookback return of a
  basket's *current* holdings was considered and rejected as an
  evaluation metric — it's partially circular (momentum is already a
  scoring factor, so trailing return partly reflects what the system was
  built to select for, not forward skill) and a single absolute
  threshold (e.g. a flat annual-return bar) isn't theme- or
  regime-agnostic. A hard numeric return bar anywhere in the system's own
  evaluation criteria also sits awkwardly next to the "not investment
  advice" disclaimer required in §9 — keep any return-based signal
  internal/monitoring-only, never surfaced as a claim to the End User.
- Human review gate: no theme's basket should be treated as
  client-facing output until at least one manual review pass, especially
  early on given free-tier data source limitations (§6), and specifically
  whenever the Report groundedness check above flags an unmatched number.

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
