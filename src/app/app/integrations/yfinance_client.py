"""yfinance client (fallback price source; ToS gray area per ARCHITECTURE.md §6)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class PriceHistory:
    ticker: str
    close: pd.Series
    volume: pd.Series
    source: str


def fetch_yfinance_prices(ticker: str, lookback_days: int = 504) -> PriceHistory:
    """Fetch ~2y of daily OHLCV and return normalized close/volume series."""
    import yfinance as yf

    frame = yf.Ticker(ticker).history(period="2y", auto_adjust=True)
    if frame.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    frame = frame.dropna(subset=["Close"])
    close = frame["Close"].tail(lookback_days)
    volume = frame.get("Volume", pd.Series(index=close.index, dtype=float)).tail(
        lookback_days
    )
    return PriceHistory(ticker=ticker, close=close, volume=volume, source="yfinance")
