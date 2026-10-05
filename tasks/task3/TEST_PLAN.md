# Task 3 — Test Plan

Companion to `SPEC.md` (acceptance criteria A1–A14), `PLAN.md`,
`BACKTEST_SKILL.md`. Unit and integration tests are offline and
deterministic: use recorded FMP fixtures (PLAN Step 0.3), the stub store, and
synthetic price paths with known answers. Live-network tests are opt-in (§13).

## 1. Calendar and schedule (`backtest/calendar.py`)

| # | Case | Expected |
|---|---|---|
| 1.1 | Rebalance dates for 2024 | First trading day of Jan, Apr, Jul, Oct (holiday and weekend aware) |
| 1.2 | 2021-01 | First rebalance is 2021-01-04 |
| 1.3 | Signal date | Last trading day strictly before the rebalance date |
| 1.4 | Full mode | 20 rebalances from 2021-01-04; last period ends 2025-12-31 (A6) |
| 1.5 | Trailing, run date 2026-10-05 | Four completed periods starting 2025-10-01; 2026-10-01 rebalance (2 trading days old) omitted as in-progress (A5) |
| 1.6 | Trailing, run date 2026-10-20 | In-progress period included (13 trading days, above the minimum) and flagged |
| 1.7 | Run date before a period's close is available | Period treated as not completed |
| 1.8 | Run date on a rebalance date | Boundary handled, no off-by-one |
| 1.9 | Determinism | No clock reads; same inputs, same schedule |

## 2. Signals (`backtest/signals.py`)

| # | Case | Expected |
|---|---|---|
| 2.1 | `etf_breadth`: stock held by 3 of 5 snapshot ETFs | 3 |
| 2.2 | Same ETF mapped to two sub-exposures | Counted once |
| 2.3 | ETF with no valid snapshot at the date | Excluded; flag recorded |
| 2.4 | Ticker case and cash/futures lines | Normalized; non-equity lines dropped |
| 2.5 | Stock held by no ETF | 0 |
| 2.6 | `money_flow_ratio` with close at high every day | +1.0 |
| 2.7 | Close at low every day | −1.0 |
| 2.8 | `high == low` day | Contribution 0, no division error |
| 2.9 | Hand-computed 5-day example | Matches `sum(clv*vol)/sum(vol)` |
| 2.10 | Fewer than `money_flow_min_obs` valid days | `NaN` |
| 2.11 | Zero total volume | `NaN` |
| 2.12 | Scale invariance | Multiplying all volumes by 1000 leaves the ratio unchanged |
| 2.13 | Result range | Always within [−1, 1] |

## 3. Portfolio and costs (`backtest/portfolio.py`)

| # | Case | Expected |
|---|---|---|
| 3.1 | First rebalance, $10,000, 4 equal weights, 10 bps | Positions at 25% each less costs; cash residual correct |
| 3.2 | Fractional shares off | Floor shares; leftover cash tracked |
| 3.3 | Retained name with new weight | Only the delta is traded; cost on `|delta|` |
| 3.4 | Exited name | Fully sold; trade reason `exit` |
| 3.5 | Costs | Equal `bps/10000 * traded value` per trade; summed total matches |
| 3.6 | Missing price at execution | Buy skipped, weight stays in cash, `missing_prices` flag |
| 3.7 | Empty basket | 100% cash (all positions sold) |
| 3.8 | Zero-price or negative-price input | Rejected with a clear error |

## 4. Simulation and accounting (`backtest/simulate.py`)

| # | Case | Expected |
|---|---|---|
| 4.1 | One stock rising 10% in one period, no costs | Value = 10,000 × 1.10 |
| 4.2 | Value identity at every date | `value == cash + sum(shares * price)` (A7) |
| 4.3 | Attribution identity | `sum(ticker pnl) - costs == final - initial` (A7) |
| 4.4 | Two periods, changing baskets | Equity continuous across the rebalance (no jump except costs) |
| 4.5 | Delisting mid-hold | Last price used, then cash; `delisted_holding` flag |
| 4.6 | Price gap longer than `max_price_gap_days` | No silent forward-fill beyond the limit; flag |
| 4.7 | Weekend/holiday dates | No equity points on non-trading days |
| 4.8 | Hold-cash period | Equity flat (cash yield 0) |
| 4.9 | Determinism | Identical outputs for identical inputs |
| 4.10 | Turnover | Matches hand calculation for a two-rebalance example |

## 5. Benchmarks (`backtest/benchmarks.py`)

| # | Case | Expected |
|---|---|---|
| 5.1 | QQQ benchmark | Starts on the strategy's first execution date with the same cash (A8) |
| 5.2 | Entry cost | Same one-time cost applied |
| 5.3 | Theme-ETF equal-weight | Uses only ETFs that exist at each date |
| 5.4 | Universe equal-weight | Rebalanced at each rebalance from that date's candidates |
| 5.5 | Date alignment | All series share the same date axis |
| 5.6 | Missing benchmark data | Series omitted with a flag, strategy result unaffected |

## 6. Metrics

| # | Case | Expected |
|---|---|---|
| 6.1 | Known equity path | Total return, max drawdown, volatility match hand values |
| 6.2 | Sharpe with risk-free 0 | `mean/std * sqrt(252)` of daily returns |
| 6.3 | Beta and alpha | Strategy = 2 × benchmark daily returns gives beta 2 |
| 6.4 | Hit rate | Counts periods with strategy return above benchmark |
| 6.5 | CAGR on a period under one year | Not annualized (reported as total return only) |
| 6.6 | Short window | `short_window` flag when fewer than 8 rebalances |
| 6.7 | Constant series | Volatility 0, Sharpe `NaN`, no exceptions |

## 7. Historical data layer (`integrations/historical_data.py`)

| # | Case | Expected |
|---|---|---|
| 7.1 | Price view at `as_of` | No rows after `as_of` |
| 7.2 | Statement view | Only statements with `filingDate <= as_of`; `acceptedDate` later than `filingDate` respected |
| 7.3 | TTM construction | Sum of the latest four filed quarters; fewer than four gives `None` fields |
| 7.4 | Growth fields | Equal the live definitions on a shared fixture (mirror test) |
| 7.5 | Split after `as_of` | P/E uses raw price and as-reported EPS (consistent); split-adjusted series used for returns; dollar volume invariant |
| 7.6 | Market cap | Historical value at `as_of`, not current |
| 7.7 | ETF snapshots | Latest valid snapshot only; age and lag rules enforced |
| 7.8 | Unknown ticker | Raises; factor panel degrades it to a NaN row |
| 7.9 | Cache hit | No FMP call on second access (call counter) |
| 7.10 | Budget exceeded | `DATA_BUDGET_EXCEEDED`, partial result, no crash |
| 7.11 | 429 response | Backoff and retry, then clean failure |
| 7.12 | Stub store | Deterministic, offline, no network |
| 7.13 | Patched `fetch_price_history` signature | Works with positional and keyword `lookback_days` |

## 8. Backtest agent: look-ahead, parity, patching

| # | Case | Expected |
|---|---|---|
| 8.1 | **Canary** | Poison all prices, statements, and ETF snapshots dated after `as_of` with extreme values; candidates, scores, ranks, and basket unchanged (A3) |
| 8.2 | **Parity** | Same panel and substitute columns through live `compute_factor_scores/combine_scores/rank` and through the backtest path give identical `composite_score` and `rank` (A4) |
| 8.3 | `construct_basket` copy safety | Input entries are not mutated |
| 8.4 | Weights source | Uses the run's persisted `factor_weights` (6-key and 8-key snapshots); never renormalized |
| 8.5 | Missing factor column for a weight key | Fails fast with a clear error |
| 8.6 | Substitution | `thematic` equals breadth and `sentiment` equals money flow in the scored frame; placeholders never reach the output |
| 8.7 | Deterministic tie-break | Candidates sorted by ticker; repeated runs give identical order |
| 8.8 | `as_of_context` hygiene | Originals restored on normal exit and on exception |
| 8.9 | Concurrency | A second concurrent entry blocks or raises, never interleaves |
| 8.10 | Sector-hit exclusion | Universe contains only ETF-holding tickers; documented difference |
| 8.11 | Empty basket | Cash held, `no_basket` flag, job completes (A9) |
| 8.12 | Partial basket (1–4 names) | Invested, `partial_basket` flag |
| 8.13 | Insufficient universe | Policy applied (`hold_cash`), flag set |
| 8.14 | Widening retries | Up to `max_widen_retries`, then stops |
| 8.15 | Error in one rebalance | Recorded; other rebalances proceed; final status `partial` (A10) |
| 8.16 | All rebalances fail | Status `failed`; parent run untouched |
| 8.17 | Structure tests | No LLM import in the backtest path; engine has no I/O or clock (A2) |
| 8.18 | Other agents untouched | CI check that `git diff` on existing agent files is empty for this PR (A1) |
| 8.19 | Live-unchanged check | Existing agent test suites pass unchanged |
| 8.20 | Task 2 compatibility | With 8-key weights the backtest scores liquidity and volatility without code changes |

## 9. Persistence

| # | Case | Expected |
|---|---|---|
| 9.1 | Save and load round trip | All fields incl. JSON columns preserved |
| 9.2 | Re-running the same `(run_id, mode)` | New row; earlier results unchanged (A11) |
| 9.3 | Stored metadata | Config snapshot, hash, methodology version, code version, data version present |
| 9.4 | Delete run or theme | Backtest rows and equity/trade rows removed by cascade |
| 9.5 | Migration up and down | Clean on a database with existing runs |
| 9.6 | `get_current_holdings_view` | Joins basket, factor rows, K-line snapshot; handles missing K-line or P/E |

## 10. API and orchestration

| # | Case | Expected |
|---|---|---|
| 10.1 | `POST` mode `trailing` | `202` with `backtest_id`; job enqueued |
| 10.2 | `POST` while one is queued or running for the same mode | Same `backtest_id`, no duplicate |
| 10.3 | `POST` with unknown mode or extra parameters | 422 |
| 10.4 | `GET` while running | Status and progress (`stage`, `completed`, `total`) |
| 10.5 | `GET` when succeeded | Full payload incl. disclaimer and methodology version (A13) |
| 10.6 | `GET` for a run without a backtest | Clear "not run" state, not an error |
| 10.7 | Disabled in config | Disabled state; no job queued |
| 10.8 | Auto-trigger | Run success enqueues `trailing`; run failure does not |
| 10.9 | Backtest failure | Parent run status unchanged |
| 10.10 | Trades endpoint | Paginated, ordered by sequence |
| 10.11 | Export CSV/JSON | Correct columns; formula prefixes neutralized |
| 10.12 | Session scoping | Same denial rules as other run endpoints |
| 10.13 | Queue config | Only the `backtest` queue worker (concurrency 1) consumes jobs |
| 10.14 | Timeout | Job stops with `TIMEOUT` and a `partial` or `failed` status |

## 11. Frontend (component tests with mock payloads)

| # | Case | Expected |
|---|---|---|
| 11.1 | Summary cards | Strategy and benchmark values with deltas; hypothetical label always visible |
| 11.2 | Equity curve | Strategy and QQQ lines; rebalance markers; tooltip with both values and excess |
| 11.3 | Controls | Mode toggle, benchmark selector, value/% /excess toggle, linear/log scale update the chart without refetch where possible |
| 11.4 | Rebalance timeline | One card per rebalance with dates, weights bar, holdings, period return vs benchmark, flags |
| 11.5 | Current holdings table | Columns: stock and company, 6M return, price, P/E, market cap, 6M K-line; sorting; `n/m` for non-positive or missing P/E |
| 11.6 | Mini K-line | Placeholder when `unavailable`; opens the Task 3 modal |
| 11.7 | Contribution bars | Diverging bars sorted by P&L; costs bar; total equals the summary P&L |
| 11.8 | Trade blotter | Sort and filter by rebalance and ticker; paging |
| 11.9 | States | Not run (button), queued, running (stage text and progress), partial (banner with details), failed (error and Retry), disabled |
| 11.10 | Flags | `short_window`, `survivorship_risk`, `llm_factors_replaced` chips with explanations |
| 11.11 | Export menu | CSV (equity, trades, rebalances), JSON, chart image, print |
| 11.12 | Methodology popover | Shows assumptions and disclaimer |
| 11.13 | Responsive | Cards below 768 px; no horizontal page scroll |
| 11.14 | Print | Light theme, controls hidden, chart and tables intact, disclaimer present |
| 11.15 | Accessibility | Keyboard operation, `aria` labels for charts (text summary), contrast, reduced motion |
| 11.16 | Polling | Stops on terminal states; backs off; handles network errors |

## 12. Manual and analytical QA

- Recompute one rebalance by hand (spreadsheet): candidates, breadth, money
  flow, z-scores, composite, ranks, basket, and trades; compare to the stored
  result.
- Compare the strategy and QQQ curves to a charting site for the same dates.
- Run trailing mode on three themes from real runs and full mode on one;
  record runtime, FMP call counts, flags, and the number of candidates without
  price history.
- Inspect early-year periods in full mode for insufficient universes
  (ETFs launched after 2021).
- Verify `llm_factors_replaced` and `survivorship_risk` appear.
- Review all user-facing copy with compliance (D10).
- Screenshots: desktop, tablet, phone; light and dark; print preview.

## 13. Opt-in live tests

Marker `live_network`, excluded by default: fetch real history for 3 tickers
and 2 ETFs; verify no data after `as_of`, correct adjustment relationships
(raw vs split-adjusted vs total-return), a dated ETF holdings snapshot, and a
filed-statement view. Run before release and when the FMP integration changes.

## 14. Commands

```
pnpm lint
pnpm lint:api
pnpm test:api
pnpm --dir src/web test
pnpm check:structure
pnpm build
```

## 15. Exit criteria

All rows in §1–§11 pass, A1–A14 in `SPEC.md` are satisfied, the canary and
parity tests run in CI, §12 findings are recorded in the PR description, the
live test passed once, and the documentation in `PLAN.md` Step 11 is updated
in the same PR.
