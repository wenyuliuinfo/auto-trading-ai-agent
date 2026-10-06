"""Performance metrics and attribution for the backtest engine."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.types import EquityPoint, Rebalance, SimulationResult, Trade


def _values(points: list[EquityPoint]) -> list[float]:
    return [float(point.value) for point in points]


def _returns(points: list[EquityPoint]) -> pd.Series:
    if len(points) < 2:
        return pd.Series(dtype=float)
    return pd.Series(_values(points)).pct_change().replace(
        [np.inf, -np.inf], np.nan
    ).dropna()


def total_return(points: list[EquityPoint], initial_cash: float) -> float:
    if not points or initial_cash == 0:
        return float("nan")
    return points[-1].value / initial_cash - 1


def cagr(
    points: list[EquityPoint],
    initial_cash: float,
    annualize_min_years: float,
) -> float | None:
    """Annualized return, or None when the period is too short."""
    if len(points) < 2:
        return None
    years = (points[-1].date - points[0].date).days / 365.25
    if years < annualize_min_years:
        return None
    final_ratio = points[-1].value / initial_cash
    if final_ratio <= 0:
        return float("nan")
    return float(final_ratio ** (1 / years) - 1)


def max_drawdown(points: list[EquityPoint]) -> dict[str, Any]:
    """Return maximum peak-to-trough drawdown with dates."""
    if not points:
        return {"value": None, "peak_date": None, "trough_date": None}
    peak = points[0].value
    peak_date = points[0].date
    max_dd = 0.0
    trough_date = points[0].date
    for point in points:
        if point.value > peak:
            peak = point.value
            peak_date = point.date
        dd = point.value / peak - 1 if peak else 0.0
        if dd < max_dd:
            max_dd = dd
            trough_date = point.date
    return {
        "value": max_dd,
        "peak_date": peak_date,
        "trough_date": trough_date,
    }


def _series_metrics(
    points: list[EquityPoint],
    initial_cash: float,
    risk_free_annual: float,
    trading_days_per_year: int,
    annualize_min_years: float,
) -> dict[str, Any]:
    returns = _returns(points)
    volatility = (
        float(returns.std(ddof=1) * math.sqrt(trading_days_per_year))
        if len(returns) > 1
        else 0.0
    )
    daily_rf = risk_free_annual / trading_days_per_year
    if len(returns) > 1 and returns.std(ddof=1) > 0:
        sharpe = float(
            (returns.mean() - daily_rf) / returns.std(ddof=1) * math.sqrt(trading_days_per_year)
        )
    else:
        sharpe = float("nan")
    drawdown = max_drawdown(points)
    return {
        "total_return": total_return(points, initial_cash),
        "final_value": points[-1].value if points else initial_cash,
        "cagr": cagr(points, initial_cash, annualize_min_years),
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": drawdown["value"],
        "max_drawdown_peak_date": drawdown["peak_date"].isoformat()
        if drawdown["peak_date"]
        else None,
        "max_drawdown_trough_date": drawdown["trough_date"].isoformat()
        if drawdown["trough_date"]
        else None,
    }


def beta_alpha(
    strategy: list[EquityPoint],
    benchmark: list[EquityPoint],
    trading_days_per_year: int,
) -> dict[str, float | None]:
    """Daily regression of strategy returns on benchmark returns."""
    if len(strategy) < 3 or len(benchmark) < 3:
        return {"beta": None, "alpha": None}
    strategy_map = _point_map(strategy)
    benchmark_map = _point_map(benchmark)
    common_dates = sorted(set(strategy_map) & set(benchmark_map))
    if len(common_dates) < 3:
        return {"beta": None, "alpha": None}
    strategy_values = pd.Series(
        [strategy_map[day] for day in common_dates], index=common_dates
    )
    benchmark_values = pd.Series(
        [benchmark_map[day] for day in common_dates], index=common_dates
    )
    returns = pd.DataFrame(
        {"strategy": strategy_values.pct_change(), "benchmark": benchmark_values.pct_change()}
    ).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2 or returns["benchmark"].std(ddof=1) == 0:
        return {"beta": None, "alpha": None}
    beta = float(returns["strategy"].cov(returns["benchmark"]) / returns["benchmark"].var())
    alpha_daily = float(returns["strategy"].mean() - beta * returns["benchmark"].mean())
    return {"beta": beta, "alpha": alpha_daily * trading_days_per_year}


def _point_map(points: list[EquityPoint]) -> dict[date, float]:
    return {point.date: point.value for point in points}


def period_return(
    rebalance: Rebalance, points: list[EquityPoint]
) -> float:
    values = _point_map(points)
    start = values.get(rebalance.exec_date)
    end = values.get(rebalance.hold_end_date)
    if start is None or end is None or start == 0:
        return float("nan")
    return end / start - 1


def summary_metrics(
    strategy: list[EquityPoint],
    benchmarks: dict[str, list[EquityPoint]],
    rebalances: list[Rebalance],
    sim: SimulationResult,
    cfg: dict[str, Any],
    primary_benchmark: str,
) -> dict[str, Any]:
    """Compute summary metrics for the strategy and each benchmark."""
    capital = cfg.get("capital", {})
    metrics_cfg = cfg.get("metrics", {})
    initial_cash = float(capital.get("initial_cash", 10000))
    risk_free = float(metrics_cfg.get("risk_free_annual", 0.0))
    trading_days = int(metrics_cfg.get("trading_days_per_year", 252))
    annualize_min_years = float(metrics_cfg.get("annualize_min_years", 1.0))

    benchmark_summaries: dict[str, dict[str, Any]] = {}
    for name, points in benchmarks.items():
        benchmark_summaries[name] = _series_metrics(
            points,
            initial_cash,
            risk_free,
            trading_days,
            annualize_min_years,
        )

    primary_points = benchmarks.get(primary_benchmark, [])
    regression = beta_alpha(strategy, primary_points, trading_days)
    strategy_summary = _series_metrics(
        strategy,
        initial_cash,
        risk_free,
        trading_days,
        annualize_min_years,
    )
    strategy_summary.update(regression)
    strategy_summary["turnover"] = sim.turnover
    strategy_summary["costs_paid"] = sim.costs_total

    # Tracking error and information ratio versus the primary benchmark.
    strategy_returns = _returns(strategy)
    if primary_points and len(strategy_returns) > 1:
        benchmark_series = pd.Series(_values(primary_points), index=[p.date for p in primary_points])
        benchmark_returns = benchmark_series.pct_change().replace([np.inf, -np.inf], np.nan)
        excess = strategy_returns.sub(benchmark_returns, fill_value=0.0).dropna()
        strategy_summary["tracking_error"] = (
            float(excess.std(ddof=1) * math.sqrt(trading_days))
            if len(excess) > 1 and excess.std(ddof=1) > 0
            else 0.0
        )
        strategy_summary["information_ratio"] = (
            float(excess.mean() / excess.std(ddof=1) * math.sqrt(trading_days))
            if len(excess) > 1 and excess.std(ddof=1) > 0
            else None
        )
    else:
        strategy_summary["tracking_error"] = 0.0
        strategy_summary["information_ratio"] = None

    strategy_returns_by_period = [
        period_return(rebalance, strategy) for rebalance in rebalances
    ]
    benchmark_returns_by_period = [
        period_return(rebalance, primary_points) for rebalance in rebalances
    ]
    beats = sum(
        1
        for strategy_return, benchmark_return in zip(
            strategy_returns_by_period, benchmark_returns_by_period, strict=True
        )
        if not np.isnan(strategy_return)
        and not np.isnan(benchmark_return)
        and strategy_return > benchmark_return
    )
    valid_periods = sum(
        1
        for strategy_return, benchmark_return in zip(
            strategy_returns_by_period, benchmark_returns_by_period, strict=True
        )
        if not np.isnan(strategy_return) and not np.isnan(benchmark_return)
    )
    strategy_summary["hit_rate"] = beats / valid_periods if valid_periods else 0.0

    return {
        "strategy": strategy_summary,
        "benchmarks": benchmark_summaries,
    }


def attribution(
    trades: list[Trade],
    final_positions: dict[str, float],
    final_prices: dict[str, float],
    initial_cash: float,
    company_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Per-ticker gross P&L; costs are reported separately by the caller."""
    buys: dict[str, float] = {}
    sells: dict[str, float] = {}
    periods: dict[str, set[date]] = {}
    for trade in trades:
        if trade.side == "BUY":
            buys[trade.ticker] = buys.get(trade.ticker, 0.0) + trade.value
        else:
            sells[trade.ticker] = sells.get(trade.ticker, 0.0) + trade.value
        periods.setdefault(trade.ticker, set()).add(trade.date)

    tickers = sorted(set(buys) | set(sells) | set(final_positions))
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        final_value = final_positions.get(ticker, 0.0) * final_prices.get(ticker, 0.0)
        pnl = final_value + sells.get(ticker, 0.0) - buys.get(ticker, 0.0)
        rows.append(
            {
                "ticker": ticker,
                "company_name": (company_names or {}).get(ticker),
                "pnl": pnl,
                "contribution_pct": pnl / initial_cash * 100
                if initial_cash
                else float("nan"),
                "periods_held": len(periods.get(ticker, set())),
            }
        )
    return sorted(rows, key=lambda row: row["pnl"], reverse=True)
