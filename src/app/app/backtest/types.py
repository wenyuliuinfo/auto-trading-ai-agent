"""Shared dataclasses for the pure backtest engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Rebalance:
    """One scheduled rebalance window.

    ``signal_date`` is the last trading day before ``exec_date``. ``hold_end_date``
    is the next rebalance execution date, or a truncated period end. An
    in-progress trailing period ends at the run date.
    """

    idx: int
    signal_date: date
    exec_date: date
    hold_end_date: date
    in_progress: bool = False


@dataclass
class RebalanceResult:
    idx: int
    signal_date: date
    exec_date: date
    hold_end_date: date
    basket: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    near_misses: list[dict[str, Any]] = field(default_factory=list)
    inputs_summary: dict[str, Any] = field(default_factory=dict)
    in_progress: bool = False


@dataclass(frozen=True)
class Trade:
    date: date
    ticker: str
    side: str
    shares: float
    price: float
    value: float
    cost: float
    reason: str


@dataclass(frozen=True)
class EquityPoint:
    date: date
    value: float


@dataclass
class SimulationResult:
    equity: list[EquityPoint]
    trades: list[Trade]
    costs_total: float
    turnover: float
    final_positions: dict[str, float] = field(default_factory=dict)
    final_prices: dict[str, float] = field(default_factory=dict)
    missing_prices: list[str] = field(default_factory=list)
    delisted_holdings: list[str] = field(default_factory=list)


@dataclass
class BenchmarkSeries:
    name: str
    points: list[EquityPoint]


@dataclass
class BacktestResult:
    run_id: str
    mode: str
    status: str
    data_source: str
    period_start: date | None
    period_end: date | None
    initial_cash: float
    summary: dict[str, Any]
    series: dict[str, list[EquityPoint]]
    rebalances: list[RebalanceResult]
    attribution: list[dict[str, Any]]
    trades: list[Trade]
    costs_total: float
    current_holdings: list[dict[str, Any]]
    flags: list[str]
    disclaimer: str
    methodology_version: int
    config_hash: str
    code_version: str
    data_version: str
    progress: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
