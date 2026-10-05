# Task 3 — Backtest agent and Backtest section

Status: DRAFT for review. Items marked **VERIFY** depend on code, endpoints,
or plan limits that were not inspected when drafting; resolve them in PLAN
Step 0 and update this file. Open decisions are in §21.

Related files: `BACKTEST_SKILL.md` (hard rules), `METHODOLOGY.md`
(assumptions and limitations), `UI_DESIGN.md`, `PLAN.md`, `TEST_PLAN.md`,
`config/backtest.yaml`.

## 1. Goal and non-goals

**Goal.** For every run, replay the pipeline's deterministic strategy on
historical data, simulate a $10K portfolio that follows it, and show the
result next to the run's Basket, Rankings, and Report as a new **Backtest**
section: strategy summary, equity curve versus a Nasdaq index fund,
rebalance timeline, current holdings table, contribution bars, and trade
blotter.

**Non-goals.**

- No change to the Screener, Analyst, Modeling, Trader, or Report agents.
- No LLM in the backtest path (§3).
- No tuning of factor weights or screens from backtest results.
- No tax, financing, short-selling, or capacity modeling.
- No user-adjustable backtest parameters; the API accepts only `mode`.
- The "current holdings" table does not re-rank anything; it displays the
  run's live basket.

## 2. Owner decisions captured in this draft

| Topic | Decision |
|---|---|
| Thematic score | Number of the theme's mapped ETFs that hold the stock |
| Sentiment score | Money flow (buying volume minus selling volume), trailing 6 months |
| Test themes | The theme (its persisted `theme_config`) of each run |
| Test years | 2021 – 2025 (**full** mode) |
| Per-run simulation | The last four quarterly rebalances (**trailing** mode) |
| UI | Summary cards, equity curve, rebalance timeline, current holdings table, contribution bars, trade blotter, progress and failure states, controls, export |
| Agent constraint | Backtest agent only **imports** other agents' functions; no edits to other agents |

## 3. Constraints

1. **Import-only reuse** (BACKTEST_SKILL Rule 1).
2. **No LLM calls**; results are deterministic and reproducible.
3. **No look-ahead**: strictly as-of data, signal at prior close, execution
   at the rebalance-date close.
4. **Hypothetical performance** is labeled everywhere (BACKTEST_SKILL Rule 11).
5. The backtest never changes the parent run's status.

## 4. Strategy definition

### 4.1 Schedule

- **Rebalance dates:** the first trading day of January, April, July and
  October.
- **Signal date:** the last trading day before the rebalance date. All
  signals use data dated on or before it.
- **Execution:** at the **rebalance-date close**, trading to target weights
  (only the deltas are traded; costs apply to traded value).
- **Hold:** until the next rebalance execution.
- **Lookbacks:** the live system's native lookbacks are kept (see
  METHODOLOGY). "6 months" is the momentum and money-flow window; the factor
  panel also uses 252- and 504-day windows and year-over-year fundamentals,
  so data is fetched from two years before the first signal.

### 4.2 Modes

| Mode | Trigger | Period | Rebalances |
|---|---|---|---|
| `trailing` | Automatically after each run completes (flag), or `POST` | The four most recent **completed** holding periods ending at the run date, plus the in-progress period if it has at least `min_partial_hold_days` trading days | 4 (or 5 with the in-progress period) |
| `full` | On demand only (`POST`) | 2021-01-04 through 2025-12-31 | 20 |

A holding period is **completed** when the next rebalance's execution date is
on or before the run date and its close is available.

**Example (run date 2026-10-05):** rebalances 2025-10-01, 2026-01-02,
2026-04-01, 2026-07-01 form the four completed periods (the last ends at the
2026-10-01 close). The 2026-10-01 rebalance has only two trading days, below
the 10-day minimum, so the in-progress period is omitted and the curve ends
at 2026-10-01.

### 4.3 Capital and trading

- Initial cash $10,000 (config).
- Fractional shares by default (config; if false, floor shares and leave
  cash).
- Transaction cost: 10 bps of traded value per side (config).
- Cash earns nothing (config `cash_yield_annual: 0.0`).
- Dividends are included through total-return-adjusted prices.

## 5. Architecture

```
POST /runs/{id}/backtest ──► queue "backtest" (concurrency 1) ──► run_backtest_task
                                                                       │
                                  agents/backtest.py (orchestrator)    ▼
   config/backtest.yaml ─►  ┌───────────────────────────────────────────────┐
   run.theme_config ──────► │ 1. schedule (backtest/calendar.py)            │
                            │ 2. prefetch (integrations/historical_data.py) │
                            │ 3. per rebalance:                             │
                            │    as_of_context ─► screener.assemble_…       │
                            │                  ─► factor_panel.get_factor_… │
                            │                  ─► modeling._build_scoring_… │
                            │    substitute thematic, sentiment             │
                            │                  ─► modeling.compute/combine/rank
                            │                  ─► trader.construct_basket   │
                            │ 4. simulate (backtest/simulate.py, pure)      │
                            │ 5. benchmarks + metrics + attribution (pure)  │
                            │ 6. persist (data/queries.py)                  │
                            └───────────────────────────────────────────────┘
                                         │
                       GET /runs/{id}/backtest ◄── UI Backtest section
```

- **Trigger point:** the code that runs the graph (for example a Celery task)
  enqueues the backtest after the run succeeds. That orchestration code is not
  an agent, so it may change (**VERIFY** its location).
- **Isolation:** its own queue, status, progress, and error handling.
- **Dependencies on other tasks:** Task 3 supplies the K-line snapshot, mini
  chart, and chart components that the holdings table reuses. Task 2's
  liquidity and volatility factors, if merged, work unchanged because they are
  computed inside `get_factor_panel`/`_build_scoring_frame`. Task 1's delete
  flow must cascade to the new tables.

## 6. Reuse map (import-only)

| Reused function | Used for | Risk and mitigation |
|---|---|---|
| `screener.assemble_candidate_universe(hits, max_candidates)` | Merge, dedupe, cap the point-in-time ETF hits | It calls `search_sector("")` through `enrich_with_market_cap`; patch `screener.search_sector` inside `as_of_context` to return point-in-time rows. Sector-keyword hits are not reconstructed historically (METHODOLOGY). |
| `factor_panel.get_factor_panel(tickers)` | Raw factors (valuation, growth, quality, momentum, adv, market cap, beta, hist_vol, and any Task 2 columns) | Reads "now" data through `fetch_price_history`/`fetch_fundamentals`; patch those names in `factor_panel` inside `as_of_context`. Uses a thread pool, so patch globally under a lock. |
| `modeling._build_scoring_frame(panel, reports)` | Builds growth, quality, valuation, momentum, (liquidity, volatility) | Private function; parity test. Called with placeholder reports; `thematic` and `sentiment` columns are then overwritten. |
| `modeling.compute_factor_scores / combine_scores / rank` | Z-scores, composite, ranking | Pure. Weights are the run's persisted snapshot. |
| `trader.construct_basket(ranked_list, theme_config)` | Screens, diversification, sizing | Mutates its input (`weight`); pass deep copies. |
| `deepseek`/`*_node` functions | **Not used** | Rule 1 and 3. |

`build_ranked_entries` (new, in the Backtest agent) reproduces the dictionary
that `modeling_node` builds inline: `ticker`, `company_name`,
`gics_subindustry`, `sub_exposure`, `sub_exposure_tags`, `composite_score`
(`None` if NaN), `rank`, `market_cap`, `avg_dollar_volume` (from `adv`),
`thematic_relevance_score`, `sentiment`, `factor_contributions`, `caveats`
(`[]`). Candidate rows are sorted by ticker before scoring so ties break
deterministically (Modeling Rule 7).

## 7. As-of data layer (`app/integrations/historical_data.py`)

`HistoricalStore` fetches from FMP, caches, and exposes as-of views. Every
accessor requires `as_of` and never returns later data.

| Dataset | Source (**VERIFY** endpoints and plan depth) | Point-in-time rule | Used for |
|---|---|---|---|
| Split-adjusted daily OHLCV | FMP historical prices, split-adjusted | `date <= as_of` | Factor panel via patched `fetch_price_history`; money flow |
| Raw (unadjusted) close | FMP historical prices, unadjusted | `date <= as_of` | `Fundamentals.price` so P/E matches as-reported EPS |
| Total-return-adjusted close | FMP historical prices, dividend- and split-adjusted | `date <= execution day` | Simulation P&L and benchmarks only |
| Quarterly income, balance sheet, cash flow | FMP statements with `filingDate` and `acceptedDate` | `filingDate <= as_of` (use `acceptedDate` when it is later than the filing date) | Patched `fetch_fundamentals` |
| Historical market cap | FMP historical market capitalization | `date <= as_of` | `Fundamentals.market_cap`; universe capping |
| ETF holdings snapshots | FMP ETF holdings with a `date` parameter (documented in FMP FAQ; coverage for thematic ETFs **VERIFY**); N-PORT-based fund disclosures as fallback (public about 60 days after quarter end) | Latest snapshot with `snapshot_date + lag <= as_of` and age `<= etf_snapshot_max_age_days` | Universe and `etf_breadth` |
| Benchmark prices (QQQ, SPY) | FMP historical, total-return-adjusted | Same as simulation | Benchmarks |

### 7.1 Patched fetchers

- `fetch_price_history(ticker, lookback_days=504)` returns
  `PriceHistory(ticker, close, volume, source="backtest")` from the
  split-adjusted series, sliced to `<= as_of`, last `lookback_days` rows.
- `fetch_fundamentals(ticker)` returns a `Fundamentals` object:
  - `price` = raw close at `as_of`
  - `market_cap` = historical market cap at `as_of`
  - TTM fields = sum of the latest four quarters with `filingDate <= as_of`
  - `total_debt`, `cash`, `shareholders_equity` = latest filed balance sheet
  - `revenue_growth_yoy`, `eps_growth_yoy` = **defined exactly as in
    `integrations/fmp.py::fetch_fmp_fundamentals`** (**VERIFY**; mirror, do
    not reinvent)
  - `source = "backtest_pit"`
  - Missing quarters yield `None` fields, never zeros.
- Unknown tickers raise; the factor panel already converts that to a NaN row.

### 7.2 Cache, budget, and rate limits

- Cache key: `(dataset, ticker or etf, as_of_or_range, fetch_version)`.
  Default backend is a `market_data_cache` table (D2).
- Prefetch phase: one full-history fetch per ticker per dataset, so every
  rebalance is served from cache.
- Budget: `max_fmp_calls_per_backtest` (config). On exceeding it, stop with
  `DATA_BUDGET_EXCEEDED` and return a `partial` result for the rebalances
  already scored.
- Rate limiting: `fmp_requests_per_minute` (config), with backoff on 429.
- Rough size: about five calls per candidate ticker plus one holdings call
  per ETF per rebalance; shared tickers across themes are fetched once.

## 8. Signals

### 8.1 Thematic score: ETF breadth

`etf_breadth(ticker) = number of distinct ETFs, among those mapped to the
theme's sub-exposures in config/sub_exposure_etf_map.yaml, whose holdings
snapshot at the signal date contains the ticker.`

- An ETF counts once even if mapped to several sub-exposures.
- ETFs without a valid snapshot at that date (not yet launched, or snapshot
  too old) are excluded and recorded in the rebalance flags.
- Tickers are normalized (upper case); cash, futures, and non-equity lines
  are dropped.
- The value is used as-is; Modeling z-scores it cross-sectionally.

### 8.2 Sentiment score: money-flow ratio

Using split-adjusted daily OHLCV over the 126 trading days ending at the
signal date:

```
clv_t   = ((close_t - low_t) - (high_t - close_t)) / (high_t - low_t)   # 0 if high == low
flow_t  = clv_t * volume_t                    # + buying pressure, - selling pressure
money_flow_ratio = sum(flow_t) / sum(volume_t)        # in [-1, 1]
```

This approximates "buying volume minus selling volume" from daily bars,
normalized by total volume so company size does not dominate. True
buy/sell-initiated volume needs trade-level data (see METHODOLOGY). Require at
least `money_flow_min_obs` valid days (default 100), else `NaN`.

Alternative definition (D8): signed volume by close-to-close direction.

## 9. Scoring and selection per rebalance

1. Build the point-in-time hits `{sub_exposure: [ticker rows]}` from ETF
   snapshots (each row: `ticker`, `company_name`, `gics_subindustry`,
   `market_cap` at the signal date).
2. Inside `as_of_context`: `assemble_candidate_universe(hits, max_candidates)`.
3. If fewer than `min_candidates_for_rebalance` candidates: flag
   `insufficient_universe` and apply `insufficient_universe_policy`
   (default `hold_cash`).
4. `get_factor_panel(sorted tickers)` inside `as_of_context`.
5. `_build_scoring_frame` with placeholder reports, then overwrite `thematic`
   and `sentiment` with the substitute signals.
6. `compute_factor_scores`, `combine_scores`, `rank` using the run's
   `theme_config["factor_weights"]`. Fail fast if a weight key has no matching
   column.
7. `build_ranked_entries`, then `construct_basket(deepcopy(entries),
   theme_config)` using the run's `screens`, `weighting_scheme`, and
   `max_per_sub_industry`.
8. If the basket has fewer than 5 names, widen the universe by calling
   `assemble_candidate_universe` again with `max_candidates + 100 *
   retry` up to `max_widen_retries` (default 2; **VERIFY** against the
   live graph's `check_basket_complete`). If still empty: hold cash and flag
   `no_basket`. If 1–4 names: invest and flag `partial_basket`.
9. Record inputs summary (counts, flags, top-ranked names, substitute-signal
   values) for the rebalance row.

## 10. Simulation and accounting (`app/backtest/`)

- State: `cash`, `positions {ticker: shares}`.
- At each execution date: compute target dollars from portfolio value ×
  weight, trade deltas at the total-return-adjusted close, charge
  `cost_bps × |trade value|`, record each trade with a reason
  (`entry`, `exit`, `increase`, `decrease`).
- Between rebalances: daily mark-to-market, no trading.
- Missing price at execution: skip the buy, flag `missing_prices`, leave the
  weight in cash.
- Price series ending during a hold (delisting): follow
  `delisting_policy` (default `last_price_then_cash`) and flag
  `delisted_holding`.
- Identities (tested): value = cash + Σ shares × price at every date; Σ ticker
  P&L − costs = total P&L.

## 11. Benchmarks

Primary: **QQQ** total return (Nasdaq-100 fund). Optional (config-enabled):
SPY, equal-weight of the theme's mapped ETFs available at each date, and
equal-weight of the candidate universe at each rebalance. Each benchmark
starts on the same date with the same cash and the same one-time entry cost.
Benchmarks and strategy use the same date axis.

## 12. Metrics

Computed for the strategy and each benchmark from daily values (net of
costs): total return, final value of $10K, CAGR (annualized only if the period
is at least one year), annualized volatility, Sharpe (risk-free per config,
default 0), max drawdown (and dates), beta and alpha versus the primary
benchmark (daily regression), tracking error, information ratio, quarterly
hit rate (periods beating the benchmark), turnover (annualized sum of buys
divided by average value), total costs paid. Short-window warning when fewer
than 8 rebalances.

## 13. Attribution

Per ticker: P&L = Σ over holding periods of `shares × (exit price − entry
price)` (including partial-period exits), contribution = P&L / initial cash,
periods held. A separate "costs" item. The list plus costs sums to total P&L.

## 14. Persistence

Additive migrations; all child tables cascade from `backtest_runs`, which
cascades from runs (and from theme deletion, per Task 1).

| Table | Key columns |
|---|---|
| `backtest_runs` | `id`, `run_id`, `mode`, `status`, `progress` (JSON), `config_hash`, `config_json`, `methodology_version`, `code_version`, `data_version`, `period_start`, `period_end`, `summary` (JSON), `attribution` (JSON), `flags` (JSON), `error_code`, `error_message`, `created_at`, `started_at`, `finished_at` |
| `backtest_rebalances` | `backtest_id`, `idx`, `signal_date`, `exec_date`, `hold_end_date`, `candidate_count`, `eligible_count`, `basket` (JSON), `flags` (JSON), `period_return`, `benchmark_returns` (JSON), `inputs_summary` (JSON) |
| `backtest_equity` | `backtest_id`, `series_name`, `points` (JSONB `[{date, value}]`) |
| `backtest_trades` | `backtest_id`, `seq`, `date`, `ticker`, `side`, `shares`, `price`, `value`, `cost`, `reason` |
| `market_data_cache` | per §7.2 |

A new backtest for the same `(run_id, mode)` creates a new row; the API returns
the latest unless `backtest_id` is given.

## 15. API (additive; align with existing route conventions, **VERIFY**)

| Endpoint | Purpose |
|---|---|
| `POST /runs/{run_id}/backtest` body `{mode}` | Enqueue; `202` with `backtest_id`; idempotent while one is queued or running for the same mode |
| `GET /runs/{run_id}/backtest?mode=trailing\|full` | Status, progress, and the result (below) |
| `GET /runs/{run_id}/backtest/trades` | Paginated blotter |
| `GET /runs/{run_id}/backtest/export?format=csv\|json&part=equity\|trades\|rebalances` | Attachment |

Result shape (abridged):

```json
{
  "backtest_id": "...", "run_id": "...", "mode": "trailing",
  "status": "succeeded",
  "progress": {"stage": "finalizing", "completed": 4, "total": 4},
  "methodology_version": 1, "config_hash": "…", "code_version": "…", "data_version": "…",
  "period": {"start": "2025-10-01", "end": "2026-10-01"},
  "initial_cash": 10000,
  "summary": {"strategy": {"total_return": 0.0, "final_value": 0.0, "max_drawdown": 0.0,
                           "sharpe": 0.0, "alpha": 0.0, "beta": 0.0, "hit_rate": 0.0,
                           "turnover": 0.0, "costs_paid": 0.0},
              "benchmarks": {"QQQ": {"total_return": 0.0}}},
  "series": {"strategy": [{"date": "…", "value": 0.0}], "QQQ": []},
  "rebalances": [{"idx": 0, "signal_date": "…", "exec_date": "…", "basket": [],
                  "period_return": 0.0, "benchmark_returns": {"QQQ": 0.0}, "flags": []}],
  "attribution": [{"ticker": "…", "company_name": "…", "pnl": 0.0,
                   "contribution_pct": 0.0, "periods_held": 0}],
  "costs_total": 0.0,
  "current_holdings": [{"ticker": "…", "company_name": "…", "weight": 0.0,
                        "return_6m": 0.0, "price": 0.0, "pe_ratio": 0.0,
                        "market_cap": 0.0, "kline": {"status": "ok", "mini_url": "…"}}],
  "flags": ["short_window", "survivorship_risk", "llm_factors_replaced"],
  "disclaimer": "…"
}
```

`current_holdings` is assembled at read time from existing data: the run's
basket (`get_basket_with_scores`), raw factor rows (`pe_ratio`, `market_cap`,
`momentum_6m`), and Task 3's K-line snapshot (price = last close; 6-month
return as in Task 3). P/E shows `null` when missing and the UI displays "n/m"
for non-positive values.

## 16. Job orchestration

- Queue `backtest`, worker concurrency 1 per process (global patch safety).
- Stages: `fetching_data`, `building_universe`, `scoring`, `simulating`,
  `finalizing`; progress `{stage, completed, total}`.
- Timeouts: per job (`job_timeout_s`), per FMP request (`fmp_timeout_s`).
- Retries: transient fetch errors are retried inside the data layer; a failed
  job can be re-queued by `POST`.
- Status: `succeeded`, `partial` (any rebalance failed or was empty, or data
  budget hit), `failed` (no rebalance scored).
- Auto-trigger of `trailing` after a run succeeds is controlled by
  `auto_trigger_trailing` (config). `full` is never automatic.
- The parent run's status and the run API are unaffected by backtest state.

## 17. Configuration

`config/backtest.yaml` (see the file). Read once at job start; the snapshot and
SHA-256 hash are stored with the result. Not accepted from API input.

## 18. Security and compliance

- Hypothetical-performance wording and disclaimer come from the payload; get
  compliance review of `METHODOLOGY.md` and UI copy before client use.
- Data-provider terms: confirm FMP plan permits the stored/derived use and any
  display of derived data.
- Inputs are tickers from FMP and the run's own state; validate with the
  existing symbol pattern before building cache keys or URLs.
- No user-supplied paths or parameters reach the data layer.
- Exports neutralize spreadsheet formula prefixes in text fields.

## 19. Backward compatibility and rollback

- No changes to existing tables or agent code; new tables and endpoints only.
- Legacy runs have no backtest; the UI shows "Run backtest".
- Rollback: set `enabled: false` in config (endpoints return a disabled
  state, no jobs run) or revert the deploy; new tables are harmless.

## 20. Acceptance criteria

- **A1.** No file under `app/agents/{screener,analyst,modeling,trader,report}.py`
  or other agents is modified.
- **A2.** The structure test passes: no LLM client import in the backtest
  path; `app/backtest/**` imports no I/O layers and no clock calls.
- **A3.** Look-ahead canary: poisoning data after `as_of` changes nothing.
- **A4.** Parity: with the same panel and substitute columns, backtest scoring
  equals the live functions' output.
- **A5.** Trailing mode on a fixture run yields 4 completed periods (plus the
  in-progress one only when eligible), with correct signal and execution
  dates.
- **A6.** Full mode on a fixture covers 2021-01-04 to 2025-12-31 with 20
  rebalances.
- **A7.** Accounting identities hold (value and attribution).
- **A8.** Benchmarks start on the same date with the same cash and entry
  cost.
- **A9.** An empty or partial basket is handled per policy and flagged; the
  job finishes.
- **A10.** A data failure in one rebalance yields `partial`; the parent run is
  unaffected.
- **A11.** Results are immutable and carry config hash, methodology version,
  code version, and data version.
- **A12.** The Backtest section renders all nine UI elements (UI_DESIGN) with
  loading, running, partial, failed, and disabled states.
- **A13.** Disclaimer and hypothetical labeling appear in the API payload,
  UI, and exports.
- **A14.** Docs are updated (§24) and the full check suite passes.

## 21. Open decisions (recommended default in bold)

1. **D1** `full` mode: **on demand only, per run** (not automatic).
2. **D2** Cache backend: **DB table `market_data_cache`** vs Parquet files.
3. **D3** Risk-free rate for Sharpe: **0** vs a T-bill series.
4. **D4** Execution price: **rebalance-date close** vs next open.
5. **D5** Delisting: **last price, then cash**.
6. **D6** ETF holdings source: **FMP date-based holdings**, with N-PORT-based
   disclosures as fallback (60-day lag).
7. **D7** Widening retries in the backtest: **mirror the live graph** (max 2).
8. **D8** Money-flow formula: **CLV-weighted volume**, vs up/down volume.
9. **D9** Benchmarks shown by default: **QQQ plus SPY, theme-ETF and universe
   baselines available in the selector**.
10. **D10** Compliance wording for hypothetical performance.
11. **D11** `gics_subindustry` uses the current classification (small
    look-ahead, accepted and disclosed).
12. **D12** Insufficient-universe policy: **hold cash** vs carry previous
    basket.

## 22. VERIFY list

1. `integrations/etf_holdings.py::search_holdings` output shape (does it
   expose which ETF each hit came from? needed to build `etf_membership`).
2. `integrations/fmp.py`: price endpoint and adjustment used by
   `fetch_fmp_prices`; exact definitions of `revenue_growth_yoy` and
   `eps_growth_yoy`.
3. FMP endpoint names, parameters, and history depth for: unadjusted,
   split-adjusted, and total-return-adjusted prices; quarterly statements;
   historical market cap; dated ETF holdings; plan call limits.
4. Whether delisted tickers return price history (survivorship).
5. `check:structure` layer rules for `app/backtest/` and for one agent
   importing another.
6. Live graph retry limit (`check_basket_complete`) and `retry_count`
   semantics.
7. Location of the run-execution task (for the auto-trigger) and existing
   queue/worker configuration.
8. Existing API conventions (auth/session scoping, pagination, polling).
9. Task 1 delete flow cascade coverage; Task 3 snapshot availability.
10. `reference_universe.search_sector("")` row shape for the patched version.

## 23. Files touched

| Area | Files |
|---|---|
| New engine | `app/backtest/{calendar,signals,portfolio,simulate,benchmarks,metrics,types}.py` |
| New agent | `app/agents/backtest.py` |
| New integration | `app/integrations/historical_data.py` |
| Config | `config/backtest.yaml` |
| Data | `app/data/queries.py`, models, migration |
| Orchestration | Run-completion hook, Celery task, `backtest` queue, worker config |
| API | Routes, schemas, OpenAPI, export |
| Frontend | Backtest section (see UI_DESIGN) |
| Infra | Worker image/queue settings, settings in `app/config.py`, `.env.example` |
| Structure checks | Layer config for `app/backtest/`; LLM-import guard |

## 24. Documentation updates

`BACKTEST_SKILL.md` (new, beside the other skills); `ARCHITECTURE.md` (new
agent/job, tables, API, decision log); `CONTEXT.md` (rebalance, signal date,
point-in-time, look-ahead, hypothetical performance); `CONVENTIONS.md` (layer
rules); README API table; third-party/data-provider notice.
