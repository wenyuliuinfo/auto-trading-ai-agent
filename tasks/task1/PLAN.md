# Task 1 — Implementation Plan

Companion to `SPEC.md` and `TEST_PLAN.md`. Each step is one reviewable commit.
Do not start step 2 until step 0 and 1 are done.

## Step 0 — Baseline before touching code

- Pick a fixed fixture universe (stub mode, 8–10 tickers) with the **legacy
  6-key weights**.
- Run `modeling_node` and save `ranked_list` (rank, `composite_score`,
  `factor_contributions`) as a golden snapshot under the test fixtures.
- This snapshot is the proof for acceptance criterion A1 (legacy themes
  unchanged).

## Step 1 — Resolve open decisions

Settle SPEC §11 (windows, `hist_vol` coexistence, weights, winsorization).
Record the answers at the top of `SPEC.md` and change its status from DRAFT.

## Step 2 — Raw factors (`integrations/factor_panel.py`)

1. Add constants `TRADING_DAYS`, `RISK_WINDOW`, `RISK_MIN_OBS`.
2. Add `compute_vol_3m`, `compute_turnover_3m`, `compute_amihud_3m`.
3. Append `vol_3m`, `turnover_3m`, `amihud_3m` to `RAW_FACTOR_COLUMNS`.
4. In `_row_for_ticker`, compute `shares_outstanding_est` from
   `fundamentals.market_cap / fundamentals.price` (NaN-safe) and populate the
   three new keys.
5. Unit tests for the helpers (TEST_PLAN §1).

Check: `_row_with_fallback` and `get_factor_panel` need no other change (they
already iterate `RAW_FACTOR_COLUMNS`). Confirm `_panel_from_rows` in
`modeling.py` yields NaN, not a crash, for legacy cached rows.

## Step 3 — Cache eligibility (`data/queries.py`)

1. Update `get_cached_factor_tickers` so a ticker is cache-eligible only if
   `pe_ratio` is non-null **and** rows exist for `vol_3m`, `turnover_3m`,
   `amihud_3m`.
2. Confirm `factor_panel.factor_name` has no enum/CHECK constraint; if it
   does, add an Alembic migration in this step.
3. Tests (TEST_PLAN §4).

## Step 4 — Scoring (`agents/modeling.py`)

1. Update `SCORING_FACTORS` and `LOWER_IS_BETTER`.
2. Extend `_build_scoring_frame`: raw `vol_3m`/`turnover_3m`/`amihud_3m`,
   then `volatility`, `log_turnover`, `neg_log_amihud`, `liquidity` per SPEC §5.
3. Add `_z_mean` (reuses `compute_factor_scores`; do not duplicate z-score
   math).
4. Do **not** modify `compute_factor_scores`, `combine_scores`, `rank`, or
   the sentiment path.
5. Tests (TEST_PLAN §2, §3). Re-run the Step 0 golden test; it must still
   pass with legacy weights.

## Step 5 — Config and API

1. Edit `config/factor_weights.yaml` (SPEC §6).
2. Update `config/theme_config.schema.json` (new keys optional).
3. Update the `POST /themes` sum validator to use a tolerance.
4. Tests (TEST_PLAN §5). Verify a legacy 6-key theme snapshot still loads and
   runs.

## Step 6 — Downstream consumers

1. Grep the repo for `SCORING_FACTORS`, `momentum_z`, `sentiment_z`,
   `factor_contributions`, and any hardcoded list of six factors (report
   generation, `src/web`, `evaluation/golden_set.py`).
2. Add display labels for `liquidity_z` and `volatility_z`.
3. Make sure a legacy theme (6 contributions) and a new theme (8) both render.

## Step 7 — Documentation

1. `MODELING_SKILL.md`: Step A factor table, Hard Rule 9 rewrite, test
   fixture list. Leave Rule 8 unchanged (sentiment still LLM-derived).
2. `ARCHITECTURE.md`: decision-log entry (policy change, cache rule, replay
   limitation, legacy vs new theme non-comparability).
3. Update the header comment of `config/factor_weights.yaml` only if the
   policy text needs it.
4. Add new terms (turnover, Amihud, realized volatility) to `CONTEXT.md`.

## Step 8 — Verification

Run the repo's standard checks: `pnpm lint`, `pnpm lint:api`,
`pnpm test:api`, `pnpm --dir src/web test`, `pnpm check:structure`,
`pnpm build`. Then the manual checks in TEST_PLAN §8.

## Step 9 — Rollout

1. Deploy. Existing themes are unaffected (frozen snapshots).
2. Create 3–5 new themes across different sectors; inspect the new factor
   columns and contributions.
3. After enough new runs exist, run `scripts/shadow_compare.py` on **post-
   deploy** runs to compare current vs proposed weights. Adjust the YAML
   if needed via a separate reviewed change.
4. Review factor correlations (TEST_PLAN §8) and revisit weights.

## Rollback

Revert `config/factor_weights.yaml` to the 6-key version: new themes go back
to 6 factors. The extra raw columns and their cached rows are harmless and
can stay. Themes already created with 8 keys keep working because the code
path supports both. No data migration to undo.

## Risks

| Risk | Mitigation |
|---|---|
| Cached pre-deploy rows score new factors as NaN | Step 3 eligibility rule + test |
| Legacy themes drift | Step 0 golden snapshot, run on every commit |
| UI hardcodes six factors | Step 6 grep + rendering check |
| Outlier-dominated z-scores | Log transform (SPEC §5) |
| Double influence with Trader screens | Small weights, documented in Rule 9 |
