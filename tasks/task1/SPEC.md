# Task 1 — Add `volatility` and `liquidity` scored factors

Status: DRAFT for review. Owner decisions are listed in §11.

## 1. Goal and non-goals

**Goal.** Add two new cross-sectionally z-scored factors to the Modeling
agent's composite score:

- `volatility` — lower 3-month realized volatility scores higher.
- `liquidity` — higher turnover and lower Amihud illiquidity score higher.

**Non-goals (explicitly out of scope).**

- **No change to `sentiment`.** It stays the Analyst's `sentiment_label`
  mapped through `SENTIMENT_MAP`. MODELING_SKILL.md Hard Rule 8 is unchanged.
- No change to how `thematic`, `growth`, `quality`, `valuation`, `momentum`
  are computed (including the existing raw-scale `_nanmean` grouping).
- No change to the Trader agent's hard screens (`adv`, `market_cap`,
  `beta`, `hist_vol` keep their current meaning and columns).
- No new vendor, endpoint, or API call. Both factors derive from the
  close/volume history and market cap already fetched per ticker.
- No change to the `PriceHistory` shape (close + volume are sufficient).
- No user-supplied weights (Hard Rule 2 stands).

## 2. Policy change: Hard Rule 9

MODELING_SKILL.md Hard Rule 9 currently says liquidity/risk inputs are
screening inputs, not scored inputs, unless changed by a deliberate,
reviewed global policy decision. **This task is that decision.** It must be
recorded in the same PR:

- Rewrite Rule 9: `adv`, `market_cap`, `beta`, `hist_vol` remain screening
  inputs; `vol_3m`, `turnover_3m`, `amihud_3m` are scored inputs feeding the
  `volatility` and `liquidity` factors.
- Add a decision-log entry to ARCHITECTURE.md (rationale in §3).
- Accepted trade-off: a name can be both scored on liquidity/volatility and
  screened on `adv`/`hist_vol` by the Trader. Weights are kept small (§6) to
  limit this double influence.

## 3. Rationale and direction of each factor

| Factor | Direction | Rationale |
|---|---|---|
| `volatility` | lower is better | Low-volatility anomaly; also reduces basket risk. Thematic universes are volatile by nature, so this is a *relative* tilt within the candidate universe. |
| `liquidity` | more liquid is better | This is a **tradability** factor, not an alpha claim. Academic evidence shows illiquid stocks can earn a premium; we deliberately trade that off for implementability. |

Expected correlations to check after deploy: `volatility` vs `momentum`
(likely negative), `liquidity` vs `market_cap` (likely positive, Amihud is
size-related).

## 4. Raw column definitions (Step A, `integrations/factor_panel.py`)

Constants:

```python
TRADING_DAYS = 252
RISK_WINDOW = 63        # ~3 months of trading days
RISK_MIN_OBS = 40       # minimum valid observations inside the window
```

| Raw column | Definition | Notes |
|---|---|---|
| `vol_3m` | `std(daily simple returns, last 63 days, ddof=1) * sqrt(252)` | Annualized to match `hist_vol` units. `ddof=1` matches pandas default used by `hist_vol`; Hard Rule 5 (`ddof=0`) governs z-scoring only. |
| `turnover_3m` | `mean(volume, last 63 days) / shares_outstanding_est` | Daily turnover fraction (0.008 = 0.8%/day). Zero-volume days are included. |
| `amihud_3m` | `mean(abs(r_t) / (close_t * volume_t)) * 1e6` over valid days in last 63 | Days with `volume <= 0` or undefined return are excluded (never `inf`). Higher = less liquid. |

`shares_outstanding_est = fundamentals.market_cap / fundamentals.price`
(NaN if either is missing or `price <= 0`). This avoids changing
`fundamentals.py`. See §9 for the dual-class limitation.

Reference helpers (pure functions, no I/O, no LLM — Hard Rule 8):

```python
def compute_vol_3m(close: pd.Series) -> float:
    window = close.tail(RISK_WINDOW + 1)
    returns = window.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < RISK_MIN_OBS:
        return float("nan")
    return float(returns.std() * TRADING_DAYS**0.5)


def compute_turnover_3m(volume: pd.Series, shares_outstanding: float) -> float:
    vol = volume.tail(RISK_WINDOW).dropna()
    if len(vol) < RISK_MIN_OBS or not (shares_outstanding > 0):
        return float("nan")
    return float(vol.mean() / shares_outstanding)


def compute_amihud_3m(close: pd.Series, volume: pd.Series) -> float:
    frame = pd.concat([close, volume], axis=1, keys=["c", "v"]).tail(RISK_WINDOW + 1)
    ret = frame["c"].pct_change().abs()
    dollar_vol = frame["c"] * frame["v"]
    ratio = (ret / dollar_vol).where(dollar_vol > 0)
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
    if len(ratio) < RISK_MIN_OBS:
        return float("nan")
    return float(ratio.mean() * 1e6)
```

`RAW_FACTOR_COLUMNS` gains `"vol_3m"`, `"turnover_3m"`, `"amihud_3m"`
(append after `hist_vol`). `_row_for_ticker` populates them;
`_row_with_fallback` already NaN-fills every column in the list, so a failed
ticker degrades correctly with no extra code.

**Raw values stay raw and interpretable in the panel.** Logs and sign flips
happen in Step B input construction (§5), not in `factor_panel.py`.

## 5. Scoring inputs (`agents/modeling.py`)

Constants:

```python
SCORING_FACTORS = [
    "thematic", "growth", "quality", "valuation",
    "momentum", "sentiment", "liquidity", "volatility",
]
LOWER_IS_BETTER = {"pe_ratio", "ev_ebitda", "debt_to_ebitda", "vol_3m", "amihud_3m"}
```

(In the reviewed file `LOWER_IS_BETTER` is documentation only; the flips are
applied inline in `_build_scoring_frame`. Keep that pattern and keep the
constant in sync.)

`_build_scoring_frame` adds, per ticker, the raw values `vol_3m`,
`turnover_3m`, `amihud_3m` (via the existing `value()` helper, which already
returns NaN for absent columns — important for legacy cached rows). After the
DataFrame is built:

```python
frame["volatility"] = -frame["vol_3m"]                       # sign-flip here
frame["log_turnover"] = np.log(frame["turnover_3m"].where(frame["turnover_3m"] > 0))
frame["neg_log_amihud"] = -np.log(frame["amihud_3m"].where(frame["amihud_3m"] > 0))
frame["liquidity"] = _z_mean(frame, ["log_turnover", "neg_log_amihud"])
```

```python
def _z_mean(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Z-score each sub-signal with compute_factor_scores (ddof=0, NaN-omit,
    constant column -> 0), then average available z-scores. All-NaN -> NaN."""
    z = compute_factor_scores(frame[cols], cols)
    return z[[f"{c}_z" for c in cols]].mean(axis=1, skipna=True)
```

Design notes:

- **Why log:** turnover and Amihud are heavily right-skewed; a raw z-score
  would be dominated by one outlier. Logs are a fixed transform (deterministic,
  Hard Rule 4). Non-positive values become NaN, never zero (Hard Rule 6).
- **Why z-then-average for `liquidity`:** the two sub-signals have different
  units. This differs from the existing raw-scale `_nanmean` used by
  `growth`/`quality`/`valuation`; do **not** change those here (follow-up
  candidate).
- **Graceful degradation:** if one sub-signal is NaN, `liquidity` uses the
  other; if both are NaN, `liquidity` is NaN and that name's z-score is NaN,
  excluded from μ/σ.
- `liquidity` is z-scored again by `compute_factor_scores` in
  `modeling_node`; that final standardization is intentional.
- The working columns (`log_turnover`, `neg_log_amihud`) are not weights keys
  and are not persisted. `vol_3m`/`turnover_3m`/`amihud_3m` are persisted
  automatically by the existing `RAW_FACTOR_COLUMNS` loop.
- `MODELING_CAVEATS_PROMPT` needs no change.

## 6. Weights (`config/factor_weights.yaml`) — proposal

| Key | Current | Proposed |
|---|---|---|
| `thematic_z` | 0.30 | 0.27 |
| `growth_z` | 0.20 | 0.18 |
| `quality_z` | 0.15 | 0.13 |
| `valuation_z` | 0.15 | 0.13 |
| `momentum_z` | 0.10 | 0.09 |
| `sentiment_z` | 0.10 | 0.10 (unchanged) |
| `liquidity_z` | — | 0.05 |
| `volatility_z` | — | 0.05 |
| **Sum** | 1.00 | **1.00** |

These are starting values, not conclusions. The 5% weights reflect that both
are tradability/risk factors and the Trader already screens on related inputs.
Process (per the file's own header): edit the YAML, run
`scripts/shadow_compare.py` on recent runs, review, then merge. See §8 for
the replay limitation.

The weights validator must compare the sum with a tolerance (e.g. `1e-9`);
a naive `== 1.0` can fail on decimal sums.

## 7. Config, schema, and API

- `config/factor_weights.yaml`: add `liquidity_z`, `volatility_z`; update the
  values above; leave the header policy text intact.
- `config/theme_config.schema.json`: allow both new keys in
  `factor_weights`. **Keep them optional in the stored-shape schema** so
  legacy 6-key snapshots still validate. (Verify current `required` /
  `additionalProperties` settings; not reviewed when drafting.)
- `POST /themes`: copies all keys from the YAML verbatim (now 8). Unchanged
  logic; add tests. `config/theme_create_request.schema.json` still has no
  `factor_weights` field and still 422s if one is submitted.

## 8. Cache and backward compatibility

- **Legacy themes keep their 6-key snapshot** and keep scoring exactly as
  before. `modeling_node` derives `factor_cols` from the persisted weights,
  so extra columns in the scoring frame are simply unused. Their
  `ranked_list` must be identical to pre-change output (acceptance test A1).
- **New themes** get 8 keys. `_build_scoring_frame` must always emit
  `liquidity` and `volatility` columns, or `compute_factor_scores` raises
  `KeyError` for new themes.
- **Cache eligibility (`data/queries.get_cached_factor_tickers`, Hard Rule
  10).** Same-day rows cached before deploy have no `vol_3m`/`turnover_3m`/
  `amihud_3m` rows and would silently score as NaN. Require that rows for
  those three `factor_name`s *exist* for the ticker (existence, not non-null,
  so a genuine new IPO with null values is not refetched forever), in
  addition to the existing non-null `pe_ratio` rule.
- **No DB migration expected:** `factor_panel` is stored as
  `(ticker, as_of_date, factor_name, raw_value, z_score)` rows. Verify there
  is no enum or CHECK constraint on `factor_name`.
- **`scripts/shadow_compare.py` cannot replay pre-deploy runs with the new
  factors**, because their persisted panels lack the new raw columns. Compare
  using runs created after deploy.
- Rankings from legacy themes and new themes are not comparable (different
  factor sets). Note this in the ARCHITECTURE.md decision log.

## 9. Known limitations

- **Dual-class shares** (e.g. GOOG/GOOGL): market cap covers all classes but
  volume is per listing, so turnover is understated.
- ADRs and foreign listings: share counts and volume may not align.
- Stooq fallback may return no volume; both liquidity sub-signals become NaN
  for that ticker (handled, but it will lose the factor).
- `market_cap` and `price` come from the fundamentals call and may be
  timestamped differently from the price history.
- 63-day windows are noisy for small universes; z-scores over N < ~10 names
  are weak signals.
- Amihud correlates with market cap; the factor partly re-expresses size.

## 10. Acceptance criteria

- **A1.** For a fixed fixture with the legacy 6-key weights, `ranked_list`
  (order, `composite_score`, `factor_contributions`) is identical before and
  after the change.
- **A2.** With 8-key weights, every ranked name has non-null
  `composite_score` when inputs are complete, and `factor_contributions`
  contains `liquidity_z` and `volatility_z`.
- **A3.** Direction: lower `vol_3m` → higher `volatility_z`; higher
  `turnover_3m` → higher `liquidity_z`; lower `amihud_3m` → higher
  `liquidity_z`.
- **A4.** Missing/short data yields NaN (never 0, `inf`, or an exception)
  and does not alter other names' μ/σ.
- **A5.** A second same-day run (cache hit) reproduces the first run's
  ranking exactly.
- **A6.** Pre-deploy cached rows are not reused for new-factor scoring.
- **A7.** `factor_weights.yaml` sums to 1.0 within tolerance; schema accepts
  both 6-key and 8-key snapshots.
- **A8.** Docs updated (§12) and the full check suite passes.

## 11. Open decisions (recommended default in bold)

1. Window length: **63 days for all three** vs. 20 days for turnover to match
   `adv`.
2. Keep `hist_vol` (screen, ~2y window) alongside `vol_3m` (scored):
   **yes, keep both.**
3. Final weights: **§6 proposal, adjusted after shadow comparison.**
4. Apply a winsorization clip on sub-z-scores: **no, logs only for now.**
5. Fix the existing raw-scale `_nanmean` grouping in `growth`/`quality`/
   `valuation`: **separate follow-up task.**

## 12. Files touched

| File | Change |
|---|---|
| `integrations/factor_panel.py` | 3 helpers, 3 new columns, shares estimate |
| `agents/modeling.py` | constants, `_build_scoring_frame`, `_z_mean` |
| `data/queries.py` | cache eligibility for new columns |
| `config/factor_weights.yaml` | 2 new keys, rebalanced |
| `config/theme_config.schema.json` | allow new keys (optional) |
| `app/api/themes.py` (or shared loader) | tolerance-based sum check, tests |
| Report/web/evaluation code | grep `SCORING_FACTORS`, `momentum_z`, `sentiment_z`, `factor_contributions`; add labels for the two new factors |
| `MODELING_SKILL.md` | Step A factor table, Rule 9, test-fixture list |
| `ARCHITECTURE.md` | decision-log entry (§2, §8) |
