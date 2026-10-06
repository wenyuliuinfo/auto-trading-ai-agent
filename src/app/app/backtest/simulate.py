"""Portfolio simulation: delta trading, costs, and daily mark-to-market."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.backtest.portfolio import (
    mark_to_market,
    trade_deltas,
)
from app.backtest.portfolio import (
    target_shares as compute_target_shares,
)
from app.backtest.types import EquityPoint, Rebalance, SimulationResult, Trade


def _sorted_prices(prices: dict[date, float]) -> list[tuple[date, float]]:
    return sorted(
        ((day, float(value)) for day, value in prices.items() if value is not None),
        key=lambda item: item[0],
    )


def _latest_price(
    series: list[tuple[date, float]], day: date
) -> float | None:
    value: float | None = None
    for price_day, price in series:
        if price_day > day:
            break
        value = price
    return value


def _trade_reason(
    ticker: str,
    positions: dict[str, float],
    target: dict[str, float],
    side: str,
) -> str:
    held = ticker in positions and positions[ticker] > 0
    targeted = ticker in target and target[ticker] > 0
    if side == "SELL" and held and not targeted:
        return "exit"
    if side == "BUY" and not held and targeted:
        return "entry"
    if side == "BUY":
        return "increase"
    return "decrease"


def simulate(
    rebalances: list[Rebalance],
    targets: dict[date, dict[str, float]],
    prices: dict[str, dict[date, float]],
    cfg: dict[str, Any],
) -> SimulationResult:
    """Simulate a $10K portfolio traded to each rebalance target.

    ``prices`` maps ticker -> date -> total-return-adjusted close. The
    function performs no I/O and never reads the clock.
    """
    if not rebalances:
        return SimulationResult(equity=[], trades=[], costs_total=0.0, turnover=0.0)

    capital = cfg.get("capital", {})
    initial_cash = float(capital.get("initial_cash", 10000))
    fractional = bool(capital.get("fractional_shares", True))
    cost_bps = float(capital.get("transaction_cost_bps_per_side", 10))
    cost_rate = cost_bps / 10000.0

    series_by_ticker = {ticker: _sorted_prices(series) for ticker, series in prices.items()}
    all_days = sorted(
        {day for series in series_by_ticker.values() for day, _ in series}
    )
    start = rebalances[0].exec_date
    end = max(rebalance.hold_end_date for rebalance in rebalances)
    trading_days = [day for day in all_days if start <= day <= end]
    if not trading_days:
        trading_days = [start]

    cash = initial_cash
    positions: dict[str, float] = {}
    trades: list[Trade] = []
    missing_prices: list[str] = []
    delisted_holdings: list[str] = []
    equity_points: list[EquityPoint] = []
    buy_values: list[float] = []

    for day in trading_days:
        if day in targets:
            target_weights = targets[day]
            current_prices: dict[str, float] = {}
            current_positions_value = 0.0
            for ticker, shares in positions.items():
                price = _latest_price(series_by_ticker.get(ticker, []), day)
                if price is not None:
                    current_prices[ticker] = price
                    current_positions_value += shares * price
            equity_before = cash + current_positions_value
            if equity_before <= 0:
                equity_before = initial_cash

            available_target_prices: dict[str, float] = {}
            for ticker in target_weights:
                price = _latest_price(series_by_ticker.get(ticker, []), day)
                if price is not None and price > 0:
                    available_target_prices[ticker] = price
            target_shares, allocated, missing = compute_target_shares(
                target_weights, equity_before, available_target_prices, fractional
            )
            missing_prices.extend(missing)

            # A target that is already held but has no executable price is sold
            # at its last available price and treated as delisted.
            for ticker, _weight in target_weights.items():
                if (
                    ticker in positions
                    and positions[ticker] > 0
                    and ticker not in target_shares
                ):
                    target_shares[ticker] = 0.0
                    if ticker not in missing_prices:
                        missing_prices.append(ticker)
                    if ticker not in delisted_holdings:
                        delisted_holdings.append(ticker)

            prices_for_trades = {**current_prices, **available_target_prices}
            deltas = trade_deltas(positions, target_shares, prices_for_trades)
            costs = sum(delta["value"] * cost_rate for delta in deltas)
            cash = equity_before - allocated - costs
            for delta in deltas:
                value = delta["value"]
                cost = value * cost_rate
                reason = _trade_reason(
                    delta["ticker"], positions, target_shares, delta["side"]
                )
                trades.append(
                    Trade(
                        date=day,
                        ticker=delta["ticker"],
                        side=delta["side"],
                        shares=delta["shares"],
                        price=delta["price"],
                        value=value,
                        cost=cost,
                        reason=reason,
                    )
                )
                if delta["side"] == "BUY":
                    buy_values.append(value)
            positions = target_shares

        mark_prices: dict[str, float | None] = {
            ticker: _latest_price(series_by_ticker.get(ticker, []), day)
            for ticker in positions
        }
        # Mark only positions whose price is available; missing marks retain
        # their last known value through ``mark_to_market`` by excluding them.
        markable = {
            ticker: price for ticker, price in mark_prices.items() if price is not None
        }
        equity = mark_to_market(cash, positions, markable)
        equity_points.append(EquityPoint(date=day, value=equity))

    costs_total = sum(trade.cost for trade in trades)
    total_buys = sum(buy_values)
    average_value = (
        sum(point.value for point in equity_points) / len(equity_points)
        if equity_points
        else initial_cash
    )
    days = max(1, (end - start).days)
    period_years = days / 365.0
    turnover = (total_buys / average_value / period_years) if average_value else 0.0

    final_positions = dict(positions)
    final_prices: dict[str, float] = {}
    for ticker in positions:
        price = _latest_price(series_by_ticker.get(ticker, []), end)
        if price is not None:
            final_prices[ticker] = price

    return SimulationResult(
        equity=equity_points,
        trades=trades,
        costs_total=costs_total,
        turnover=turnover,
        final_positions=final_positions,
        final_prices=final_prices,
        missing_prices=missing_prices,
        delisted_holdings=delisted_holdings,
    )
