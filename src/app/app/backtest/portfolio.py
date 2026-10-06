"""Position sizing and delta-trade helpers for the simulation engine."""

from __future__ import annotations

from typing import Any


def target_shares(
    weights: dict[str, float],
    equity: float,
    prices: dict[str, float],
    fractional_shares: bool,
) -> tuple[dict[str, float], float, list[str]]:
    """Convert target weights to shares at one execution date.

    Returns ``(shares, allocated_value, missing_prices)``. Missing-price buys
    remain in cash and are reported rather than silently zero-filled.
    """
    shares: dict[str, float] = {}
    allocated = 0.0
    missing: list[str] = []
    for ticker, weight in weights.items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            missing.append(ticker)
            continue
        target_value = equity * weight
        raw_shares = target_value / price
        if not fractional_shares:
            raw_shares = float(int(raw_shares))
        if raw_shares <= 0:
            continue
        shares[ticker] = raw_shares
        allocated += raw_shares * price
    return shares, allocated, missing


def trade_deltas(
    positions: dict[str, float],
    target: dict[str, float],
    prices: dict[str, float],
) -> list[dict[str, Any]]:
    """Compute the delta trades required to move from positions to target."""
    deltas: list[dict[str, Any]] = []
    tickers = sorted(set(positions) | set(target))
    for ticker in tickers:
        current = positions.get(ticker, 0.0)
        desired = target.get(ticker, 0.0)
        delta = desired - current
        if abs(delta) < 1e-12:
            continue
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        side = "BUY" if delta > 0 else "SELL"
        deltas.append(
            {
                "ticker": ticker,
                "side": side,
                "shares": abs(delta),
                "price": price,
                "value": abs(delta) * price,
            }
        )
    return deltas


def mark_to_market(
    cash: float,
    positions: dict[str, float],
    prices: dict[str, float],
) -> float:
    """Return portfolio value with positions marked to ``prices``."""
    return cash + sum(shares * prices[ticker] for ticker, shares in positions.items())
