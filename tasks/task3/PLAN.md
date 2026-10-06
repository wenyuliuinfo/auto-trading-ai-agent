# Task 3 — Implementation Plan (PLAN v2)

Companion to `SPEC.md` (v2), `TEST_PLAN.md`, `UI_DESIGN.md`,
`METHODOLOGY.md`, `BACKTEST_SKILL.md`. The previous version is kept in
`_archive/PLAN.v1.md`.

## 0. Amendment 1 (what changed and why)

The first implementation skipped the real work (per-rebalance regeneration,
retargeting, real benchmarks) and shipped placeholders that produced
plausible-looking but fabricated numbers. v2 changes how the work is
delivered:

1. **Contain first.** Disable the current backtest output before anything
   else (Step A).
2. **Tests first.** The merge-gate tests (SPEC §25) are written before the
   code and start red (Step 1).
3. **Real loop first, on a labeled stub store (M1).** The strategy control
   flow exists and is proven before any real data is wired in. This removes the
   temptation to fake the loop.
4. **Milestones with gates (M1 → M2 → M3).** Each ends with a gate; the next
   milestone does not start until the gate is green, and a mode is only
   enabled after its gate.
5. **Review checklist** for any code (human or agent) that claims to implement
   a step (§ "Review checklist").

**Hard constraints for every step:**

- No edits to the Screener, Analyst, Modeling, Trader, or Report agents or any
  other existing agent file. If a diff touches one, stop and redesign.
- No randomness, identifier-derived numbers, or placeholder returns outside
  `StubStore` and test fixtures.
- No step may describe its output as a "backtest" unless the relevant gate has
  passed.

## Step A — Containment (do this first, today)

1. Set `enabled: false` in `config/backtest.yaml` (or `modes.trailing.enabled`
   and `modes.full.enabled` both false) so no results are produced or shown.
2. Remove `simulate_full_history` from the backtest path (do not merely hide
   it). Remove or quarantine `simulate_from_closes` from `run_backtest`; keep
   it only if renamed and used for nothing but the holdings table math.
3. Hide or disable the Backtest section in the UI until M1 is complete, or show
   "Not available".
4. Add the disposition notes from `SPEC §26` to the PR description so reviewers
   know what is being replaced.

Exit: no endpoint returns fabricated or hindsight results.

## Step 0 — Verification spikes (no production code)

Resolve every **VERIFY** in `SPEC §22` and record answers there.

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

## Step 1 — Merge-gate tests first (red)

Create the tests in `SPEC §25` with fixtures, so they fail until the real code
exists:

- `test_regenerates_each_rebalance` (spies on `get_factor_panel`,
  `compute_factor_scores`, `construct_basket`).
- `test_rank_flip_changes_targets`, `test_trades_equal_deltas`,
  `test_accounting_identities`, `test_daily_equity_series`.
- `test_benchmark_independence`, `test_canary_no_lookahead`,
  `test_parity_scoring`.
- Static checks: `test_no_synthetic_data`, `test_no_llm_import`,
  `test_engine_purity`, `test_agents_untouched`.
- `test_mode_gating_and_config_alignment`, `test_status_honesty`,
  `test_stub_results_labeled_and_rejected`.

Also record golden outputs of the live functions on a small fixed panel for the
parity test. CI runs these on every commit; the milestone gate is "all of this
milestone's tests are green" (SPEC §25).

## Step 2 — Config and types

1. Add the v2 config keys (`modes.<mode>.enabled`, `data.allow_stub_results`;
   SPEC §17). Loader in `agents/backtest.py` reads `modes.<mode>`, validates,
   computes the hash. Remove every use of `selection_mode`. Read the disclaimer
   from config.
2. Extend `app/backtest/types.py`: `Rebalance`, `RebalanceResult`, `Trade`,
   `EquityPoint`, `SimulationResult`, `BacktestResult` (add `trades`, benchmark
   series, `costs_total`, `data_source`, `config_hash`, `code_version`,
   `data_version`, `methodology_version`), flag and error-code enums.
3. Config and type validation tests.

## Step 3 — Pure engine (replace `engine.py`)

1. `calendar.py`: `build_schedule(mode, cfg, run_date, trading_days)` per
   SPEC §4.2 (rebalance dates, signal dates, completed and in-progress
   periods).
2. `signals.py`: `etf_breadth`, `money_flow_ratio`.
3. `portfolio.py` and `simulate.py`: the delta-trading loop in SPEC §10, with
   costs, fractional or whole shares, delisting policy, missing-price skip,
   trade log, daily equity points.
4. `benchmarks.py`: same-start buy-and-hold with entry cost from benchmark
   prices only.
5. `metrics.py`: SPEC §12 (sample std, `null` for undefined metrics) and
   attribution (SPEC §13).
6. Delete `simulate_full_history` and the fixed-weight `simulate_from_closes`.
7. Unit tests (TEST_PLAN §1–§6) plus the engine gate tests from Step 1.

## Step 4 — Store interface and `StubStore`

1. `HistoricalStore` protocol (SPEC §7.1) in `historical_data.py`.
2. `app/integrations/historical_data_stub.py` (`StubStore`) per SPEC §7.3:
   seeded and deterministic; at least 60 tickers across 3+ sub-exposures;
   persistent but varying factor exposures so ranks change between dates;
   quarterly-varying ETF membership with late-launching ETFs; synthetic filed
   statements; independent QQQ and SPY series; `provenance()` reports
   `data_source: "stub"`.
3. Patched-fetcher factories that serve any store (price and fundamentals
   fetchers returning `PriceHistory` and `Fundamentals`).
4. Tests: determinism, no look-ahead in every accessor, ranks actually vary
   across dates.

## Step 5 — Persistence

1. Alembic migration: `backtest_runs` (with `data_source`),
   `backtest_rebalances`, `backtest_equity`, `backtest_trades`,
   `market_data_cache`, with cascades (SPEC §14).
2. `data/queries.py`: save and get functions; `get_current_holdings_view`
   (used by `build_current_holdings`); reject stub results unless
   `allow_stub_results`.
3. Verify Task 1's delete flow removes the new rows. Tests (TEST_PLAN §9).

## Step 6 — Backtest agent: the real loop

1. `as_of_context` (lock, patch, restore) and `score_rebalance` per the
   skill's reference implementation; `build_ranked_entries`.
2. Rewrite `run_backtest(run_id, mode)` as in SPEC §5.1: config snapshot,
   schedule, prefetch with progress, **loop over every rebalance** calling
   `score_rebalance` (own basket per date), `simulate`, `build_benchmarks`,
   metrics and attribution, `build_current_holdings`, assemble, persist,
   final status per I6.
3. Keep `build_current_holdings` from the old code (it correctly uses the
   live basket plus K-lines) with the corrected `mini_url`.
4. Error isolation per rebalance; empty and partial basket policies; widening
   retries.

## Gate G1 / Milestone M1 — real loop on the stub store

Exit criteria:

- All G1 tests in SPEC §25 are green.
- Running trailing and full modes on the stub store shows, in the stored
  result: 4 (or 5) and 20 rebalances each with its own `inputs_summary` and
  basket; at least two distinct baskets; trades and non-zero costs; a daily
  equity series; an independent QQQ series; `data_source: "stub"`.
- Results are not persisted or shown outside dev (`allow_stub_results: false`
  in production config).

Do not enable any mode in production at this point.

## Step 7 — Orchestration and API (can start after Step 5, finish at M1)

1. Celery task and `backtest` queue (concurrency 1); enqueue from the
   run-completion hook only when `auto_trigger_trailing` is true.
2. Endpoints, schemas, OpenAPI, exports; idempotent `POST`; mode gating (409
   when disabled); disabled state.
3. API fixtures for the frontend (including a stub-labeled example).
4. Tests (TEST_PLAN §10).

## Step 8 — Frontend (starts at M1 using stub fixtures; see `UI_DESIGN.md`)

1. Backtest section shell with all states, plus the "Synthetic data" banner
   (stub) and the "Interim universe" chip (M2).
2. Summary cards, equity curve with controls, rebalance timeline.
3. Current holdings table (reusing Task 3 components), contribution bars,
   trade blotter.
4. Export menu, print stylesheet, methodology popover, disclaimers.
5. Component tests with mock payloads (TEST_PLAN §11).

## Step 9 — `FmpStore` (Milestone M2: real prices and fundamentals)

1. Fetchers, cache, call counting and budget, rate limiting and backoff for
   every dataset in SPEC §7.2.
2. As-of views and patched-fetcher factories; point-in-time fundamentals that
   mirror the live growth definitions (from Step 0).
3. ETF membership from **today's** holdings, with the
   `universe_not_point_in_time` flag and `data_source: "fmp"`.
4. Tests on recorded fixtures: `test_fmp_store_point_in_time`,
   `test_interim_universe_flag`, split-handling cases (raw vs split-adjusted),
   cache hit, budget exceeded, 429 backoff.

## Gate G2 / Milestone M2

Exit criteria:

- G1 and G2 tests green (SPEC §25).
- Opt-in live smoke test passed once.
- **Manual recomputation:** pick one rebalance of one real run, recompute
  candidates, breadth, money flow, z-scores, composite, ranks, basket, and
  trades in a spreadsheet; they match the stored result.
- QQQ and strategy curves match a charting site for the same dates.
- Compliance has reviewed the wording (D10).

Then `modes.trailing.enabled` may be set to true (staging first). `full`
remains disabled; the Backtest section shows the interim-universe chip.

## Step 10 — Dated ETF holdings (Milestone M3)

1. Implement dated ETF holdings in `FmpStore` per Step 0 findings (FMP
   date-based holdings; N-PORT-based fallback with a 60-day lag).
2. Snapshot age and lag rules; ETFs not yet launched are excluded per date and
   flagged; remove the interim flag when the data is point-in-time.
3. Tests: `test_dated_etf_holdings`; breadth varies by date; thin-universe
   periods trigger `insufficient_universe_policy`.
4. Survivorship measurement: count candidates in historical holdings that have
   no price history, report it in the result flags.

## Gate G3 / Milestone M3

Exit criteria: G1–G3 tests green; `full` mode run on at least two real
themes; early-year periods reviewed (new ETFs, thin universes, hold-cash
quarters); survivorship counts reviewed; then `modes.full.enabled` may be
switched on.

## Step 11 — Infrastructure

Worker image and queue configuration, environment variables (FMP key reuse,
budgets, timeouts), resource limits, logging fields (`backtest_id`, `stage`,
`data_source`). Document the dedicated-queue requirement. CI runs the gate
tests and the static checks.

## Step 12 — Documentation

Add `BACKTEST_SKILL.md` beside the other skills with **Rules 15 and 16** from
`SPEC §26`; update `TEST_PLAN.md` (merge gates, criteria range A1–A24);
`ARCHITECTURE.md` (agent, tables, API, milestones, decision log); `CONTEXT.md`;
`CONVENTIONS.md`; README API table; data-provider notice. Compliance reviews
`METHODOLOGY.md` and UI copy.

## Step 13 — Verification

1. Run `pnpm lint`, `pnpm lint:api`, `pnpm test:api`,
   `pnpm --dir src/web test`, `pnpm check:structure`, `pnpm build`.
2. Run the gate tests for the current milestone and the opt-in live test.
3. Manual QA per TEST_PLAN §12 on three themes from real runs (trailing) and
   one theme (full).

## Step 14 — Rollout

1. Staging with `trailing.enabled: true`, `auto_trigger_trailing: false`;
   trigger manually on five real runs; review data coverage, flags, runtime,
   FMP call counts.
2. After G3: run `full` on two themes in staging; review.
3. Compliance sign-off.
4. Production: enable `auto_trigger_trailing`; watch queue depth, job
   duration, failure rate, and FMP usage for a week.

## Review checklist (apply to every PR and every coding-agent output)

Reject the change if any of these is true:

- [ ] Any `random`, `gauss`, `hash(`, or `ord(` used to produce values outside
      `StubStore` and test fixtures.
- [ ] `construct_basket` (or the scoring functions) is not called once per
      rebalance, or the same basket is applied to several dates.
- [ ] The live basket (or any "current" data) is used for a historical date.
- [ ] A benchmark value is derived from strategy values (or equals them).
- [ ] Words like "placeholder", "synthetic", "deterministic replay", or "for
      now" appear in non-stub code paths.
- [ ] The equity series has only rebalance-date points.
- [ ] Trades, costs, or turnover are missing or always 0.
- [ ] Status is `succeeded` while any rebalance failed, was empty, or used
      interim data without a flag.
- [ ] A mode is enabled before its gate has passed.
- [ ] Any file in the other agents' modules appears in the diff.
- [ ] The PR description lists which SPEC §25 tests cover the change.

## Handoff for a coding agent

Load: `BACKTEST_SKILL.md`, `SPEC.md` §3.1, §5, §9, §10, §25, §26, and the
current step of this plan. Instruct: "Implement only this step; run its gate
tests; do not stub or fake any part of the strategy; if something cannot be
implemented as specified, stop and report instead of substituting a
placeholder."

## Rollback

Set `enabled: false` (no jobs; endpoints return a disabled state) or revert
the deploy. The additive tables are harmless and can stay. The parent run is
never affected.

## Risks

| Risk | Mitigation |
|---|---|
| Placeholder code passes as complete again | Tests-first, merge gates, review checklist, static checks (A16), labeled stub store |
| Dated ETF holdings missing for many ETFs or years | Step 0 spike; N-PORT fallback; flags; `full` waits for M3 |
| Interim universe (today's ETF holdings) biases results | Flag and chip at M2; trailing only; disclosed in methodology |
| Survivorship (delisted names) | Count and flag unpriced candidates; disclose |
| Global patching causes cross-job interference | Lock, single-concurrency queue, hygiene tests, never patch in the API process |
| Private-function import breaks on a Modeling refactor | Parity tests fail loudly in CI |
| Backtest signals differ from live signals | `llm_factors_replaced` flag everywhere |
| FMP cost or rate limits | Cache-first, budget, backoff, shared cache |
| Adjusted vs raw price mix-ups distort P/E or dollar volume | Separate series per purpose; split-case tests |
| Small samples read as proof | `short_window` flag, copy, no significance claims |
| Long-running jobs block workers | Dedicated queue, timeouts, progress |
| Stub results leak into production | `allow_stub_results: false`, rejection at persistence, banner, test |
