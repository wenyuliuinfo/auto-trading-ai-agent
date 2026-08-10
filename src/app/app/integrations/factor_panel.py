"""Factor panel assembly: raw pre-z-score factors from vendor data (Step A)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from app.integrations.fundamentals import fetch_fundamentals
from app.integrations.prices import fetch_price_history
from app.integrations.yfinance_client import PriceHistory
from app.logging_conf import get_logger

logger = get_logger(__name__)

FACTOR_PANEL_MAX_WORKERS = 8

RAW_FACTOR_COLUMNS = [
    "ticker",
    "pe_ratio",
    "ev_ebitda",
    "ps_ratio",
    "revenue_growth_yoy",
    "eps_growth_yoy",
    "roe",
    "gross_margin",
    "debt_to_ebitda",
    "fcf_conversion",
    "momentum_6m",
    "return_1y",
    "rsi_14",
    "pct_from_52wk_high",
    "adv",
    "market_cap",
    "beta",
    "hist_vol",
]


def _ratio(numerator: float | None, denominator: float | None) -> float:
    if numerator is None or denominator is None or denominator == 0:
        return float("nan")
    return numerator / denominator


def compute_rsi(close: pd.Series, window: int = 14) -> float:
    """Wilder-style RSI approximation; NaN when the window is too short."""
    if len(close) < window + 1:
        return float("nan")
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    value = (100 - 100 / (1 + rs)).iloc[-1]
    return float(value)


def compute_beta(
    close: pd.Series,
    benchmark: str = "SPY",
    lookback_days: int = 504,
    benchmark_history: PriceHistory | None = None,
) -> float:
    """Beta vs benchmark over the lookback window; NaN on insufficient data."""
    try:
        bench = benchmark_history or fetch_price_history(
            benchmark, lookback_days=lookback_days
        )
        stock_returns = close.pct_change().dropna().tail(lookback_days)
        bench_returns = bench.close.pct_change().dropna().tail(lookback_days)
        aligned = pd.concat([stock_returns, bench_returns], axis=1, join="inner").dropna()
        if len(aligned) < 30:
            return float("nan")
        cov = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]))
        var = float(aligned.iloc[:, 1].var())
        if var == 0:
            return float("nan")
        return cov / var
    except Exception as exc:
        logger.warning("beta_computation_failed", benchmark=benchmark, error=str(exc))
        return float("nan")


def _row_for_ticker(
    ticker: str, benchmark_history: PriceHistory | None = None
) -> dict[str, Any]:
    fundamentals = fetch_fundamentals(ticker)
    prices = fetch_price_history(ticker)
    close = prices.close
    volume = prices.volume
    market_cap = (
        fundamentals.market_cap
        if fundamentals.market_cap is not None
        else float("nan")
    )
    total_debt = (
        fundamentals.total_debt
        if fundamentals.total_debt is not None
        else float("nan")
    )
    cash = (
        fundamentals.cash if fundamentals.cash is not None else float("nan")
    )
    pe = _ratio(fundamentals.price, fundamentals.diluted_eps_ttm)
    ev = (
        market_cap
        + total_debt
        - cash
    )
    ev_ebitda = _ratio(ev, fundamentals.ebitda_ttm)
    ps = _ratio(market_cap, fundamentals.revenue_ttm)
    roe = _ratio(fundamentals.net_income_ttm, fundamentals.shareholders_equity)
    gross_margin = _ratio(fundamentals.gross_profit_ttm, fundamentals.revenue_ttm)
    debt_to_ebitda = _ratio(fundamentals.total_debt, fundamentals.ebitda_ttm)
    fcf_conversion = _ratio(fundamentals.free_cash_flow_ttm, fundamentals.net_income_ttm)
    momentum_6m = _ratio(close.iloc[-1], close.iloc[-126]) - 1 if len(close) > 126 else float("nan")
    return_1y = _ratio(close.iloc[-1], close.iloc[-252]) - 1 if len(close) > 252 else float("nan")
    pct_from_52wk_high = (
        _ratio(close.iloc[-1], close.tail(252).max()) - 1
        if len(close) > 0 and close.tail(252).max() > 0
        else float("nan")
    )
    adv = float((volume.tail(20) * close.tail(20)).mean()) if len(volume) > 0 else float("nan")
    hist_vol = float(close.pct_change().std() * (252**0.5)) if len(close) > 1 else float("nan")
    return {
        "ticker": ticker,
        "pe_ratio": pe,
        "ev_ebitda": ev_ebitda,
        "ps_ratio": ps,
        "revenue_growth_yoy": fundamentals.revenue_growth_yoy
        if fundamentals.revenue_growth_yoy is not None
        else float("nan"),
        "eps_growth_yoy": fundamentals.eps_growth_yoy
        if fundamentals.eps_growth_yoy is not None
        else float("nan"),
        "roe": roe,
        "gross_margin": gross_margin,
        "debt_to_ebitda": debt_to_ebitda,
        "fcf_conversion": fcf_conversion,
        "momentum_6m": momentum_6m,
        "return_1y": return_1y,
        "rsi_14": compute_rsi(close),
        "pct_from_52wk_high": pct_from_52wk_high,
        "adv": adv,
        "market_cap": market_cap,
        "beta": compute_beta(close, benchmark_history=benchmark_history),
        "hist_vol": hist_vol,
    }


def _row_with_fallback(
    ticker: str, benchmark_history: PriceHistory | None
) -> dict[str, Any]:
    try:
        return _row_for_ticker(ticker, benchmark_history)
    except Exception as exc:
        logger.warning("factor_panel_ticker_failed", ticker=ticker, error=str(exc))
        return {**{col: float("nan") for col in RAW_FACTOR_COLUMNS}, "ticker": ticker}


def get_factor_panel(tickers: list[str]) -> pd.DataFrame:
    """Build the raw (pre-z-score) factor panel for the candidate universe.

    Per-ticker failures degrade to a row of NaNs (never a crash) so the
    scoring math can exclude missing values rather than dropping names.
    Tickers are fetched through a bounded thread pool; SPY is fetched once
    and shared across every beta calculation in the run.
    """
    try:
        benchmark_history = fetch_price_history("SPY", lookback_days=504)
    except Exception as exc:
        logger.warning("beta_benchmark_failed", benchmark="SPY", error=str(exc))
        benchmark_history = PriceHistory(
            ticker="SPY",
            close=pd.Series(dtype=float),
            volume=pd.Series(dtype=float),
            source="unavailable",
        )
    with ThreadPoolExecutor(max_workers=FACTOR_PANEL_MAX_WORKERS) as executor:
        rows = list(
            executor.map(
                lambda ticker: _row_with_fallback(ticker, benchmark_history),
                tickers,
            )
        )
    return pd.DataFrame(rows, columns=RAW_FACTOR_COLUMNS)


def is_finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False
