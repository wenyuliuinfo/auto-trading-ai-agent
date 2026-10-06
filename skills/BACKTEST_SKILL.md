---
name: backtest-agent-implementation
description: Use this skill whenever writing, modifying, reviewing, or debugging code in app/agents/backtest.py, app/backtest/**, or app/integrations/historical_data.py — the as-of (point-in-time) data layer, historical rebalance scoring that reuses other agents' functions, portfolio simulation, benchmark comparison, metrics, attribution, or how backtest results are persisted and served. Covers the hard rules that keep the backtest free of look-ahead bias, LLM calls, and edits to other agents. Do not use this skill for live-pipeline changes to the Screener, Analyst, Modeling, Trader, or Report agents (see their own SKILL.md files).
---

# Backtest Agent — Canonical Implementation & Rules

This skill is the single source of truth for **how** the Backtest agent
replays the pipeline's deterministic strategy over history and simulates a
$10K portfolio against benchmarks. `tasks/task4/SPEC.md` explains the
contract and `tasks/task4/METHODOLOGY.md` explains the assumptions; this file
is what a coding agent should load and follow *while writing the code*.

**Scope reminder:** the Backtest agent is an **evaluator** of the strategy,
not a new strategy and not a research agent. It never writes prose, never
calls an LLM, and never changes how any other agent behaves. Its output is
hypothetical performance, always labeled as such.

## Where this logic lives (per `CONVENTIONS.md` §2)

```
app/
├── agents/
│   └── backtest.py            # orchestration only: load run + theme_config,
│                               #   build schedule, per-rebalance scoring via
│                               #   IMPORTED functions, call engine, persist
├── backtest/                  # PURE engine: no I/O, no DB, no network,
│   ├── calendar.py            #   no clock reads
│   ├── signals.py             # etf_breadth(), money_flow_ratio()
│   ├── portfolio.py           # positions, trades, costs, mark-to-market
│   ├── simulate.py            # schedule + targets -> equity, trades, periods
│   ├── benchmarks.py
│   ├── metrics.py
│   └── types.py
├── integrations/
│   └── historical_data.py     # as-of data store: FMP fetch + cache
├── data/
│   └── queries.py             # save_backtest(), get_backtest(), ...
config/
└── backtest.yaml              # the only source of backtest parameters
```

Verify the new `app/backtest/` package against `pnpm check:structure`; add it
as a layer that may not import `integrations/`, `data/`, or `agents/`.

## Hard rules

1. **Import only; never edit other agents.** `agents/backtest.py` may import
   and call functions from `screener.py`, `modeling.py`, `trader.py` and
   `integrations/factor_panel.py`. It must not modify those files. If a
   needed behavior is not importable, implement it inside `app/backtest/` or
   `agents/backtest.py` and add a **parity test** against the live function.
   Allowed imports:
   - `modeling`: `compute_factor_scores`, `combine_scores`, `rank`,
     `_build_scoring_frame` (private, covered by a parity test)
   - `trader`: `construct_basket` (pass **deep copies**; it mutates its input)
   - `screener`: `assemble_candidate_universe`, `MAX_CANDIDATES`,
     `MIN_CANDIDATES`
   - `factor_panel`: `get_factor_panel`, `RAW_FACTOR_COLUMNS`
   Never import `*_node` functions, `DeepSeekClient`, or anything that writes
   run artifacts (`save_*`).
2. **No look-ahead, enforced structurally.** Every data accessor takes an
   explicit `as_of` and returns only rows dated on or before it (price date;
   statement `filingDate`/`acceptedDate`; ETF snapshot date). Signals use data
   through the **signal date** (last trading day before the rebalance date);
   trades execute at the **rebalance-date close**. A canary test must poison
   all post-`as_of` data and prove no signal changes.
3. **No LLM anywhere in the backtest path.** Same inputs and config must give
   identical outputs. No `DeepSeekClient`, no `stubbing_enabled()` branches
   that call a model, no prose generation. A structure test fails the build
   if `deepseek_client` is imported under `app/backtest/**` or
   `agents/backtest.py`.
4. **Signal substitutions are fixed.** The LLM-derived factors are replaced:
   - `thematic` = number of the theme's mapped ETFs that hold the stock at the
     signal date (`etf_breadth`)
   - `sentiment` = money-flow ratio over the trailing 126 trading days
     (`money_flow_ratio`)
   All other factors come from the live `get_factor_panel` /
   `_build_scoring_frame` path running on as-of data. **Weights come from the
   run's persisted `theme_config["factor_weights"]`**, never from a file at
   backtest time and never renormalized (Modeling Hard Rule 2).
5. **Global patch discipline.** As-of data is injected by temporarily
   replacing `fetch_price_history` and `fetch_fundamentals` inside
   `app.integrations.factor_panel` (and `search_sector`/`search_holdings` in
   `app.agents.screener`) using `unittest.mock.patch.object` inside the
   `as_of_context(...)` context manager. Rules: patch only inside that
   context manager, hold the module-level `threading.Lock` for the whole
   scoring call, restore in `finally`, run only on the dedicated
   `backtest` worker queue with concurrency 1, never patch in the API
   process.
6. **The engine is pure.** `app/backtest/**` does no file, DB, or network
   I/O and never reads the clock (`date.today()`, `datetime.now()`). Dates are
   arguments. This is what makes the simulation unit-testable.
7. **Missing data is `NaN`/flagged, never zero or silently filled.** Do not
   forward-fill prices across more than `max_price_gap_days`. A candidate
   without a price at execution is skipped and recorded (`missing_prices`).
   A holding whose price series ends mid-period follows the configured
   delisting policy and is flagged. Count and report candidates that appear in
   historical ETF holdings but have no price history (survivorship signal).
8. **Accounting must close.** At all times
   `portfolio_value = cash + sum(shares * price)`. Per-ticker P&L, minus costs,
   equals total P&L (attribution identity). Weights from the Trader sum to 1.0
   (cash only when a basket is empty or partial by policy). Costs are charged
   on traded value `|delta|` and recorded on each trade.
9. **Results are immutable and reproducible.** Persist the config snapshot and
   its hash, `methodology_version`, code version (git SHA), and data version
   with every backtest. A rerun creates a new `backtest_id`; never update a
   finished result in place.
10. **Failure isolation.** A backtest never changes the parent run's status.
    Per-rebalance errors are recorded and the job continues; the final status
    is `succeeded`, `partial` (some rebalances failed or were empty), or
    `failed`. Enforce the FMP call budget and per-job timeout from config.
11. **Hypothetical performance is always labeled.** Every API payload carries
    `disclaimer` and `methodology_version`; no field, label, or log line may
    imply realized performance. The UI renders the disclaimer from the
    payload.
12. **Benchmarks use the same rules.** Same start date, initial cash, entry
    cost, and total-return-adjusted prices as the strategy. Benchmark series
    are computed by `app/backtest/benchmarks.py`, not by ad hoc UI code.
13. **Config-as-code.** `config/backtest.yaml` is the only source of
    parameters. The API accepts only `mode` (`trailing` or `full`). Read the
    file once at job start and persist the snapshot.
14. **Cache first, budget always.** Read from the cache before calling FMP.
    Count FMP calls per job and stop with `DATA_BUDGET_EXCEEDED` when the
    configured budget is reached (partial results allowed).
15. **Regenerate and retarget at every rebalance.** The scoring and selection pipeline runs once per rebalance on as-of data; the portfolio is traded to each new target. A basket is never reused across dates, and the live basket is never used for historical dates.
16. **No fabricated data.** Nothing outside StubStore and test fixtures may use randomness, identifier-derived numbers, or placeholder returns. Stub results are labeled and blocked in production.


## Reference implementation (sketch; align names with the real modules)

### As-of context (hard rule 5)

```python
# agents/backtest.py
import threading
from contextlib import contextmanager
from unittest.mock import patch

from app.agents import screener
from app.integrations import factor_panel

_PATCH_LOCK = threading.Lock()


@contextmanager
def as_of_context(store, as_of, reference_rows):
    price_fn = store.make_price_fetcher(as_of)            # returns PriceHistory
    fund_fn = store.make_fundamentals_fetcher(as_of)      # returns Fundamentals
    with _PATCH_LOCK, \
         patch.object(factor_panel, "fetch_price_history", price_fn), \
         patch.object(factor_panel, "fetch_fundamentals", fund_fn), \
         patch.object(screener, "search_sector", lambda keyword: reference_rows):
        yield
```

`price_fn(ticker, lookback_days=504)` must accept both positional and keyword
`lookback_days`, return `PriceHistory(close=..., volume=...)` sliced to
`<= as_of` using the **split-adjusted** series, and raise for unknown tickers
(the live code already degrades a failed ticker to a NaN row).

### Per-rebalance scoring (hard rules 1, 4)

```python
def score_rebalance(ctx, rebalance) -> RebalanceResult:
    as_of = rebalance.signal_date
    hits = ctx.store.etf_universe(ctx.sub_exposures, as_of)         # PIT holdings
    with as_of_context(ctx.store, as_of, ctx.store.reference_rows(as_of)):
        candidates, warnings = screener.assemble_candidate_universe(
            hits, max_candidates=ctx.max_candidates
        )
        tickers = sorted(c["ticker"] for c in candidates)           # stable order
        panel = factor_panel.get_factor_panel(tickers)

    reports = [
        {"ticker": t, "thematic_relevance_score": 3, "sentiment_label": "neutral"}
        for t in tickers                                            # placeholders
    ]
    frame = modeling._build_scoring_frame(panel, reports)
    frame["thematic"] = signals.etf_breadth(tickers, ctx.store.etf_membership(as_of))
    frame["sentiment"] = signals.money_flow_ratio(ctx.store.ohlcv(tickers, as_of))

    weights = ctx.theme_config["factor_weights"]                    # persisted snapshot
    factor_cols = [k.removesuffix("_z") for k in weights]
    scored = modeling.compute_factor_scores(frame, factor_cols)
    scored["composite_score"] = modeling.combine_scores(scored, weights)
    ranked = modeling.rank(scored)

    entries = build_ranked_entries(ranked, candidates)              # mirrors modeling_node
    basket, near_misses, swaps = trader.construct_basket(
        copy.deepcopy(entries), ctx.theme_config
    )
    return RebalanceResult(basket=basket, warnings=warnings, ...)
```

`build_ranked_entries` reproduces the fields `construct_basket` reads:
`ticker`, `composite_score` (or `None` when NaN), `rank`, `market_cap`,
`avg_dollar_volume` (from `adv`), `sub_exposure`, `caveats` (`[]`).

### Engine entry point (hard rules 6, 8)

```python
# backtest/simulate.py
def simulate(schedule, targets, price_panel_tr, config) -> SimulationResult:
    """schedule: list[Rebalance]; targets: {exec_date: {ticker: weight}};
    price_panel_tr: dividend+split-adjusted closes; no I/O, no clock."""
```

## Test fixtures to include (per `CONVENTIONS.md` §5)

- **Look-ahead canary:** poison every price, statement, and ETF snapshot dated
  after `as_of`; the ranked list and basket must be byte-identical.
- **Parity:** for one as-of date, the backtest scoring path and the live
  functions given the same panel produce the same `composite_score` and
  `rank` (with the substituted columns held equal).
- **`construct_basket` copy safety:** the entries passed in are not mutated.
- **Patch hygiene:** after `as_of_context` exits (including on exception), the
  original functions are restored; concurrent use raises or blocks.
- **Accounting identity:** per-ticker P&L minus costs equals total P&L;
  portfolio value equals cash plus positions at every date.
- **Empty and partial baskets:** an empty basket holds cash and is flagged; a
  partial basket invests the names it has.
- **No LLM:** structure test fails if an LLM client is imported.
- **Determinism:** two runs with the same inputs give identical results.
- **Failure isolation:** a data error in one rebalance yields `partial`, not a
  crash, and never touches the parent run.
