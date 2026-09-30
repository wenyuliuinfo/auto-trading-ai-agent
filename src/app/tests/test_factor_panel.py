"""Factor panel unit tests for edge cases in raw-factor assembly."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.integrations.factor_panel import (
    RAW_FACTOR_COLUMNS,
    RISK_MIN_OBS,
    RISK_WINDOW,
    _row_for_ticker,
    compute_amihud_3m,
    compute_turnover_3m,
    compute_vol_3m,
    get_factor_panel,
)
from app.integrations.fundamentals import Fundamentals
from app.integrations.yfinance_client import PriceHistory


def _fundamentals() -> Fundamentals:
    return Fundamentals(
        ticker="ZERO",
        price=100.0,
        diluted_eps_ttm=10.0,
        market_cap=10_000_000_000.0,
        total_debt=0.0,
        cash=1_000_000_000.0,
        ebitda_ttm=1_000_000_000.0,
        revenue_ttm=20_000_000_000.0,
        revenue_growth_yoy=0.1,
        eps_growth_yoy=0.2,
        net_income_ttm=2_000_000_000.0,
        shareholders_equity=5_000_000_000.0,
        gross_profit_ttm=8_000_000_000.0,
        free_cash_flow_ttm=1_000_000_000.0,
        source="test",
    )


def _prices() -> PriceHistory:
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    close = pd.Series(np.linspace(50.0, 100.0, len(dates)), index=dates)
    volume = pd.Series(1_000_000.0, index=dates)
    return PriceHistory(ticker="ZERO", close=close, volume=volume, source="test")


def test_zero_total_debt_is_not_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: zero debt must produce EV/EBITDA, not NaN."""
    monkeypatch.setattr(
        "app.integrations.factor_panel.fetch_fundamentals",
        lambda ticker: _fundamentals(),
    )
    monkeypatch.setattr(
        "app.integrations.factor_panel.fetch_price_history",
        lambda ticker, lookback_days=504: _prices(),
    )

    row = _row_for_ticker("ZERO")

    assert not math.isnan(row["ev_ebitda"])
    assert row["debt_to_ebitda"] == 0.0


def test_get_factor_panel_fetches_spy_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_fetch_price_history(
        ticker: str, lookback_days: int = 504
    ) -> PriceHistory:
        calls.append(ticker)
        return _prices()

    def fake_row(ticker: str, benchmark_history: PriceHistory | None = None) -> dict[str, object]:
        return {**{col: float("nan") for col in RAW_FACTOR_COLUMNS}, "ticker": ticker}

    monkeypatch.setattr(
        "app.integrations.factor_panel.fetch_price_history",
        fake_fetch_price_history,
    )
    monkeypatch.setattr(
        "app.integrations.factor_panel._row_for_ticker",
        fake_row,
    )

    panel = get_factor_panel(["AAA", "BBB"])

    assert calls.count("SPY") == 1
    assert list(panel["ticker"]) == ["AAA", "BBB"]


def test_compute_vol_3m_constant_price_is_zero() -> None:
    close = pd.Series([100.0] * (RISK_WINDOW + 1))
    assert compute_vol_3m(close) == 0.0


def test_compute_vol_3m_requires_min_observations() -> None:
    close = pd.Series([100.0 + i * 0.5 for i in range(RISK_MIN_OBS)])
    assert math.isnan(compute_vol_3m(close))
    enough = pd.Series([100.0 + i * 0.5 for i in range(RISK_MIN_OBS + 1)])
    assert not math.isnan(compute_vol_3m(enough))


def test_compute_turnover_3m_uses_last_window() -> None:
    volume = pd.Series(range(100))
    shares = 1_000_000.0
    expected = float(pd.Series(range(100 - RISK_WINDOW, 100)).mean() / shares)
    assert compute_turnover_3m(volume, shares) == pytest.approx(expected)


def test_compute_turnover_3m_rejects_invalid_shares() -> None:
    volume = pd.Series([1_000_000.0] * RISK_WINDOW)
    assert math.isnan(compute_turnover_3m(volume, 0.0))
    assert math.isnan(compute_turnover_3m(volume, float("nan")))


def test_compute_amihud_3m_hand_computed() -> None:
    close = pd.Series([100.0, 101.0, 100.0, 102.0, 103.0] * 20)
    volume = pd.Series([1_000_000.0] * 100)
    frame = pd.concat([close.tail(RISK_WINDOW + 1), volume.tail(RISK_WINDOW + 1)], axis=1)
    ret = frame.iloc[:, 0].pct_change().abs()
    dollar_volume = frame.iloc[:, 0] * frame.iloc[:, 1]
    ratio = (ret / dollar_volume).where(dollar_volume > 0)
    expected = float(ratio.dropna().mean() * 1e6)
    assert compute_amihud_3m(close, volume) == pytest.approx(expected)


def test_compute_amihud_3m_all_zero_volume_is_nan() -> None:
    close = pd.Series([100.0 + i for i in range(RISK_WINDOW + 1)])
    volume = pd.Series([0.0] * (RISK_WINDOW + 1))
    assert math.isnan(compute_amihud_3m(close, volume))


def test_raw_factor_columns_include_new_risk_factors() -> None:
    for name in ["vol_3m", "turnover_3m", "amihud_3m"]:
        assert RAW_FACTOR_COLUMNS.count(name) == 1
