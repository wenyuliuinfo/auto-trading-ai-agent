# Task 3 — Implementation Plan

Companion to `SPEC.md`, `TEST_PLAN.md`, `UI_DESIGN.md`, `METHODOLOGY.md`,
`BACKTEST_SKILL.md`. Each step is one reviewable commit or small PR. Steps
3–5 can run in parallel after Step 2; the frontend (Step 10) can start
against API fixtures once Step 8 defines the contract.

**Hard constraint for every step:** no edits to the Screener, Analyst,
Modeling, Trader, or Report agents or any other existing agent file. If a
diff touches one, stop and redesign (BACKTEST_SKILL Rule 1).

## Step 0 — Verification spikes (no production code)

Resolve every **VERIFY** in `SPEC.md §22` and record answers there.

### §22.1 ETF hit source

`integrations/etf_holdings.py::search_holdings()` returns a list of dicts
shaped as `{"ticker", "weight", "source"}`. `source` is
`f"etf_holdings:{etf}"`, so each hit already identifies its originating ETF.
Backtest can derive `etf_membership` from that field without changing the
live Screener.

### §22.2 Current FMP price/fundamental definitions

`fmp.py::fetch_fmp_prices()` uses
`GET /stable/historical-price-eod/light` with `symbol`, `from`, `to`, and
`apikey`. It returns `price` and `volume`; the current client does not
request an adjustment variant and does not distinguish raw, split-adjusted,
or total-return series.

`fmp.py::fetch_fmp_fundamentals()` defines:

```text
revenue_growth_yoy = current_revenue / previous_revenue - 1
eps_growth_yoy     = current_eps_diluted_or_eps / previous_eps_diluted_or_eps - 1
```

using the latest two annual income statements. Either field is `None` when
the numerator or prior denominator is missing or zero.

### §22.3 FMP endpoint and depth verification

Resolvable from the repo: the current code only uses the stable endpoints
`/quote`, `/ratios-ttm`, `/key-metrics-ttm`, `/income-statement`,
`/balance-sheet-statement`, `/cash-flow-statement`, and
`/historical-price-eod/light`.

Still requires a live API probe with the actual FMP plan key (cannot be
resolved from source alone):

- exact endpoints/parameters for unadjusted, split-adjusted, and
  total-return-adjusted historical prices;
- quarterly statement coverage and `filingDate`/`acceptedDate` behavior;
- historical market-cap endpoint and depth;
- dated ETF-holdings coverage for the mapped thematic ETFs across
  2021–2025;
- whether delisted tickers still return historical prices;
- plan call limits.

### §22.4 Delisted ticker behavior

Cannot be determined from source. It must be tested against the live FMP
plan before accepting full mode. The fallback remains: count and flag
unpriced candidates as `survivorship_risk`.

### §22.5 Structure rules

Current `tests/test_structure.py` enforces only:

- `api/` never imports `integrations/` or `evaluation/`;
- `agents/` never imports `api/` or `evaluation/`;
- `worker.py` imports the graph boundary.

It does not yet constrain `app/backtest/**`, and it does not prohibit one
agent from importing another. Task 3 must add its own structural guards:
no LLM client in `app/backtest/**` or `agents/backtest.py`, no I/O layers in
`app/backtest/**`, and no clock calls in the engine.

### §22.6 Live graph retry limit

`graph.py::check_basket_complete()` routes back to `screener_retry` only
when the basket has fewer than `MIN_BASKET_SIZE` and `retry_count < 2`.
`screener_node` increments `retry_count`. So the live pipeline permits at
most two widen retries; the backtest `max_widen_retries` default should be
`2`.

### §22.7 Run task, queue, and auto-trigger location

Run execution lives in `app/worker.py::run_pipeline_task`, which calls
`execute_run(run_id)`. Celery currently uses the default `celery` queue,
Redis broker/result backend, and `celery-worker` runs with
`--concurrency=4`. There is no dedicated backtest queue yet. The natural
auto-trigger point is after `execute_run` succeeds in `run_pipeline_task`
(or a small helper at the worker boundary), not inside an agent.

### §22.8 API conventions

Existing `api/runs.py` uses plain `/runs/{run_id}` paths, returns `404` for
missing/not-ready resources, reports `queued/running/complete/failed`
status plus a `progress` dict, and exposes SSE under `/events`. Auth/session
scoping is documented in `ARCHITECTURE.md` but not implemented in this
prototype, and current read endpoints do not implement pagination. Backtest
endpoints should mirror the same status/progress polling and 404 style;
pagination must be introduced for the trade blotter.

### §22.9 Task 1 cascade and Task 3 snapshot availability

Task 1 theme deletion is implemented via `delete_theme()`; all child tables
use `ON DELETE CASCADE`, and `run_klines` has `run_id` FK cascade. Therefore
deleting a theme cascades to runs and their `run_klines` rows. Task 3's
K-line snapshot is already available through `get_klines()` and the K-line
API, so the backtest `current_holdings` view can reuse it.

### §22.10 `reference_universe.search_sector("")` row shape

`search_sector("")` returns records from `reference_universe_seed.csv` (or
the configured live CSV) with columns:

```text
ticker, company_name, gics_subindustry, market_cap, avg_dollar_volume
```

and adds `source = "index:russell3000"`. The backtest's patched point-in-time
version must return the same shape plus any historical fields it needs.

Exit: `SPEC.md` status changes from DRAFT; decisions D1–D12 settled; if dated
ETF holdings are unavailable for most mapped ETFs, decide before continuing
(fallback: N-PORT disclosures with a 60-day lag, or restrict `full` mode).

## Step 1 — Baseline and guardrails

1. Add the structure tests first (they should fail until code exists):
   no LLM client import in `app/backtest/**` or `agents/backtest.py`;
   `app/backtest/**` imports no `integrations/`, `data/`, `agents/`; no clock
   calls in the engine.
2. Record golden outputs of the live functions on a small fixed panel
   (`compute_factor_scores`, `combine_scores`, `rank`, `construct_basket`) for
   the parity tests.

## Step 2 — Config and types

1. Add `config/backtest.yaml` and a loader in `agents/backtest.py` (reads the
   file once, validates, computes the hash).
2. `app/backtest/types.py` dataclasses: `Rebalance`, `RebalanceResult`,
   `Trade`, `SimulationResult`, `BacktestConfig`, flags and error-code enums.
3. Config validation tests.

## Step 3 — Pure engine: calendar and signals

1. `calendar.py`: trading-day helpers, rebalance schedule for `trailing` and
   `full` modes, completed-period logic, partial-period rule.
2. `signals.py`: `etf_breadth`, `money_flow_ratio` (D8), with `NaN`
   handling.
3. Unit tests (TEST_PLAN §1–§2).

## Step 4 — Pure engine: portfolio, simulation, benchmarks, metrics

1. `portfolio.py` and `simulate.py`: delta trading, costs, fractional or
   whole shares, delisting policy, missing-price skip, trade log.
2. `benchmarks.py`: same-start buy-and-hold curves with entry cost.
3. `metrics.py` and attribution (identity-preserving).
4. Unit tests (TEST_PLAN §3–§6).

## Step 5 — Historical data layer (`app/integrations/historical_data.py`)

1. `HistoricalStore` with FMP fetchers for each dataset in `SPEC §7`, cache
   table access through `data/queries.py`, call counting and budget, rate
   limiting and backoff.
2. As-of views and the two patched-fetcher factories
   (`make_price_fetcher`, `make_fundamentals_fetcher`), mirroring the live
   growth definitions from Step 0.
3. Stub store (deterministic synthetic history) used when
   `settings.stub_agents` is true, so CI runs offline.
4. Tests with recorded fixtures (TEST_PLAN §7).

## Step 6 — Persistence

1. Alembic migration: `backtest_runs`, `backtest_rebalances`,
   `backtest_equity`, `backtest_trades`, `market_data_cache` with cascades.
2. `data/queries.py`: save and get functions; `get_current_holdings_view`.
3. Verify Task 1's delete flow removes the new rows. Tests (TEST_PLAN §9).

## Step 7 — Backtest agent (`app/agents/backtest.py`)

1. `as_of_context` (lock, patch, restore) and `score_rebalance` per the
   skill's reference implementation; `build_ranked_entries`.
2. `run_backtest(run_id, mode)`: load run and `theme_config`, schedule,
   prefetch with progress, loop rebalances (error isolation), simulate,
   benchmarks, metrics, attribution, persist, set final status.
3. Parity and canary tests (TEST_PLAN §8).

## Step 8 — Orchestration and API

1. Celery task and `backtest` queue (concurrency 1); enqueue from the
   run-completion hook when `auto_trigger_trailing` is true.
2. Endpoints, schemas, OpenAPI, exports; idempotent `POST`; disabled state.
3. API fixtures for the frontend. Tests (TEST_PLAN §10).

## Step 9 — Infrastructure

Worker image and queue configuration, environment variables
(`FMP` key reuse, budgets, timeouts), resource limits, logging fields
(`backtest_id`, `stage`). Document the dedicated-queue requirement.

## Step 10 — Frontend (see `UI_DESIGN.md`)

1. Backtest section shell with states (not run, queued, running, partial,
   failed, disabled).
2. Summary cards; equity curve with controls; rebalance timeline.
3. Current holdings table (reusing Task 3 components); contribution bars;
   trade blotter.
4. Export menu and print stylesheet; methodology popover and disclaimers.
5. Component tests with mock payloads (TEST_PLAN §11).

## Step 11 — Documentation

Add `BACKTEST_SKILL.md` beside the other skills; update `ARCHITECTURE.md`
(agent, tables, API, decision log), `CONTEXT.md`, `CONVENTIONS.md`, README
API table, and the data-provider notice. Have compliance review
`METHODOLOGY.md` and the UI copy.

## Step 12 — Verification

1. Run `pnpm lint`, `pnpm lint:api`, `pnpm test:api`,
   `pnpm --dir src/web test`, `pnpm check:structure`, `pnpm build`.
2. Run the opt-in live smoke test (TEST_PLAN §13) once.
3. Run the manual QA in TEST_PLAN §12: one trailing run on 3 themes from real
   runs and one full run on 1 theme; compare to a spreadsheet recomputation of
   one rebalance by hand.

## Step 13 — Rollout

1. Deploy with `enabled: true`, `auto_trigger_trailing: false` to staging;
   trigger manually on 5 real runs; review data coverage, flags, runtime, and
   FMP call counts.
2. Run `full` mode on 2 themes; review survivorship counts and
   insufficient-universe periods (new ETFs make early years sparse).
3. Compliance sign-off on wording (D10).
4. Production: enable `auto_trigger_trailing`; watch queue depth, job
   duration, failure rate, and FMP usage for a week.

## Rollback

Set `enabled: false` (no jobs; endpoints return a disabled state) or revert
the deploy. The additive tables are harmless and can stay. The parent run is
never affected.

## Risks

| Risk | Mitigation |
|---|---|
| Dated ETF holdings missing for many ETFs or years | Step 0 spike; N-PORT fallback; flags; shorter `full` range |
| Survivorship (delisted names, today's ETF constituents) | Flag and count unpriced candidates; disclose; METHODOLOGY |
| Global patching causes cross-job interference | Lock, single-concurrency queue, hygiene tests, no patching in API process |
| Private-function import breaks on a Modeling refactor | Parity tests in CI fail loudly |
| Backtest signals differ from live signals | Disclosed everywhere (`llm_factors_replaced` flag) |
| FMP cost or rate limits | Cache-first, budget, backoff, shared cache across runs |
| Adjusted vs raw price mix-ups distort P/E or dollar volume | Separate series per purpose (SPEC §7); tests on split cases |
| Small samples read as proof | Short-window flag, copy, no significance claims |
| Long-running job blocks workers | Dedicated queue, timeouts, progress |
