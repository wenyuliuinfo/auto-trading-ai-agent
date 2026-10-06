"""Benchmark buy-and-hold curves computed only from benchmark prices."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.backtest.types import EquityPoint


def benchmark_series(
    name: str,
    prices: dict[date, float],
    date_axis: list[date],
    initial_cash: float,
    apply_entry_cost: bool,
    cost_bps: float,
) -> list[EquityPoint]:
    """Build one benchmark curve on the same axis as the strategy.

    The benchmark starts at the first available date on or before the first
    axis date, pays the same one-time entry cost, and then holds.
    """
    if not prices or not date_axis:
        return []
    ordered = sorted((day, value) for day, value in prices.items())
    first_axis = date_axis[0]
    first_available: tuple[date, float] | None = None
    for day, value in ordered:
        if day <= first_axis:
            first_available = (day, value)
        else:
            break
    if first_available is None:
        return []

    _, first_price = first_available
    if first_price <= 0:
        return []
    cash = initial_cash * (1 - cost_bps / 10000.0 if apply_entry_cost else 1.0)
    shares = cash / first_price
    price_map = dict(ordered)
    points: list[EquityPoint] = []
    last_price = first_price
    for day in date_axis:
        last_price = price_map.get(day, last_price)
        points.append(EquityPoint(date=day, value=shares * last_price))
    return points


def build_benchmarks(
    benchmark_prices: dict[str, dict[date, float]],
    date_axis: list[date],
    cfg: dict[str, Any],
) -> dict[str, list[EquityPoint]]:
    """Build every enabled benchmark for which prices are available."""
    capital = cfg.get("capital", {})
    benchmarks = cfg.get("benchmarks", {})
    initial_cash = float(capital.get("initial_cash", 10000))
    apply_entry_cost = bool(benchmarks.get("apply_entry_cost", True))
    cost_bps = float(capital.get("transaction_cost_bps_per_side", 10))
    enabled = benchmarks.get("enabled", [])
    result: dict[str, list[EquityPoint]] = {}
    for name in enabled:
        prices = benchmark_prices.get(name)
        if not prices:
            continue
        series = benchmark_series(
            name, prices, date_axis, initial_cash, apply_entry_cost, cost_bps
        )
        if series:
            result[name] = series
    return result
