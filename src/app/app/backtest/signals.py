"""Deterministic substitute signals used only by the backtest path."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def etf_breadth(
    tickers: Iterable[str], membership: dict[str, set[str]]
) -> list[float]:
    """Count how many mapped ETFs hold each ticker at the signal date."""
    return [float(len(membership.get(str(ticker).upper(), set()))) for ticker in tickers]


def _money_flow_for_frame(frame: pd.DataFrame, min_obs: int) -> float:
    """Money-flow ratio for one OHLCV frame."""
    if frame.empty:
        return float("nan")
    required = {"close", "high", "low", "volume"}
    if not required.issubset(frame.columns):
        return float("nan")
    valid = frame[list(required)].dropna()
    valid = valid[valid["volume"] > 0]
    if len(valid) < min_obs:
        return float("nan")

    high_minus_low = valid["high"] - valid["low"]
    nonzero = high_minus_low > 0
    clv = pd.Series(0.0, index=valid.index, dtype=float)
    clv.loc[nonzero] = (
        (valid.loc[nonzero, "close"] - valid.loc[nonzero, "low"])
        - (valid.loc[nonzero, "high"] - valid.loc[nonzero, "close"])
    ) / high_minus_low.loc[nonzero]
    flow = clv * valid["volume"]
    total_volume = valid["volume"].sum()
    if not total_volume or np.isnan(total_volume):
        return float("nan")
    return float(flow.sum() / total_volume)


def money_flow_ratio(
    ohlcv: dict[str, pd.DataFrame], window: int = 126, min_obs: int = 100
) -> list[float]:
    """CLV-weighted volume ratio for each ticker in stable input order."""
    return [
        _money_flow_for_frame(
            ohlcv.get(ticker, pd.DataFrame()).tail(window), min_obs
        )
        for ticker in ohlcv
    ]
