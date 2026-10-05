# Task 3 — UI Design: Backtest section

Companion to `SPEC.md`. Scope: the **Backtest** section on a run page, shown
beside the existing Basket, Rankings, and Report sections. It reuses the
design tokens, `ReturnPill`, `KlineMini`, `KlineModal`, export menu, and
print stylesheet from Task 3 (`tasks/task3/UI_DESIGN.md`). The UI framework
was not inspected; component names are conceptual.

Included: strategy summary cards, equity curve, rebalance timeline, current
holdings table, contribution bars, trade blotter, progress and failure
states, controls, export. Not included: factor attribution charts, multi-run
comparison, shareable links.

## 1. Principles

- **Always hypothetical.** The label "Hypothetical backtest, not performance"
  is visible whenever results are shown, in print, and in exports.
- **Honest scale.** Short windows and survivorship risk are shown as chips,
  not buried in a footnote.
- **No color-only meaning.** Signs, arrows, and labels accompany every
  up/down color.
- **The backtest never blocks the run.** The section loads independently and
  tolerates not-run, running, partial, failed, and disabled states.
- **Backend does the math.** The UI renders payload values; it recomputes
  nothing except display transforms (percent view, excess view, log scale).

## 2. Placement and layout (desktop)

The run page gains a "Backtest" tab (or section) after Report. Tabs keep the
Report layout from Task 3 untouched.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Backtest   [Trailing 12M ▾] [Benchmark: QQQ ▾] [$ │ % │ Excess] [Log]  │  Controls
│ ⚠ Hypothetical backtest, not performance · Methodology ⓘ    [Export ▾] │
│ chips: Short window · Survivorship risk · LLM factors replaced         │
├────────────────────────────────────────────────────────────────────────┤
│ ┌Final value─┐┌Total return┐┌Max drawdown┐┌Sharpe┐┌Alpha / Beta┐      │  Summary cards
│ │ $11,420    ││ +14.2%     ││ -8.1%      ││ 1.1  ││ +3.2% / 1.3││      │
│ │ QQQ $11,050││ QQQ +10.5% ││ QQQ -6.4%  ││ 0.9  ││            ││      │
│ └────────────┘└────────────┘└────────────┘└──────┘└────────────┘      │
│ ┌Quarterly win rate┐┌Turnover┐┌Costs paid┐                             │
├────────────────────────────────────────────────────────────────────────┤
│ Equity curve ($10,000 start)                                           │
│   ╱╲  ╱╲___╱‾‾  strategy ──  QQQ ──  ┆ rebalance markers               │
│ ──────────────────────────────────────────────────                     │
│ Drawdown (underwater)                                                  │
├────────────────────────────────────────────────────────────────────────┤
│ Rebalance timeline                                                     │
│ ●──────●──────●──────●                                                 │
│ Oct 25  Jan 26 Apr 26 Jul 26                                           │
│ [card per rebalance: weights bar · holdings · return vs QQQ · flags]   │
├────────────────────────────────────────────────────────────────────────┤
│ Current holdings (this run's basket)                                   │
│ Stock | 6M return | Price | P/E | Market cap | 6M K-line               │
├────────────────────────────────────────────────────────────────────────┤
│ Contribution by stock (P&L)         │ Trade blotter                    │
│ bars…                               │ table…                           │
└────────────────────────────────────────────────────────────────────────┘
```

Order of sections: header and controls, summary cards, equity curve,
rebalance timeline, current holdings, contribution bars, trade blotter.
At 1024 px and above, contribution bars and the blotter may sit side by side;
below that they stack.

## 3. Controls

| Control | Options | Behavior |
|---|---|---|
| Mode | `Trailing 12M` (default), `Full 2021–2025` | Switching loads that mode's result. If `full` has not been run, show a "Run full backtest" button (D1) with a time estimate and a note that it may take several minutes. |
| Benchmark | QQQ (default), SPY, Theme ETFs (equal weight), Candidate universe (equal weight) | Only options present in `series`. Swaps the comparison line, the delta chips on cards, and the excess view; no refetch. |
| Y-axis view | `$` (default), `%` return, `Excess` vs benchmark | Pure display transform of `series`. |
| Scale | Linear (default), Log | Applies to `$` view only. |
| Period (full mode) | `All`, `Last 12M`, `Calendar year` chips | Slices the series client-side; summary cards keep full-period values and say so in a tooltip. |

Controls are keyboard operable; the selected state is reflected in
`aria-pressed`/`aria-selected`. Selections persist for the session in
`localStorage` wrapped in try/catch.

## 4. Strategy summary cards

Data: `summary.strategy`, `summary.benchmarks[selected]`.

| Card | Value | Subtext |
|---|---|---|
| Final value | Strategy value of $10,000 | Benchmark value, difference |
| Total return (net of costs) | Pill with sign and arrow | Benchmark return, excess in percentage points |
| Max drawdown | Strategy | Benchmark, with dates in tooltip |
| Sharpe | Strategy | Benchmark; tooltip shows the risk-free assumption |
| Alpha / Beta | vs primary benchmark | Tooltip explains the regression; `n/a` if too few points |
| Quarterly win rate | `3 / 4 quarters beat QQQ` | |
| Turnover | Annualized | Tooltip definition |
| Costs paid | Dollar amount | `10 bps per side` from config |

Rules: CAGR appears only in full mode (period of at least one year);
all cards show `n/a` rather than `0` when a metric is `NaN`; a "Short
window" chip appears with a tooltip when fewer than 8 rebalances; no word
such as "outperformed" without the hypothetical qualifier nearby.

## 5. Equity curve

- Lines: strategy (accent), selected benchmark (muted neutral), optional
  second benchmark via a legend toggle. Start value $10,000 marker.
- Rebalance markers: vertical dotted lines or ticks on the x-axis; hover/
  focus shows the rebalance date and basket size. Click scrolls to that
  rebalance card in the timeline.
- Tooltip: date, strategy value, benchmark value, excess ($ and %).
- Shaded in-progress period when present (label "in progress").
- A second panel below shows drawdown (underwater) for the strategy and
  benchmark.
- Text summary for screen readers: "Strategy ended at $X versus $Y for QQQ
  over N months", plus a hidden data table.
- Chart library: reuse Task 3's choice (D4 in that spec) for visual
  consistency; honor its attribution requirements.
- Empty/short data: show the available points with a note rather than
  failing.

## 6. Rebalance timeline

A horizontal marker row (one dot per rebalance) above a vertical list of
cards (accordion on mobile). Data: `rebalances[]`.

Card content:

- Header: `Rebalance 2 of 4 · Signal 2025-12-31 · Executed 2026-01-02 · Held to
  2026-04-01` and period status (`completed` / `in progress`).
- Weights bar: stacked segments by holding, colored by sub-exposure; legend
  with ticker, weight, sub-exposure.
- Holdings chips: ticker, weight, rank; click filters the blotter to this
  rebalance.
- Period return versus the selected benchmark with excess, using `ReturnPill`.
- Top contributor and top detractor for the period (ticker and P&L).
- Flags as chips: `partial_basket`, `no_basket` (shows "held cash"),
  `insufficient_universe`, `missing_prices`, `etf_snapshot_stale`,
  `delisted_holding`, each with a tooltip.
- Collapsible "Inputs" panel: candidate and eligible counts, number of ETFs
  with valid snapshots, warnings from the universe step.

## 7. Current holdings table

This lists **the live basket from this run** (not the simulated last
rebalance). A caption says: "Current basket from this run's pipeline. The
backtest above uses a deterministic version of the strategy." Data:
`current_holdings[]`.

| Column | Cell |
|---|---|
| Stock | Ticker (monospace, bold) and company name; second line `weight · rank` |
| 6M return | `ReturnPill` (sign, arrow, color); `n/a` if missing |
| Current price | Last close with the as-of date in a tooltip |
| P/E | One decimal; `n/m` when missing or non-positive (tooltip: "not meaningful: negative or missing earnings") |
| Market cap | Compact format (`$412.3B`, `$3.1T`) |
| 6M K-line | `KlineMini` (Task 3); click opens `KlineModal`; placeholder `Chart unavailable` |

Behavior: sortable by stock, 6M return, P/E, market cap (default: weight
descending); sticky header; tabular numerals; right-align numeric columns;
footer: "Prices and chart: stock-sdk (public market data), as of {date}".
Below 768 px, render cards: ticker/company/weight row, return pill, mini chart
full width, then price, P/E, market cap as a small stat grid.

## 8. Contribution bars

Data: `attribution[]`, `costs_total`.

- Horizontal diverging bars centered on zero, sorted by P&L, positive in the
  up token and negative in the down token; labels `AAPL +$312 (+3.1 pts)`.
- A separate "Costs" bar (negative) at the bottom.
- A total line equal to final value minus $10,000, matching the summary card.
- Hover or focus shows company name, periods held, and P&L.
- Toggle: dollars or percentage points of initial capital.
- Limit to the top 15 by absolute P&L with an "All N positions" expander.

## 9. Trade blotter

Data: `GET /runs/{id}/backtest/trades` (paginated).

Columns: Date, Ticker, Side (BUY / SELL with text, not color alone), Shares,
Price, Value, Cost, Reason (`entry`, `exit`, `increase`, `decrease`).
Filters: rebalance (dropdown synced with the timeline), ticker search, side.
Sortable by date or value; paging 25 rows; row count and totals (buys, sells,
costs) in a footer; CSV export for the filtered or full set.

## 10. Progress, empty, and failure states

| State | Treatment |
|---|---|
| Not run (legacy run or auto-trigger off) | Empty panel: explanation, **Run backtest** button |
| Queued | "Queued" with position if available; polling every 3 s |
| Running | Stepper `Fetching data → Building universe → Scoring 2/4 → Simulating → Finalizing`; progress bar from `progress`; skeleton cards; "You can leave this page; results will be here later" |
| Partial | Result shown with a prominent banner: which rebalances failed or were empty, and why (`DATA_BUDGET_EXCEEDED`, `NO_BASKET`, ...); the affected periods are marked on the chart |
| Failed | Error summary with code, short explanation, **Retry** (re-POST), and "Show technical details" disclosure |
| Disabled | "Backtest is turned off for this environment" |
| Stale methodology | Chip "Computed with methodology v1; current is v2" with a Re-run button |
| Network error while polling | Inline retry; polling backs off; stops at terminal states |

Polling stops when status is terminal. Each state has `aria-live="polite"`
announcements for stage changes.

## 11. Methodology popover and flags

- **Methodology ⓘ** opens a popover (or side drawer) summarizing
  `METHODOLOGY.md`: schedule, signals and substitutions, execution and costs,
  benchmarks, data sources, limitations, and the disclaimer. A "Read full
  methodology" link opens the full text.
- **Flag chips** (from `flags`):
  - `short_window` — "Short window: few rebalances, results are not
    statistically meaningful."
  - `survivorship_risk` — "Universe is built from ETF holdings and may omit
    names that were later removed or delisted."
  - `llm_factors_replaced` — "Thematic and sentiment scores use ETF
    breadth and money flow, not the live LLM-based scores."
- The disclaimer text comes from the payload.

## 12. Export

`ExportMenu`:

- **Equity curve CSV**: date, strategy, each benchmark.
- **Trades CSV**: all blotter columns.
- **Rebalances CSV**: one row per rebalance and holding.
- **JSON**: the full payload.
- **Chart image (PNG)**: the equity curve with legend, benchmark, and the
  hypothetical label baked in.
- **Print / PDF**: print stylesheet: light theme, controls hidden, all
  sections expanded (timeline cards open, blotter limited to the first 100
  rows with a note), charts as static images, methodology summary and
  disclaimer on the last page, header with run date and data source.

## 13. Visual system

Reuse Task 3 tokens (`--bg`, `--surface`, `--up`, `--down`, `--accent`,
`--muted`, `--warn`). Additional tokens: `--benchmark` (neutral gray-blue
line), `--series-2` for a second benchmark, a categorical palette of 8
distinguishable colors for sub-exposures, validated for contrast and for
color-blind safety. Dark and light themes both supported. Tabular numerals
for all figures; consistent 8 px grid.

## 14. Responsive behavior

| Width | Layout |
|---|---|
| 1024 px and up | Cards in two rows; chart full width; contribution bars and blotter side by side |
| 768–1023 px | Cards wrap; sections stack; tables scroll inside their own container with a sticky first column |
| Below 768 px | Controls collapse into a single "Options" sheet; summary cards in a 2-column grid; timeline as an accordion; holdings as cards; blotter as a compact list with a "Details" expander; chart height reduced, tooltip on tap |

No horizontal page scroll at any width.

## 15. Accessibility

Semantic tables and headings; text alternatives and hidden data tables for
every chart; focus management for popovers and modals (shared with Task 3's
modal); AA contrast in both themes; keyboard access to all controls, markers,
and filters; no meaning conveyed by color alone; `prefers-reduced-motion`
respected for stepper and chart animations; announcements for state changes.

## 16. Copy

| Where | Text |
|---|---|
| Banner | Hypothetical backtest, not performance. Past results do not predict future results. |
| Disclaimer | From the payload (`disclaimer`); final wording requires compliance review (D10) |
| Short window | Short window: results are not statistically meaningful. |
| Current holdings caption | Current basket from this run's pipeline. The backtest uses a deterministic version of the strategy. |
| P/E not meaningful | n/m — negative or missing earnings |
| Not run | No backtest yet for this run. |
| Full mode hint | Runs the strategy over 2021–2025 (20 rebalances). This can take several minutes. |

## 17. Component inventory

`BacktestSection`, `BacktestControls`, `BacktestStatusBanner`, `FlagChips`,
`SummaryCards`, `EquityCurveChart`, `DrawdownChart`, `RebalanceTimeline`,
`RebalanceCard`, `WeightsBar`, `CurrentHoldingsTable`, `HoldingCard` (mobile),
`ContributionBars`, `TradeBlotter`, `ExportMenu`, `MethodologyPopover`,
`BacktestProgress`; reused from Task 3: `ReturnPill`, `KlineMini`,
`KlineModal`, `ThemeToggle`.

## 18. Visual QA checklist

- [ ] Hypothetical label visible in every state that shows numbers, in print,
      and in the PNG export.
- [ ] Benchmark selector changes line, card deltas, and excess view together.
- [ ] Strategy final value equals $10,000 plus contribution total.
- [ ] Rebalance markers match timeline cards and blotter filter.
- [ ] `n/a`/`n/m` shown instead of zero for missing values.
- [ ] Partial and failed banners list specific reasons.
- [ ] Flag chips explain themselves on hover and focus.
- [ ] Phone layout has no horizontal scroll; charts readable.
- [ ] Light and dark themes pass contrast checks.
- [ ] Print output complete, with methodology summary and disclaimer.
