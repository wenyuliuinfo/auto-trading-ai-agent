# Task 2 — Test Plan

Companion to `SPEC.md` (acceptance criteria A1–A12), `PLAN.md`, `UI_DESIGN.md`.
Unit and integration tests are offline and deterministic: use recorded SDK
fixtures (PLAN Step 0.1), stub mode, and mocked LLM responses. Live-network
tests are opt-in (§13).

## 1. Node bridge (`tools/stock-sdk-kline`)

| # | Case | Expected |
|---|---|---|
| 1.1 | Valid request for 2 symbols (mocked SDK) | `results` has both, `status: ok`, ISO dates, numeric OHLCV |
| 1.2 | One symbol rejected by the SDK | That symbol `status: error` with a code; the other still `ok`; exit code 0 |
| 1.3 | Malformed stdin JSON | Non-zero exit, JSON error on stdout or empty, no hang |
| 1.4 | Unknown `version` | Clear error, non-zero exit |
| 1.5 | Concurrency cap | Never more than the configured parallel SDK calls |
| 1.6 | Bars with null OHLC from the SDK | Normalized or omitted, never written as `NaN` strings |

## 2. Python integration (`app/integrations/kline.py`)

| # | Case | Expected |
|---|---|---|
| 2.1 | Valid snapshot from fixture | `status ok`, `len(bars) == 126`, ascending dates, `as_of` = last date |
| 2.2 | Bridge returns >126 bars | Only the last 126 kept |
| 2.3 | Invalid symbol (`"AAPL; rm -rf /"`, lowercase, empty, 20 chars) | `INVALID_SYMBOL`, never passed to the subprocess |
| 2.4 | Share-class symbols (`BRK.B`, `BF.B`) | Handled per Step 0 findings; documented result |
| 2.5 | Bad bars: non-positive price, `high < close`, `low > open`, duplicate date | Dropped; remaining bars valid; sorted |
| 2.6 | 15 bars only | `status insufficient`, no chart |
| 2.7 | 20 to 125 bars | `status ok` with `short_history` flag |
| 2.8 | Last bar older than 7 days | `stale` flag |
| 2.9 | One-day close move of +/-40% | `suspect_adjustment` flag; bars unchanged |
| 2.10 | Subprocess timeout | All tickers `unavailable` / `BRIDGE_FAILED`; process killed; no exception escapes |
| 2.11 | Non-zero exit code | Same as 2.10 |
| 2.12 | Output exceeds size cap | Same as 2.10 |
| 2.13 | Stdout is not valid JSON | Same as 2.10 |
| 2.14 | `kline_enabled = false` | `unavailable` / `DISABLED`, subprocess never started |
| 2.15 | Stub mode | Deterministic bars (same ticker twice gives identical data), no Node, no network |
| 2.16 | Node binary missing | `BRIDGE_FAILED`, clear log line, run continues |
| 2.17 | Subprocess invocation | Asserted to use an argument list with no shell and symbols only on stdin |

## 3. Derived metrics

| # | Case | Expected |
|---|---|---|
| 3.1 | 126 bars, known first/last close | `return_6m == last/first - 1` (A4) |
| 3.2 | Same data as `momentum_6m` definition | Equal to `close[-1]/close[-126]-1` within float tolerance |
| 3.3 | 120 to 125 bars | Return computed over available bars |
| 3.4 | Fewer than 120 bars, factor panel has `momentum_6m` | Fallback value, `return_6m_source = factor_panel` |
| 3.5 | No snapshot and no `momentum_6m` | `null` |
| 3.6 | `bars[0].close <= 0` | Treated as missing, no division error |
| 3.7 | `weighted_return_6m` with known weights/returns | Hand-computed value |
| 3.8 | One holding with `null` return | Excluded from numerator and denominator; `return_coverage` reflects it |
| 3.9 | Coverage below 0.5 | UI value `n/a` (summary still contains the number) |
| 3.10 | `top3_weight` with fewer than 3 holdings | Sum of what exists |
| 3.11 | `allocation_by_sub_exposure` with missing sub-exposure | Grouped as "Other"; sums equal total weight |
| 3.12 | `data_as_of` with mixed dates | Correct earliest/latest; ignores `null` |

## 4. Report assembly (`report.py`)

| # | Case | Expected |
|---|---|---|
| 4.1 | Fixture basket, mocked narrative | Table has 5 columns in the specified order, one row per holding (A1) |
| 4.2 | Row order | Weight descending, ties by rank |
| 4.3 | Headline contains `|`, `[`, `]`, newline | Cell valid; table not broken (A9) |
| 4.4 | News URL `javascript:alert(1)` or `data:` | Rendered as plain text, no link |
| 4.5 | `why_included` contains `|` and newlines | Escaped / collapsed |
| 4.6 | No news | `No recent news available.` |
| 4.7 | News selection | Newest by `published_at`; first item when dates are absent |
| 4.8 | Chart status `unavailable` | `Chart unavailable` in the cell; run unaffected (A3, A10) |
| 4.9 | Return `None` | `n/a` |
| 4.10 | Return formatting | `+18.4%`, `-3.2%`, `+0.0%` |
| 4.11 | Output contains no paragraph-style holdings; `_reformat_holdings_table` is gone | Asserted (A2) |
| 4.12 | Excluded and risk sections | Equivalent to the Step 1 baseline |
| 4.13 | Empty `risk_clusters` | Default sentence, nothing fabricated |
| 4.14 | Fewer than 3 near-misses | Section renders sensibly |
| 4.15 | Disclaimer | Appended in `report_md` even when narrative text contains disclaimer-like words; also in `report_data.disclaimer` (A8) |
| 4.16 | Single holding basket | Table with one row, summary values valid |

## 5. LLM narrative handling

| # | Case | Expected |
|---|---|---|
| 5.1 | Valid JSON | Used as-is for thesis, reasons, excluded, risks |
| 5.2 | Extra ticker not in basket | Dropped (A6) |
| 5.3 | Holding missing from `holdings` | Deterministic fallback text built only from upstream fields (A6) |
| 5.4 | Empty `why_included` | Fallback |
| 5.5 | Invalid JSON / schema violation / exception | Complete report, `narrative_fallback = true`, warning logged, run succeeds (A7) |
| 5.6 | Prompt/context inspection | No bars; `return_6m` present; no instruction to output headline or return (A5) |
| 5.7 | Context for caveats | Modeling `caveats` still reach the LLM input and `report_data.holdings[].caveats` |
| 5.8 | Model and temperature | Unchanged constants |
| 5.9 | Exactly one LLM call per report | Asserted with a mock counter |

## 6. SVG renderer

| # | Case | Expected |
|---|---|---|
| 6.1 | 126 daily bars | About 26 weekly candles; valid XML |
| 6.2 | Weekly aggregation | Open = first open, high = max, low = min, close = last close |
| 6.3 | Flat price (all equal) | Renders without division by zero |
| 6.4 | Fewer than 20 bars | Not rendered (caller shows placeholder) |
| 6.5 | Determinism | Same bars give byte-identical SVG |
| 6.6 | Content | Only numeric attributes and a `<title>` from stored numbers; contains `role="img"` |
| 6.7 | Up vs down candles | Different fill/stroke classes |

## 7. API

| # | Case | Expected |
|---|---|---|
| 7.1 | Report endpoint, new run | Contains `report_data` with schema_version 1 |
| 7.2 | Report endpoint, legacy run | `report_data: null`, `report_md` unchanged |
| 7.3 | `GET /klines/{ticker}` for a holding | JSON bars, source, sdk_version, flags |
| 7.4 | Ticker not in the run | 404 |
| 7.5 | Run from another session | Same denial as existing run endpoints |
| 7.6 | `mini.svg` | `image/svg+xml`, `Cache-Control: private`, valid SVG |
| 7.7 | Export `md` | Image URLs absolute via `public_base_url`; table intact |
| 7.8 | Export `csv` | One row per holding; header correct; fields quoted |
| 7.9 | CSV cell starting with `=`, `+`, `-`, `@` | Neutralized (formula injection) |
| 7.10 | Invalid `format` value | 422 |
| 7.11 | OpenAPI schema | Matches response models |

## 8. Persistence

| # | Case | Expected |
|---|---|---|
| 8.1 | `save_klines` then `get_klines` | Round trip incl. flags and bars |
| 8.2 | Saving twice for the same `(run_id, ticker)` | Idempotent upsert (checkpoint resume safe) |
| 8.3 | `save_report` with and without `report_data` | Both work; old callers unaffected |
| 8.4 | Delete a run/theme (Task 1 flow) | `run_klines` rows removed via cascade |
| 8.5 | Migration up/down | Applies cleanly on a DB with existing reports |

## 9. Groundedness checker

| # | Case | Expected |
|---|---|---|
| 9.1 | Report with table rows and derived returns | Returns, weights and scores recognized as grounded |
| 9.2 | LLM text with an invented number | Still flagged (advisory) |
| 9.3 | Checker run on legacy paragraph report | Still works |

## 10. Frontend (component tests with mock `report_data`)

| # | Case | Expected |
|---|---|---|
| 10.1 | Summary header | Shows holdings count, weighted return with the hypothetical label, top-3 weight, allocation bar, data-as-of |
| 10.2 | Coverage below 0.5 | Weighted return shows `n/a` |
| 10.3 | Holdings table | Five columns in the specified order; default sort by weight |
| 10.4 | Sort controls | Weight, 6M return, composite score, name; `aria-sort` updates |
| 10.5 | Return pill | Sign, arrow glyph and color (not color alone) |
| 10.6 | `factor_panel` fallback marker | Footnote marker when `return_6m_source = factor_panel` |
| 10.7 | News cell | Link with `rel="noopener noreferrer"`, source text, safe URL only |
| 10.8 | Mini chart | `<img>` with alt text; placeholder when `unavailable` or `insufficient` |
| 10.9 | Chart flags | `stale` / `suspect_adjustment` / `short_history` chips shown |
| 10.10 | Click chart | Modal opens; focus trapped; Esc closes; focus returns to trigger |
| 10.11 | Modal chart | Daily candles, volume, MA5/MA20 toggles, range 1M/3M/6M, tooltip OHLCV |
| 10.12 | MA calculation | Matches hand-computed simple moving averages |
| 10.13 | Row expand | Factor bars (supports 6-key and 8-key sets, unknown keys title-cased), composite score, rank, sub-exposure |
| 10.14 | Negative contributions | Diverging bars render left of zero |
| 10.15 | Caveats | Chips visible; count indicator on collapsed row |
| 10.16 | Disclaimer | Rendered when using `report_data` (A8) |
| 10.17 | Legacy report (`report_data` null) | Existing markdown view renders (A11) |
| 10.18 | Narrow viewport (< 768 px) | Card layout, no horizontal scroll |
| 10.19 | Export menu | Markdown and CSV call the export endpoint; PDF triggers print |
| 10.20 | Print stylesheet | Light theme, controls hidden, rows do not split across pages, header repeats |
| 10.21 | Theme toggle and system preference | Tokens switch; no unreadable contrast |
| 10.22 | Pipeline stepper | Shows each stage state; updates as the run progresses |
| 10.23 | Loading, empty, error states | Skeleton, "no holdings", retry message |
| 10.24 | Accessibility | Keyboard sorting, visible focus, table semantics, axe checks pass |

## 11. End-to-end (stub mode)

1. Create a theme and run the pipeline offline; confirm the kline node runs,
   `run_klines` has one row per holding, and the report has the table and
   `report_data`.
2. Force one ticker to fail; confirm "Chart unavailable", the report still
   completes, and the other charts render.
3. Disable `KLINE_ENABLED`; confirm the same degraded but complete result.
4. Open a legacy report; confirm it renders.
5. Export Markdown, CSV and print to PDF; open each.

## 12. Manual / visual QA

- Compare 3 tickers' mini chart, modal candles, first/last close and 6M return
  against a trusted charting site (allow for adjustment differences).
- Check a ticker with a recent split, a recent IPO, and a share-class ticker.
- Screenshot desktop (1440, 1024), tablet (768) and phone (390) in light and
  dark themes.
- Print preview on letter and A4.
- Read the weighted-return label with a compliance reviewer (D10).
- Confirm the source/as-of footer appears next to every chart.

## 13. Opt-in live tests

Mark with a pytest marker (for example `live_network`) and exclude from the
default run: real `stock-sdk` fetch for 3 tickers; assert bars returned,
schema valid, last bar within 7 days. Run before release and when the SDK
version changes.

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

All rows in §1–§11 pass, A1–A12 in `SPEC.md` are satisfied, §12 findings are
recorded in the PR description, the opt-in live test has passed once against
the pinned SDK version, and the documentation updates in `PLAN.md` Step 11 are
in the same PR.
