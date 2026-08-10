"""Modeling agent: deterministic factor scoring + ranking (Steps B/C/D).

The LLM's only role here is writing ``caveats`` prose; rank and
composite score are pure, reproducible math (MODELING_SKILL.md Hard Rule 1).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.stats import zscore

from app.data.queries import (
    get_cached_factor_tickers,
    get_factor_panel_for_tickers,
    save_factor_panel,
    save_rankings,
)
from app.integrations.factor_panel import RAW_FACTOR_COLUMNS, get_factor_panel
from app.logging_conf import get_logger

logger = get_logger(__name__)

SENTIMENT_MAP = {"bearish": -1.0, "neutral": 0.0, "bullish": 1.0}

# Lower raw value is better; sign-flip here, before compute_factor_scores,
# so "higher z-score = better" holds for every scored column.
LOWER_IS_BETTER = {"pe_ratio", "ev_ebitda", "debt_to_ebitda"}

SCORING_FACTORS = [
    "thematic",
    "growth",
    "quality",
    "valuation",
    "momentum",
    "sentiment",
]

MODELING_MODEL = "deepseek-v4-pro"
MODELING_TEMPERATURE = 0.2

MODELING_CAVEATS_PROMPT = """You are a Quantitative Ranking Agent. You do not write prose analysis and
you do not use subjective judgment to order stocks. You compute a
transparent, reproducible composite score for every stock in the universe
and output a ranked table.

You will be given, for each ticker: the structured Analyst report (Step 1)
and a quantitative factor panel (valuation, growth, quality, momentum,
liquidity — supplied via the `get_factor_panel` tool).

Procedure (do this exactly, do not substitute your own weighting scheme
unless explicitly instructed):

1. Convert the Analyst's `thematic_relevance_score` (1-5) and
   `sentiment_label` into numeric factor inputs.
2. Call `compute_factor_scores(universe)` to z-score every quantitative
   factor cross-sectionally against the candidate universe (not the
   broader market).
3. Call `combine_scores(factor_scores, weights)` using the supplied
   weighting config to produce one composite score per ticker.
4. Call `rank(composite_scores)` to produce the final ordered list with
   each factor's contribution shown (for auditability).
5. Do not override the computed rank with your own opinion. If a result
   looks wrong (e.g. a thinly-traded microcap ranks #1 purely on momentum),
   flag it in a `caveats` field rather than silently re-ordering.

Output a JSON object with a `caveats` key mapping each ticker to a list
of caveat strings, for example:
{"caveats": {"TICKER": ["..."]}}. This output must be reproducible —
given the same inputs, the same caveats must result."""


class CaveatsOutput(BaseModel):
    caveats: dict[str, list[str]] = Field(default_factory=dict)


def sentiment_label_to_numeric(label: str) -> float:
    """Map an Analyst sentiment label to a numeric factor input."""
    return SENTIMENT_MAP[label]


def compute_factor_scores(
    df: pd.DataFrame, factor_cols: list[str]
) -> pd.DataFrame:
    """Cross-sectional z-score each factor within the candidate universe.

    Missing values are excluded from mean/std (``nan_policy="omit"``),
    never treated as zero. A factor constant across a multi-name universe
    has no cross-sectional signal, so it maps to a neutral z-score of 0
    instead of NaN. Caller must sign-flip LOWER_IS_BETTER factors before
    calling, so "higher z-score = better" holds for every column.
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


def combine_scores(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted linear combination of z-scored factors into one composite.

    ``weights`` must be the persisted ``theme_config["factor_weights"]``;
    this function has no default weights of its own (MODELING_SKILL.md
    Hard Rule 2) and does not renormalize an invalid dict.
    """
    return sum(df[k] * weight for k, weight in weights.items())


def rank(df: pd.DataFrame, score_col: str = "composite_score") -> pd.DataFrame:
    """Descending sort by composite_score; rank 1 = best.

    Ties are broken by input row order (MODELING_SKILL.md Hard Rule 7).
    """
    sorted_df = df.sort_values(score_col, ascending=False).reset_index(drop=True)
    sorted_df["rank"] = sorted_df.index + 1
    return sorted_df


def _nanmean(values: list[float]) -> float:
    finite = [float(v) for v in values if pd.notna(v)]
    return float(np.mean(finite)) if finite else float("nan")


def _build_scoring_frame(
    panel: pd.DataFrame, reports: list[dict[str, Any]]
) -> pd.DataFrame:
    """Build one raw column per scored factor group plus screening inputs."""
    panel_by_ticker = panel.set_index("ticker")
    rows: list[dict[str, Any]] = []
    for report in reports:
        ticker = str(report["ticker"])
        raw: pd.Series | None = (
            panel_by_ticker.loc[ticker] if ticker in panel_by_ticker.index else None
        )

        def value(name: str, raw: pd.Series | None = raw) -> float:
            if raw is None or name not in raw.index:
                return float("nan")
            candidate = raw[name]
            return float(candidate) if pd.notna(candidate) else float("nan")

        pe = value("pe_ratio")
        ev_ebitda = value("ev_ebitda")
        debt = value("debt_to_ebitda")
        growth_values = [value("revenue_growth_yoy"), value("eps_growth_yoy")]
        quality_values = [
            value("roe"),
            value("gross_margin"),
            value("fcf_conversion"),
            -debt if pd.notna(debt) else float("nan"),
        ]
        valuation_values = [
            -pe if pd.notna(pe) else float("nan"),
            -ev_ebitda if pd.notna(ev_ebitda) else float("nan"),
        ]
        rows.append(
            {
                "ticker": ticker,
                "thematic": float(report["thematic_relevance_score"]),
                "sentiment": sentiment_label_to_numeric(
                    str(report["sentiment_label"])
                ),
                "growth": _nanmean(growth_values),
                "quality": _nanmean(quality_values),
                "valuation": _nanmean(valuation_values),
                "momentum": value("momentum_6m"),
                "market_cap": value("market_cap"),
                "adv": value("adv"),
            }
        )
    return pd.DataFrame(rows)


def _panel_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Rehydrate a panel DataFrame from persisted factor rows."""
    pivoted: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row["ticker"])
        pivoted.setdefault(ticker, {"ticker": ticker})[str(row["factor_name"])] = row.get(
            "raw_value"
        )
    return pd.DataFrame(list(pivoted.values()), columns=RAW_FACTOR_COLUMNS)


def _deterministic_caveats(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entry in entries:
        caveats: list[str] = []
        market_cap = entry.get("market_cap")
        adv = entry.get("adv")
        if market_cap is not None and pd.notna(market_cap) and market_cap < 1e9:
            caveats.append("below-average market capitalization in this universe")
        if adv is not None and pd.notna(adv) and adv < 5e6:
            caveats.append("average daily dollar volume below $5M")
        if (
            entry.get("rank") == 1
            and market_cap is not None
            and pd.notna(market_cap)
            and market_cap < 5e9
        ):
            caveats.append("top-ranked name is small-cap; treat rank with caution")
        result[str(entry["ticker"])] = caveats
    return result


async def _build_caveats(
    entries: list[dict[str, Any]],
) -> dict[str, list[str]]:
    from app.integrations.deepseek_client import DeepSeekClient, stubbing_enabled

    deterministic = _deterministic_caveats(entries)
    if stubbing_enabled():
        return deterministic
    try:
        client = DeepSeekClient()
        output = await client.complete_json(
            model=MODELING_MODEL,
            temperature=MODELING_TEMPERATURE,
            system=MODELING_CAVEATS_PROMPT,
            input_data={
                "ranked_list": [
                    {
                        k: v
                        for k, v in entry.items()
                        if k in {"ticker", "rank", "composite_score", "market_cap", "adv"}
                    }
                    for entry in entries
                ]
            },
            response_schema=CaveatsOutput,
        )
        return {str(k): list(v) for k, v in output["caveats"].items()}
    except Exception as exc:
        logger.warning("caveats_llm_failed", error=str(exc))
        return deterministic


def _contribution_series(
    scored: pd.DataFrame, weights: dict[str, float]
) -> dict[str, dict[str, float | None]]:
    contributions: dict[str, dict[str, float | None]] = {}
    for _, row in scored.iterrows():
        ticker = str(row["ticker"])
        contributions[ticker] = {
            key: (
                float(row[f"{key}"] * weight)
                if pd.notna(row[f"{key}"])
                else None
            )
            for key, weight in weights.items()
        }
    return contributions


async def modeling_node(state: dict[str, Any]) -> dict[str, Any]:
    """Score + rank the universe deterministically, then persist artifacts."""
    reports = [
        report
        for report in state["analyst_reports"]
        if report.get("status") != "error"
    ]
    if not reports:
        raise RuntimeError("modeling_node received no valid analyst reports")

    theme_config = state["theme_config"]
    weights = theme_config["factor_weights"]
    if not isinstance(weights, dict):
        raise KeyError("theme_config['factor_weights'] is missing or invalid")

    tickers = [str(report["ticker"]) for report in reports]
    today = date.today()
    cached_tickers = set(await get_cached_factor_tickers(today))
    to_fetch = [ticker for ticker in tickers if ticker not in cached_tickers]
    if to_fetch:
        fresh = await asyncio.to_thread(get_factor_panel, to_fetch)
    else:
        fresh = pd.DataFrame(columns=RAW_FACTOR_COLUMNS)
    cached_rows = await get_factor_panel_for_tickers(tickers, today)
    to_fetch_set = set(to_fetch)
    cached_rows = [row for row in cached_rows if row["ticker"] not in to_fetch_set]
    frames = [frame for frame in (fresh, _panel_from_rows(cached_rows)) if not frame.empty]
    panel = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=RAW_FACTOR_COLUMNS)
    )

    scoring = _build_scoring_frame(panel, reports)
    factor_cols = [key.removesuffix("_z") for key in weights]
    scored = compute_factor_scores(scoring, factor_cols)
    scored["composite_score"] = combine_scores(scored, weights)
    ranked = rank(scored)

    candidate_map = {str(c["ticker"]): c for c in state.get("candidates", [])}
    entries: list[dict[str, Any]] = []
    for _, row in ranked.iterrows():
        ticker = str(row["ticker"])
        candidate = candidate_map.get(ticker, {})
        entries.append(
            {
                "ticker": ticker,
                "company_name": candidate.get("company_name"),
                "gics_subindustry": candidate.get("gics_subindustry"),
                "sub_exposure": candidate.get("sub_exposure"),
                "sub_exposure_tags": candidate.get("sub_exposure_tags", []),
                "composite_score": (
                    float(row["composite_score"])
                    if pd.notna(row["composite_score"])
                    else None
                ),
                "rank": int(row["rank"]),
                "market_cap": (
                    float(row["market_cap"]) if pd.notna(row["market_cap"]) else None
                ),
                "avg_dollar_volume": (
                    float(row["adv"]) if pd.notna(row["adv"]) else None
                ),
                "thematic_relevance_score": (
                    float(row["thematic"]) if pd.notna(row["thematic"]) else None
                ),
                "sentiment": (
                    float(row["sentiment"]) if pd.notna(row["sentiment"]) else None
                ),
                "factor_contributions": {},
                "caveats": [],
            }
        )

    contributions = _contribution_series(scored, weights)
    for entry in entries:
        entry["factor_contributions"] = contributions[entry["ticker"]]
    caveats = await _build_caveats(entries)
    for entry in entries:
        entry["caveats"] = caveats.get(entry["ticker"], [])

    panel_rows: list[dict[str, Any]] = []
    panel_by_ticker = panel.set_index("ticker")
    for _, row in scored.iterrows():
        ticker = str(row["ticker"])
        panel_row = (
            panel_by_ticker.loc[ticker]
            if ticker in panel_by_ticker.index
            else None
        )
        for factor in factor_cols:
            panel_rows.append(
                {
                    "ticker": ticker,
                    "as_of_date": today,
                    "factor_name": factor,
                    "raw_value": (
                        float(row[factor]) if pd.notna(row[factor]) else None
                    ),
                    "z_score": (
                        float(row[f"{factor}_z"])
                        if pd.notna(row[f"{factor}_z"])
                        else None
                    ),
                }
            )
        # Persist the full raw panel (including the vendor-derived inputs such
        # as pe_ratio/roe/momentum_6m) so a same-day cache hit can rebuild the
        # scoring frame identically. Storing only the six scoring columns made
        # growth/quality/valuation NaN on cached runs and produced null
        # composite_score rows.
        for factor in RAW_FACTOR_COLUMNS:
            if factor == "ticker" or factor in factor_cols:
                continue
            raw_value: float | None = None
            if panel_row is not None and factor in panel_row.index:
                candidate_value = panel_row[factor]
                if pd.notna(candidate_value):
                    raw_value = float(candidate_value)
            panel_rows.append(
                {
                    "ticker": ticker,
                    "as_of_date": today,
                    "factor_name": factor,
                    "raw_value": raw_value,
                    "z_score": None,
                }
            )
    await save_factor_panel(state["run_id"], panel_rows)
    await save_rankings(state["run_id"], entries)
    logger.info(
        "modeling_complete", run_id=state["run_id"], ranked=len(entries)
    )
    return {"ranked_list": entries, "factor_panel": panel_rows}
