# Task 1 — Test Plan

Companion to `SPEC.md` (acceptance criteria A1–A8) and `PLAN.md`. All unit
tests must be offline and deterministic (stub mode or synthetic series; no
vendor calls, no LLM calls).

## 1. Raw helpers (`integrations/factor_panel.py`)

| # | Case | Expected |
|---|---|---|
| 1.1 | `compute_vol_3m` on constant price | `0.0` |
| 1.2 | Alternating +1% / −1% closes over 64 points | Matches hand-computed `std(ddof=1) * sqrt(252)` |
| 1.3 | Only 30 valid returns | `NaN` |
| 1.4 | Exactly `RISK_MIN_OBS` valid returns | Value, not `NaN` (boundary) |
| 1.5 | Series longer than 64 points | Only the last 63 returns are used (change an early price, result unchanged) |
| 1.6 | Prior close is 0 or NaN inside the window | No `inf`; affected return dropped |
| 1.7 | `compute_turnover_3m` with known volume and shares | `mean(volume)/shares` |
| 1.8 | `shares_outstanding` is NaN, 0, or negative | `NaN` |
| 1.9 | Volume contains zero days | Zeros are included in the mean |
| 1.10 | Volume series empty or all NaN (Stooq without Volume) | `NaN` |
| 1.11 | `compute_amihud_3m` with hand-computed values | Matches `mean(|r|/(close*volume))*1e6` |
| 1.12 | Zero-volume days inside the window | Excluded; result finite |
| 1.13 | All volume zero | `NaN`, never `inf` |
| 1.14 | Fewer than `RISK_MIN_OBS` valid days | `NaN` |
| 1.15 | Recently listed ticker (<40 days of history) | All three helpers return `NaN`, no `IndexError` |
| 1.16 | `_row_for_ticker` with `market_cap` or `price` missing | `turnover_3m` is `NaN`; other columns unaffected |
| 1.17 | `_row_with_fallback` on forced exception | Row contains the three new columns as `NaN` |
| 1.18 | `RAW_FACTOR_COLUMNS` | Contains the three new names exactly once |

## 2. Scoring frame (`agents/modeling.py::_build_scoring_frame`)

| # | Case | Expected |
|---|---|---|
| 2.1 | Panel with the new columns | Frame has `volatility` and `liquidity` columns |
| 2.2 | Direction, volatility | Lower `vol_3m` gets higher `volatility_z` (A3) |
| 2.3 | Direction, turnover | Higher `turnover_3m`, other inputs equal, gets higher `liquidity_z` |
| 2.4 | Direction, Amihud | Lower `amihud_3m`, other inputs equal, gets higher `liquidity_z` |
| 2.5 | Scale invariance | Multiplying all `turnover_3m` by 1000 leaves `liquidity_z` unchanged (log then z) |
| 2.6 | One sub-signal `NaN` | `liquidity` equals the other sub-signal's z-score for that ticker |
| 2.7 | Both sub-signals `NaN` | `liquidity` is `NaN`, not 0 (Hard Rule 6) |
| 2.8 | `turnover_3m` or `amihud_3m` ≤ 0 | Treated as `NaN` (no log warnings, no `-inf`) |
| 2.9 | Panel lacks the new columns entirely (legacy cache) | No exception; `volatility`/`liquidity` are `NaN`; other factors unchanged |
| 2.10 | Constant `vol_3m` across universe | `volatility_z` is 0 for non-NaN names (existing constant-column rule) |
| 2.11 | Single-candidate universe | Documented behavior (same as existing factors), no exception before `rank` |
| 2.12 | `sentiment` column | Byte-identical to pre-change output (sentiment untouched) |

## 3. Composite and ranking

| # | Case | Expected |
|---|---|---|
| 3.1 | **A1 golden test**: legacy 6-key weights, Step 0 fixture | `ranked_list` identical to the saved snapshot |
| 3.2 | 8-key weights (SPEC §6) | `composite_score` equals hand-computed weighted sum; no null scores when inputs complete (A2) |
| 3.3 | `factor_contributions` for 8-key weights | Contains `liquidity_z` and `volatility_z` for every ticker |
| 3.4 | Missing `theme_config["factor_weights"]` | Still raises (Hard Rule 2) |
| 3.5 | Weights not summing to 1.0 | `combine_scores` does not renormalize (existing test stays green) |
| 3.6 | Determinism | Two identical runs produce identical output (Hard Rule 4) |
| 3.7 | Name with `NaN` in one new factor | Other names' z-scores computed as if that name were absent from that column (Hard Rule 6) |
| 3.8 | Persisted panel rows | `vol_3m`, `turnover_3m`, `amihud_3m` present as raw rows; `liquidity`/`volatility` persisted with `raw_value` and `z_score` |

## 4. Cache (`data/queries.py`, Hard Rule 10)

| # | Case | Expected |
|---|---|---|
| 4.1 | Ticker cached today with new-column rows | Eligible, reused |
| 4.2 | Ticker cached today from before deploy (no new-column rows) | Not eligible, refetched (A6) |
| 4.3 | Cached row has new-column rows with null values (new IPO) | Eligible (row existence, not non-null) |
| 4.4 | Cached row has null `pe_ratio` | Still ineligible (existing rule) |
| 4.5 | Two consecutive same-day runs | Second run's ranking equals the first (A5) and has no null `composite_score` |

## 5. Config, schema, API

| # | Case | Expected |
|---|---|---|
| 5.1 | `config/factor_weights.yaml` loads | Keys are exactly the eight expected names |
| 5.2 | Sum of weights | `abs(sum - 1.0) < 1e-9` (A7) |
| 5.3 | Every weight key maps to a scoring column | No key without a column in the scoring frame |
| 5.4 | `theme_config.schema.json` | Accepts a legacy 6-key snapshot and an 8-key snapshot |
| 5.5 | `POST /themes` | Persisted `theme.config.factor_weights` has 8 keys copied verbatim |
| 5.6 | `POST /themes` with `factor_weights` in the body | 422, unchanged behavior |
| 5.7 | Validator with weights summing to 1.0 via float decimals | Accepted (tolerance) |
| 5.8 | Validator with weights summing to 0.9 | Rejected |

## 6. Downstream

| # | Case | Expected |
|---|---|---|
| 6.1 | Report/web renders a legacy theme (6 contributions) | No error, no blank columns |
| 6.2 | Report/web renders a new theme (8 contributions) | Both new factors labeled |
| 6.3 | `evaluation/golden_set.py` | Still passes or is updated intentionally |

## 7. End-to-end (stub mode)

1. Create a theme; confirm the snapshot has 8 weights.
2. Run the pipeline; confirm the ranked list has no null `composite_score`.
3. Re-run same day (cache hit); confirm identical ranking (A5).
4. Run a legacy-snapshot theme; confirm identical to the pre-change output (A1).

## 8. Manual / analytical validation (post-deploy)

- Correlation matrix across the candidate universe of `volatility_z`,
  `liquidity_z`, `momentum_z`, and log market cap. Flag any pair above about
  0.7.
- Spot-check three tickers by hand against a charting tool: `vol_3m`
  (annualized), average daily turnover, and Amihud order of magnitude.
- Review five rankings for surprises: does a very illiquid or very volatile
  name still reach the top 3? If so, check caveats and the screens.
- After enough forward data accumulates, compare rank IC of the composite
  with and without the two factors using `scripts/shadow_compare.py` on
  post-deploy runs (pre-deploy runs cannot be replayed with the new factors).

## 9. Commands

```
pnpm lint
pnpm lint:api
pnpm test:api
pnpm --dir src/web test
pnpm check:structure
pnpm build
```

## 10. Exit criteria

All rows in §1–§7 pass, A1–A8 in `SPEC.md` are satisfied, the §8 manual
review is recorded in the PR description, and the docs listed in `PLAN.md`
Step 7 are updated in the same PR.
