"""Normalized price history across FMP + yfinance + Stooq (Hard Rule 11)."""

from __future__ import annotations

import io
import random

import httpx
import numpy as np
import pandas as pd

from app.config import get_settings
from app.integrations.fmp import fetch_fmp_prices
from app.integrations.yfinance_client import PriceHistory, fetch_yfinance_prices
from app.logging_conf import get_logger

logger = get_logger(__name__)


def _stub_price_history(ticker: str, lookback_days: int = 504) -> PriceHistory:
    """Deterministic seeded random walk for offline/stub runs."""
    rng = random.Random(ticker)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=lookback_days)
    returns = [rng.gauss(0.0004, 0.02) for _ in range(lookback_days)]
    close = pd.Series(100.0 * np.exp(np.cumsum(returns)), index=dates, dtype=float)
    volume = pd.Series(
        [rng.uniform(1e6, 3e7) for _ in range(lookback_days)],
        index=dates,
        dtype=float,
    )
    return PriceHistory(ticker=ticker, close=close, volume=volume, source="stub")


def fetch_stooq_prices(ticker: str, lookback_days: int = 504) -> PriceHistory:
    """Stooq daily CSV fallback."""
    candidates = [ticker.lower(), f"{ticker.lower()}.us"]
    last_error: Exception | None = None
    for symbol in candidates:
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        try:
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text))
            if frame.empty:
                continue
            frame["Date"] = pd.to_datetime(frame["Date"])
            frame = frame.set_index("Date").dropna(subset=["Close"]).tail(lookback_days)
            close = frame["Close"].astype(float)
            volume = frame.get("Volume", pd.Series(index=close.index, dtype=float))
            return PriceHistory(ticker=ticker, close=close, volume=volume, source="stooq")
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Stooq returned no data for {ticker}") from last_error


def fetch_price_history(ticker: str, lookback_days: int = 504) -> PriceHistory:
    """FMP EOD primary, yfinance fallback, Stooq last resort."""
    settings = get_settings()
    if settings.stub_agents:
        return _stub_price_history(ticker, lookback_days)
    if settings.fmp_api_key:
        try:
            return fetch_fmp_prices(ticker, lookback_days)
        except Exception as exc:
            logger.warning("fmp_prices_failed", ticker=ticker, error=str(exc))
    try:
        return fetch_yfinance_prices(ticker, lookback_days)
    except Exception as exc:
        logger.warning("yfinance_failed", ticker=ticker, error=str(exc))
        return fetch_stooq_prices(ticker, lookback_days)
