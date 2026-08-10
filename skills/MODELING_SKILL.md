---
name: modeling-agent-scoring
description: Use this skill whenever writing, modifying, reviewing, or debugging code in app/agents/modeling.py, the get_factor_panel integration modules, or any function related to factor normalization, composite scoring, or ranking of the candidate universe. Covers the canonical implementations of get_factor_panel (Step A), compute_factor_scores (Step B), combine_scores (Step C), and rank (Step D), plus the hard rules for keeping this code deterministic and auditable. Do not use this skill for Trader agent basket construction logic or Analyst agent news/text analysis (see ANALYST_SKILL.md).
---

# Modeling Agent Scoring — Canonical Implementation & Rules

This skill is the single source of truth for **how** Steps A/B/C/D of the
Modeling agent are implemented. `ARCHITECTURE.md` §4 and §7 explain *why*
this logic must stay deterministic; this file is what a coding agent
should load and follow *while writing the actual code*.

## Where this logic lives (per `CONVENTIONS.md` §2)

`get_factor_panel` calls external vendor APIs, so its fetch/orchestration
code lives in `integrations/`. `compute_factor_scores`, `combine_scores`,
and `rank` are pure math with zero I/O, so they stay directly in
`agents/modeling.py` alongside the node function and the narrow LLM call
that produces `caveats`:

```
app/
├── integrations/
│   ├── fundamentals.py      # fetch_fundamentals (FMP + Finnhub)
│   ├── prices.py            # fetch_price_history (FMP EOD + yfinance + Stooq)
│   └── factor_panel.py      # get_factor_panel: orchestrates the two above,
│                             #   computes rsi/beta/hist_vol, returns the raw
│                             #   (pre-z-score) factor DataFrame — Step A
├── agents/
│   └── modeling.py          # compute_factor_scores / combine_scores / rank
│                             #   (Steps B/C/D, pure functions) + the narrow
│                             #   LLM call for caveats + modeling_node
```

`agents/modeling.py` imports `get_factor_panel` from `integrations/`; it
never calls FMP/Finnhub/yfinance/Stooq directly. Conversely,
`integrations/factor_panel.py` never does any z-scoring, weighting, or
ranking — that math stays in `agents/modeling.py` per Hard Rule 1.

## Hard rules (do not violate these while coding here)

1. **Never let an LLM call replace or override any function in this file.**
   The Modeling agent's LLM call is only for converting `thematic_relevance_score`/
   `sentiment_label` to numeric inputs and writing the `caveats` field —
   nothing here.
2. **Factor weights are never user input, in any form, and never a Python
   constant `modeling.py` reads directly.** The single source of truth is
   `config/factor_weights.yaml` — a hand-maintained, ops/quant-owned file,
   the same pattern as `config/sub_exposure_etf_map.yaml`. It is loaded
   **exactly once in the entire codebase**, by the `POST /themes` handler
   (`api-engineer`'s scope) at theme-creation time, and copied verbatim
   into `theme.config.factor_weights`. There is no API field, no UI
   control, and no code path anywhere that lets a caller supply or
   override weights — `config/theme_create_request.schema.json` (the
   actual `POST /themes` request schema) has no `factor_weights` field at
   all, and rejects the request with a 422 if one is submitted, rather
   than silently ignoring it.
   **`modeling_node` never reads the YAML file and never references any
   weights constant** — it reads only the already-persisted
   `theme_config["factor_weights"]` and **raises** if that key is
   missing, rather than falling back to anything. This is what makes
   weights real, persisted, per-theme data (`ARCHITECTURE.md` §2.1) —
   editable by changing the YAML file for *future* themes, diffable via
   `scripts/shadow_compare.py`, and fully decoupled from both user input
   and a code redeploy. See `config/theme_config.schema.json` for the
   stored shape and `config/theme_create_request.schema.json` for
   confirmation of what's actually user-settable (`screens`,
   `weighting_scheme`, `validator_enabled` — deliberately not weights).
3. **Sign-flip "lower is better" factors (e.g. P/E) before calling
   `compute_factor_scores`** — never inside it. Keep the sign convention
   ("higher z-score is always better," after flipping) enforced at the
   call site, documented via a `LOWER_IS_BETTER` constant, not scattered
   `if` checks.
4. **Given the same input DataFrame and weights, output must be bit-for-bit
   reproducible.** No randomness, no non-deterministic ordering. If you
   add multiprocessing/parallelism anywhere in this path, guarantee it
   doesn't reorder rows nondeterministically before the final `rank` call.
5. **Population standard deviation (`ddof=0`), matching `scipy.stats.zscore`'s
   default** — do not silently switch to sample std (`ddof=1`) in a
   refactor; it rescales every z-score by a constant and will look like a
   bug to anyone diffing against this skill's reference formulas.
6. **Missing values are excluded from `μ`/`σ`, never treated as zero.**
   Use `nan_policy="omit"` (or the equivalent explicit `.dropna()` before
   computing mean/std) — silently imputing zero for a missing factor
   value will bias that factor's mean and corrupt every other stock's
   z-score on that column.
7. **Tie-breaking in `rank` is currently incidental (input row order),
   not a meaningful secondary sort key.** If a change requires
   deterministic tie-breaking (e.g. "break ties by thematic relevance"),
   add an explicit secondary sort key — do not rely on DataFrame row
   order to encode a decision.
8. **`get_factor_panel` never calls an LLM.** Every value it returns is
   computed from vendor API data via plain arithmetic — see Step A below.
   `thematic_relevance_score` and `sentiment_label` are the *only* LLM-
   derived inputs anywhere in this pipeline stage, and they arrive
   pre-computed from the Analyst agent (`ANALYST_SKILL.md`); this file
   only converts them to numeric form (see Step A, "LLM-derived factors").
9. **Liquidity/risk factors (`adv`, `market_cap`, `beta`, `hist_vol`) are
   screening inputs for the Trader agent, not scored composite inputs by
   default.** Do not add them to `config/factor_weights.yaml` unless
   that's a deliberate, reviewed global policy change — conflating "used
   to exclude" with "used to rank" silently changes what the composite
   score means for every theme created after the change. There is no
   per-theme opt-in for this; the weights file is global (Hard Rule 2).
10. **Cache factor panel rows in the `factor_panel` table before
    recomputing.** Same-day requests for a ticker already fetched should
    reuse the stored row rather than re-hitting FMP/Finnhub/yfinance/Stooq —
    required given free-tier rate limits (`ARCHITECTURE.md` §6). A ticker
    is only cache-eligible when its raw `pe_ratio` row has a non-null value;
    all-null rows from a failed fetch must be retried, never reused.
11. **`fundamentals.py` and `prices.py` each normalize their multi-source
    output to one shape before returning.** FMP and Finnhub have
    different field names/units for the same underlying figure; so do
    FMP EOD, yfinance and Stooq for price history. `factor_panel.py` should never
    need to know which underlying vendor supplied a given value beyond
    what's preserved in a `source` field on the raw record.

## Step A — Factor Definitions & Calculation

Seven factors feed the pipeline. Two are LLM-derived and arrive already
computed from the Analyst agent; the other five (plus the liquidity/risk
screening inputs) are computed here, in code, from free-tier vendor data.

### LLM-derived factors (computed by the Analyst agent, not here)

| Factor | Value | Source |
|---|---|---|
| `thematic_z` (raw: `thematic_relevance_score`) | 1-5 score from the Analyst's read of news/filing text | GDELT/SerpApi Google News text, SEC EDGAR business description |
| `sentiment_z` (raw: `sentiment_label`) | Mapped `bearish=-1, neutral=0, bullish=1`, or a deterministic tone score (see note below) | GDELT/Google News tone |

```python
SENTIMENT_MAP = {"bearish": -1.0, "neutral": 0.0, "bullish": 1.0}

def sentiment_label_to_numeric(label: str) -> float:
    return SENTIMENT_MAP[label]

# Deterministic alternative (no LLM), if preferred for this factor specifically:
def deterministic_sentiment_score(gdelt_avg_tone: float) -> float:
    """Normalize GDELT tone (-100 to +100, typical article range roughly
    -10 to +10) to a -1..1 score."""
    normalized_tone = max(min(gdelt_avg_tone / 10.0, 1.0), -1.0)
    return normalized_tone
```

### `integrations/fundamentals.py`

```python
def fetch_fmp_fundamentals(ticker: str) -> dict:
    """FMP stable API. Primary fundamentals source; combines quote,
    ratios-ttm, key-metrics-ttm, and annual statements."""
    ...

def fetch_finnhub_fundamentals(ticker: str) -> dict:
    """Finnhub free tier. Used to fill gaps when FMP is missing a field,
    or as the primary source if FMP's daily quota is exhausted."""
    ...

def _normalize_fundamentals(raw: dict, source: str) -> "Fundamentals":
    """Common shape: price, diluted_eps_ttm, market_cap, total_debt, cash,
    ebitda_ttm, revenue_ttm, revenue_ttm_prior_year, diluted_eps_ttm_prior_year,
    net_income_ttm, shareholders_equity, gross_profit_ttm, free_cash_flow_ttm."""
    ...

def fetch_fundamentals(ticker: str) -> "Fundamentals":
    """Tries FMP first, falls back to Finnhub per-field on gaps
    (Hard Rule 11) — factor_panel.py never sees which vendor supplied
    which field, only the normalized Fundamentals object."""
    ...
```

### `integrations/prices.py`

```python
def fetch_yfinance_prices(ticker: str, lookback_days: int) -> "PriceHistory":
    """Fallback after FMP EOD. Unofficial/ToS gray area — acceptable for
    internal use per ARCHITECTURE.md §6; revisit before commercial use."""
    ...

def fetch_stooq_prices(ticker: str, lookback_days: int) -> "PriceHistory":
    """Last-resort fallback if FMP EOD and yfinance are unavailable."""
    ...

def fetch_price_history(ticker: str, lookback_days: int = 504) -> "PriceHistory":
    """Normalized close/volume series (Hard Rule 11), FMP EOD primary,
    yfinance fallback, Stooq last resort. 504 trading days (~2yr) covers
    beta and momentum lookbacks below."""
    ...
```

### `integrations/factor_panel.py` — `get_factor_panel(tickers)`

```python
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from app.integrations.fundamentals import fetch_fundamentals
from app.integrations.prices import fetch_price_history

def get_factor_panel(tickers: list[str]) -> pd.DataFrame:
    """Build the raw (pre-z-score) factor panel for the candidate universe.
    Every column here is plain arithmetic on vendor data — no LLM call
    (Hard Rule 8). Check factor_panel table for a fresh cached row per
    ticker before calling any vendor API (Hard Rule 10). Tickers run in a
    bounded thread pool; SPY is fetched once and shared for beta."""
    benchmark_history = fetch_price_history("SPY", lookback_days=504)

    def fetch_row(ticker: str) -> dict:
        fundamentals = fetch_fundamentals(ticker)
        prices = fetch_price_history(ticker)
        return {
            "ticker": ticker,
            # --- Valuation (LOWER_IS_BETTER, sign-flip in agents/modeling.py) ---
            "pe_ratio": fundamentals.price / fundamentals.diluted_eps_ttm,
            "ev_ebitda": (fundamentals.market_cap + fundamentals.total_debt
                          - fundamentals.cash) / fundamentals.ebitda_ttm,
            "ps_ratio": fundamentals.market_cap / fundamentals.revenue_ttm,
            # --- Growth ---
            "revenue_growth_yoy": (fundamentals.revenue_ttm
                                   / fundamentals.revenue_ttm_prior_year - 1),
            "eps_growth_yoy": (fundamentals.diluted_eps_ttm
                               / fundamentals.diluted_eps_ttm_prior_year - 1),
            # --- Quality ---
            "roe": fundamentals.net_income_ttm / fundamentals.shareholders_equity,
            "gross_margin": fundamentals.gross_profit_ttm / fundamentals.revenue_ttm,
            "debt_to_ebitda": fundamentals.total_debt / fundamentals.ebitda_ttm,  # LOWER_IS_BETTER
            "fcf_conversion": fundamentals.free_cash_flow_ttm / fundamentals.net_income_ttm,
            # --- Momentum ---
            "momentum_6m": prices.close[-1] / prices.close[-126] - 1,   # ~126 trading days
            "rsi_14": compute_rsi(prices.close, window=14),
            "pct_from_52wk_high": prices.close[-1] / prices.close[-252:].max() - 1,
            # --- Liquidity/risk (screening inputs, see Hard Rule 9) ---
            "adv": (prices.volume[-20:] * prices.close[-20:]).mean(),
            "market_cap": fundamentals.market_cap,
            "beta": compute_beta(prices.close, benchmark_history=benchmark_history),
            "hist_vol": prices.close.pct_change().std() * (252 ** 0.5),  # annualized;
                                                                          # substitutes for
                                                                          # implied vol, which
                                                                          # free tiers lack
        }

    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(fetch_row, tickers))
    return pd.DataFrame(rows)


def compute_rsi(close: pd.Series, window: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return (100 - 100 / (1 + rs)).iloc[-1]


def compute_beta(
    close: pd.Series,
    benchmark: str = "SPY",
    lookback_days: int = 504,
    benchmark_history=None,
) -> float:
    stock_returns = close.pct_change().dropna()[-lookback_days:]
    bench = benchmark_history or fetch_price_history(benchmark, lookback_days=lookback_days)
    bench_returns = bench.close.pct_change().dropna()[-lookback_days:]
    cov = stock_returns.cov(bench_returns)
    var = bench_returns.var()
    return cov / var
```

**Notes on this step:**
- `pe_ratio`, `ev_ebitda`, and `debt_to_ebitda` are the `LOWER_IS_BETTER`
  factors — sign-flip is applied by `agents/modeling.py` before calling
  `compute_factor_scores`, not here.
- `ps_ratio` is available but not included in `config/factor_weights.yaml`'s
  valuation weighting by default — if that global policy is changed to
  use it instead of/alongside `pe_ratio`/`ev_ebitda`, sign-flip it the
  same way (lower P/S is better).
- `adv`, `market_cap`, `beta`, `hist_vol` are computed here but consumed
  by the **Trader** agent's hard screens, not `combine_scores`, per Hard
  Rule 9 — don't wire them into `config/factor_weights.yaml` without a
  deliberate, reviewed global policy decision.
- Estimate-revision trend (mentioned in the original factor table) is
  intentionally omitted from this reference implementation — free-tier
  FMP/Finnhub coverage of consensus estimate revisions is thin/
  inconsistent; treat it as a `None`/missing value (per Hard Rule 6,
  excluded from `μ`/`σ`, not defaulted to 0) rather than approximating it.

## Reference implementation — Steps B/C/D (`agents/modeling.py`)

### Step B — Normalize

```python
from scipy.stats import zscore
import pandas as pd

# Factors where a LOWER raw value is better — sign-flip before scoring.
# Matches Step A's factor definitions above; add ps_ratio here too if a
# theme's config includes it in place of/alongside pe_ratio or ev_ebitda.
LOWER_IS_BETTER = {"pe_ratio", "ev_ebitda", "debt_to_ebitda"}

def compute_factor_scores(df: pd.DataFrame, factor_cols: list[str]) -> pd.DataFrame:
    """Cross-sectional z-score each factor within the candidate universe.

    Missing values are excluded from mean/std (nan_policy="omit"), not
    treated as zero. A factor constant across a multi-name universe has no
    cross-sectional signal, so it maps to a neutral z-score of 0 instead of
    NaN. Caller must sign-flip LOWER_IS_BETTER factors before calling this
    function, so that "higher z-score = better" holds for every resulting
    column.
    """
    out = df.copy()
    for col in factor_cols:
        valid = out[col].dropna()
        if len(valid) > 1 and float(valid.std(ddof=0)) == 0.0:
            z = pd.Series(0.0, index=out.index, dtype=float)
            z[out[col].isna()] = np.nan
            out[f"{col}_z"] = z
        else:
            out[f"{col}_z"] = zscore(out[col], nan_policy="omit")
    return out
```

### Step C — Combine (weighted sum; default method — see §7 for Borda alternative)

**No weights constant lives in `agents/modeling.py` at all.** The global
default weights exist in exactly one place — `config/factor_weights.yaml`
— and are loaded by a small function outside this skill's scope entirely
(`app/api/themes.py`'s `POST /themes` handler, or a shared
`app/config.py` loader it calls), which copies the YAML content verbatim
into `theme.config.factor_weights` at theme-creation time. If you find
yourself adding a weights dict literal anywhere in `agents/modeling.py`,
stop — that's Hard Rule 2 being violated.

```python
def combine_scores(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted linear combination of z-scored factors into one composite_score.
    `weights` must be theme_config["factor_weights"] — the caller (modeling_node)
    is responsible for reading it from state and raising if it's absent
    (Hard Rule 2). This function has no default weights of its own."""
    return sum(df[k] * w for k, w in weights.items())
```

### Step D — Rank

```python
def rank(df: pd.DataFrame, score_col: str = "composite_score") -> pd.DataFrame:
    """Descending sort by composite_score; rank 1 = best.
    Ties are broken by input row order (see Hard Rule 7)."""
    df = df.sort_values(score_col, ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df
```

## Test fixtures to include (per `CONVENTIONS.md` §5)

For `get_factor_panel` (Step A), cover at minimum:
- A ticker with missing/null fundamentals (e.g. a recent IPO with no
  prior-year revenue) — `revenue_growth_yoy` should be `None`, not
  `inf` or `0`, and must not crash the batch.
- A ticker with fewer than 252 trading days of price history (recent
  listing) — `pct_from_52wk_high`/`beta` should degrade gracefully
  (shorter lookback or `None`), not raise an index error.
- Zero/negative `ebitda_ttm` or `net_income_ttm` — `ev_ebitda`,
  `debt_to_ebitda`, and `fcf_conversion` can produce nonsensical or
  sign-flipped results on negative denominators; decide and document
  the expected behavior (e.g. null out rather than returning a
  misleadingly large or negative ratio).
- `fetch_fundamentals`/`fetch_price_history` normalization — verify FMP
  vs. Finnhub and yfinance vs. Stooq outputs each collapse to one
  consistent shape (Hard Rule 11), and that a primary-source failure
  correctly falls back rather than propagating a vendor-specific error.

For Steps B/C/D, cover at minimum:
- All-NaN factor column (should not raise; resulting z-scores are NaN,
  not zero).
- Two stocks with identical `composite_score` (verify current
  incidental-order tie-breaking behavior is what's actually intended —
  see Hard Rule 7).
- Single-candidate universe (z-score is undefined for N=1 — decide and
  document the expected output rather than letting it silently NaN
  through to `rank`).
- Weights that don't sum to 1.0 — should be caught by `api-engineer`'s
  validator against `config/factor_weights.yaml` at theme-creation time,
  never here, but add a test confirming `combine_scores` doesn't itself
  silently renormalize an invalid weight dict if one somehow reaches it.

## Where the Borda alternative and learning-to-rank fit in

`ARCHITECTURE.md` §7 records the decision to start with weighted-sum.
If `combine_scores` is ever swapped for the Borda rank-aggregation method
or a learned ranker (`LGBMRanker`), update `ARCHITECTURE.md`'s decision
log in the same PR — this skill file's "reference implementation" section
should also be updated to match, so the two never drift apart.

## Shadow-mode comparison reuses these exact functions (`ARCHITECTURE.md` §8.C)

`scripts/shadow_compare.py` is not a separate scoring implementation — it
calls `compute_factor_scores` → `combine_scores(df, new_weights)` →
`rank` directly, against a completed run's already-persisted
`analyst_reports`/`factor_panel` rows loaded from Postgres instead of
freshly fetched ones. No LLM calls, no vendor API calls — this is only
cheap and safe *because* Steps B/C/D are pure, deterministic functions
with no hidden state (Hard Rule 4). If you ever introduce hidden state
or non-determinism into this file, shadow-mode comparison silently stops
being trustworthy — treat that coupling as another reason Hard Rule 4
isn't optional.

```python
# scripts/shadow_compare.py (sketch — lives outside app/, not itself
# part of the agent pipeline)
from app.agents.modeling import compute_factor_scores, combine_scores, rank
from app.data.queries import get_analyst_reports, get_factor_panel_rows

def shadow_compare(run_id: str, new_weights: dict[str, float]) -> "DiffReport":
    reports = get_analyst_reports(run_id)          # already-persisted, no re-fetch
    panel = get_factor_panel_rows(run_id)           # already-persisted, no re-fetch
    scored = compute_factor_scores(panel, factor_cols=list(new_weights))
    combined = combine_scores(scored, new_weights)
    new_ranked = rank(combined)
    old_ranked = get_persisted_rankings(run_id)      # what actually shipped
    return diff_rankings(old_ranked, new_ranked)     # tickers in/out, rank deltas
```
