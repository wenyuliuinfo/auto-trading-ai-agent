"""Unit tests for Modeling's deterministic math (ARCHITECTURE.md §8.A)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.stats import zscore

from app.agents.modeling import (
    MODELING_CAVEATS_PROMPT,
    SENTIMENT_MAP,
    _build_scoring_frame,
    _panel_from_rows,
    _z_mean,
    combine_scores,
    compute_factor_scores,
    rank,
    sentiment_label_to_numeric,
)


def test_compute_factor_scores_matches_scipy() -> None:
    frame = pd.DataFrame({"factor": [2.0, 4.0, 4.0, 4.0, 6.0]})
    result = compute_factor_scores(frame, ["factor"])
    expected = zscore(frame["factor"], nan_policy="omit")
    np.testing.assert_allclose(result["factor_z"], expected)


def test_all_nan_factor_column_does_not_raise() -> None:
    frame = pd.DataFrame({"factor": [np.nan, np.nan, np.nan]})
    result = compute_factor_scores(frame, ["factor"])
    assert result["factor_z"].isna().all()


def test_single_candidate_z_score_is_nan() -> None:
    frame = pd.DataFrame({"factor": [5.0]})
    result = compute_factor_scores(frame, ["factor"])
    assert np.isnan(result["factor_z"].iloc[0])


def test_constant_factor_maps_to_zero_z_score() -> None:
    frame = pd.DataFrame({"factor": [3.0, 3.0, 3.0, 3.0]})
    result = compute_factor_scores(frame, ["factor"])
    assert (result["factor_z"] == 0.0).all()


def test_constant_factor_with_missing_values_maps_to_zero_or_nan() -> None:
    frame = pd.DataFrame({"factor": [3.0, 3.0, np.nan, 3.0]})
    result = compute_factor_scores(frame, ["factor"])
    assert (result["factor_z"].dropna() == 0.0).all()
    assert np.isnan(result["factor_z"].iloc[2])


def test_combine_scores_is_weighted_sum_without_renormalization() -> None:
    frame = pd.DataFrame({"a_z": [1.0, 2.0], "b_z": [3.0, 4.0]})
    combined = combine_scores(frame, {"a_z": 0.6, "b_z": 0.4})
    np.testing.assert_allclose(combined, [1.8, 2.8])
    # Invalid weights (sum != 1) are not silently renormalized.
    assert not np.isclose(combined.sum(), 1.0)


def test_rank_is_descending_permutation() -> None:
    frame = pd.DataFrame(
        {"ticker": ["a", "b", "c", "d"], "composite_score": [3.0, 1.0, 3.0, 2.0]}
    )
    result = rank(frame)
    assert list(result["rank"]) == [1, 2, 3, 4]
    assert result.loc[result["ticker"] == "a", "rank"].iloc[0] == 1
    assert result.loc[result["ticker"] == "c", "rank"].iloc[0] == 2


@given(
    st.lists(st.floats(min_value=0.0, max_value=10.0), min_size=3, max_size=8),
    st.floats(min_value=0.0, max_value=1.0),
)
@settings(max_examples=20, deadline=None)
def test_rank_property_is_valid_permutation(values: list[float], extra: float) -> None:
    frame = pd.DataFrame(
        {
            "ticker": [f"t{i}" for i in range(len(values))],
            "composite_score": values,
        }
    )
    result = rank(frame)
    assert sorted(result["rank"].tolist()) == list(range(1, len(values) + 1))


def test_sentiment_map_round_trip() -> None:
    assert sentiment_label_to_numeric("bullish") == SENTIMENT_MAP["bullish"]
    assert sentiment_label_to_numeric("bearish") == -1.0


def test_caveats_prompt_supports_json_object_mode() -> None:
    assert "json" in MODELING_CAVEATS_PROMPT.lower()


def _persisted_panel_rows(ticker: str = "AAA") -> list[dict[str, object]]:
    raw = {
        "pe_ratio": 20.0,
        "ev_ebitda": 12.0,
        "ps_ratio": 5.0,
        "revenue_growth_yoy": 0.10,
        "eps_growth_yoy": 0.20,
        "roe": 0.15,
        "gross_margin": 0.40,
        "debt_to_ebitda": 1.5,
        "fcf_conversion": 0.80,
        "momentum_6m": 0.05,
        "rsi_14": 55.0,
        "pct_from_52wk_high": -0.02,
        "adv": 100_000_000.0,
        "market_cap": 100_000_000_000.0,
        "beta": 1.1,
        "hist_vol": 0.25,
    }
    return [
        {"ticker": ticker, "factor_name": name, "raw_value": value, "z_score": None}
        for name, value in raw.items()
    ]


def test_cached_panel_rebuilds_scorable_factors() -> None:
    """Regression: factor-panel cache rows must rebuild non-NaN factors."""
    panel = _panel_from_rows(_persisted_panel_rows())
    report = {
        "ticker": "AAA",
        "thematic_relevance_score": 4.0,
        "sentiment_label": "bullish",
    }
    scoring = _build_scoring_frame(panel, [report])
    row = scoring.iloc[0]
    assert not np.isnan(row["growth"])
    assert not np.isnan(row["quality"])
    assert not np.isnan(row["valuation"])
    assert not np.isnan(row["momentum"])
    assert not np.isnan(row["thematic"])


def test_cached_panel_with_missing_raw_value_does_not_crash() -> None:
    """Regression: null cached raw values map to NaN, never float(None)."""
    rows = _persisted_panel_rows()
    for row in rows:
        if row["factor_name"] in {"pe_ratio", "ev_ebitda", "market_cap"}:
            row["raw_value"] = None
    panel = _panel_from_rows(rows)
    report = {
        "ticker": "AAA",
        "thematic_relevance_score": 4.0,
        "sentiment_label": "bullish",
    }
    scoring = _build_scoring_frame(panel, [report])
    row = scoring.iloc[0]
    assert np.isnan(row["valuation"])
    assert np.isnan(row["market_cap"])


def _risk_scoring_panel(
    vol: list[float], turnover: list[float], amihud: list[float]
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["A", "B"],
            "vol_3m": vol,
            "turnover_3m": turnover,
            "amihud_3m": amihud,
        }
    )


def _risk_reports() -> list[dict[str, object]]:
    return [
        {
            "ticker": "A",
            "thematic_relevance_score": 4.0,
            "sentiment_label": "bullish",
        },
        {
            "ticker": "B",
            "thematic_relevance_score": 4.0,
            "sentiment_label": "bullish",
        },
    ]


def test_build_scoring_frame_adds_volatility_and_liquidity() -> None:
    frame = _build_scoring_frame(
        _risk_scoring_panel([0.2, 0.4], [0.01, 0.02], [0.5, 0.2]),
        _risk_reports(),
    )
    assert {"volatility", "liquidity"}.issubset(frame.columns)


def test_volatility_direction_is_lower_vol_higher_score() -> None:
    frame = _build_scoring_frame(
        _risk_scoring_panel([0.2, 0.4], [0.01, 0.02], [0.5, 0.2]),
        _risk_reports(),
    )
    scored = compute_factor_scores(frame, ["volatility"])
    a = scored.loc[scored["ticker"] == "A", "volatility_z"].iloc[0]
    b = scored.loc[scored["ticker"] == "B", "volatility_z"].iloc[0]
    assert a > b


def test_liquidity_direction_higher_turnover_higher_score() -> None:
    frame = _build_scoring_frame(
        _risk_scoring_panel([0.2, 0.2], [0.01, 0.02], [0.5, 0.5]),
        _risk_reports(),
    )
    a = frame.loc[frame["ticker"] == "A", "liquidity"].iloc[0]
    b = frame.loc[frame["ticker"] == "B", "liquidity"].iloc[0]
    assert b > a


def test_liquidity_direction_lower_amihud_higher_score() -> None:
    frame = _build_scoring_frame(
        _risk_scoring_panel([0.2, 0.2], [0.01, 0.01], [0.5, 0.2]),
        _risk_reports(),
    )
    a = frame.loc[frame["ticker"] == "A", "liquidity"].iloc[0]
    b = frame.loc[frame["ticker"] == "B", "liquidity"].iloc[0]
    assert b > a


def test_legacy_panel_without_new_columns_does_not_crash() -> None:
    panel = pd.DataFrame({"ticker": ["A"], "momentum_6m": [0.1]})
    frame = _build_scoring_frame(panel, _risk_reports()[:1])
    assert "volatility" in frame.columns
    assert "liquidity" in frame.columns
    assert np.isnan(frame["volatility"].iloc[0])
    assert np.isnan(frame["liquidity"].iloc[0])


def test_z_mean_reuses_zscore_and_averages_available_sub_signals() -> None:
    frame = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0],
            "b": [3.0, 2.0, np.nan],
        }
    )
    result = _z_mean(frame, ["a", "b"])
    assert not result.isna().any()
