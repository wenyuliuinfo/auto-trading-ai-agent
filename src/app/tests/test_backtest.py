"""Backtest engine, agent, persistence, and API contract tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.agents.backtest import execute_backtest, load_backtest_config
from app.backtest.calendar import build_schedule
from app.backtest.signals import etf_breadth, money_flow_ratio
from app.backtest.simulate import simulate
from app.backtest.types import Rebalance
from app.data.queries import (
    create_backtest_run,
    create_run,
    create_theme,
    get_latest_backtest,
)
from app.integrations.historical_data_stub import _stub_trading_days


def _enabled_config() -> dict[str, object]:
    cfg = load_backtest_config()
    cfg["_force_stub_store"] = True
    cfg["modes"] = {
        "trailing": {**cfg["modes"]["trailing"], "enabled": True},
        "full": {**cfg["modes"]["full"], "enabled": True},
    }
    return cfg


def test_build_schedule_full_has_twenty_rebalances() -> None:
    cfg = _enabled_config()
    trading_days = _stub_trading_days(date(2020, 12, 1), date(2025, 12, 31))
    schedule = build_schedule("full", cfg, date(2026, 10, 5), trading_days)
    assert len(schedule) == 20
    assert schedule[0].exec_date == date(2021, 1, 4)
    assert schedule[-1].hold_end_date == date(2025, 12, 31)


def test_build_schedule_trailing_completed_periods() -> None:
    cfg = _enabled_config()
    trading_days = _stub_trading_days(date(2023, 1, 1), date(2026, 10, 5))
    schedule = build_schedule("trailing", cfg, date(2026, 10, 5), trading_days)
    assert 4 <= len(schedule) <= 5
    assert schedule[-1].hold_end_date <= date(2026, 10, 5)


def test_signals_are_deterministic_and_bounded() -> None:
    breadth = etf_breadth(["AAPL", "MSFT"], {"AAPL": {"XLK", "AIQ"}, "MSFT": {"XLK"}})
    assert breadth == [2.0, 1.0]

    dates = pd.bdate_range("2025-01-01", periods=130)
    close = pd.Series(range(1, 131), index=dates, dtype=float)
    frame = pd.DataFrame(
        {
            "close": close,
            "high": close + 2,
            "low": close - 2,
            "volume": pd.Series(100.0, index=dates),
        }
    )
    ratio = money_flow_ratio({"AAA": frame}, min_obs=100)
    assert -1.0 <= ratio[0] <= 1.0


def test_simulate_accounting_identity() -> None:
    rebalances = [
        Rebalance(idx=0, signal_date=date(2025, 1, 2), exec_date=date(2025, 1, 3), hold_end_date=date(2025, 1, 4)),
        Rebalance(idx=1, signal_date=date(2025, 1, 3), exec_date=date(2025, 1, 4), hold_end_date=date(2025, 1, 5)),
    ]
    prices = {
        "AAA": {
            date(2025, 1, 3): 100.0,
            date(2025, 1, 4): 110.0,
            date(2025, 1, 5): 105.0,
        }
    }
    targets = {
        date(2025, 1, 3): {"AAA": 1.0},
        date(2025, 1, 4): {"AAA": 1.0},
    }
    cfg = {
        "capital": {
            "initial_cash": 10000,
            "fractional_shares": True,
            "transaction_cost_bps_per_side": 10,
        }
    }
    result = simulate(rebalances, targets, prices, cfg)
    assert result.equity
    final_value = result.equity[-1].value
    assert final_value > 0
    assert result.costs_total > 0


@pytest.mark.asyncio
async def test_execute_backtest_stub_persists_result(db: None, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.backtest.load_backtest_config", _enabled_config
    )
    theme = await create_theme(
        "Grid modernization",
        "Electrification of transmission, smart grid, storage.",
        {
            "sub_exposures": [
                "transmission_equipment",
                "smart_grid",
                "battery_storage",
                "utilities",
            ],
            "factor_weights": {
                "thematic_z": 0.27,
                "growth_z": 0.18,
                "quality_z": 0.13,
                "valuation_z": 0.13,
                "momentum_z": 0.09,
                "sentiment_z": 0.10,
                "liquidity_z": 0.05,
                "volatility_z": 0.05,
            },
            "screens": {
                "min_avg_dollar_volume": 5_000_000,
                "min_market_cap": 300_000_000,
                "max_per_sub_industry": 3,
            },
            "weighting_scheme": "equal_weight",
            "validator_enabled": True,
        },
    )
    run = await create_run(theme["theme_id"])
    backtest_id = "00000000-0000-0000-0000-000000000012"
    row = await create_backtest_run(
        run["run_id"],
        "trailing",
        _enabled_config(),
        "hash",
    )
    backtest_id = row["backtest_id"]

    await execute_backtest(backtest_id, run["run_id"], "trailing")

    row = await get_latest_backtest(run["run_id"], "trailing")
    assert row is not None
    assert row["status"] in {"succeeded", "partial"}
    assert row["data_source"] == "stub"


def test_backtest_full_mode_returns_disabled_and_409(client, monkeypatch) -> None:
    async def fake_get_run(run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "theme_id": "00000000-0000-0000-0000-000000000001",
            "status": "complete",
            "requested_at": "now",
            "retry_count": 0,
            "error_detail": None,
        }

    monkeypatch.setattr("app.api.backtest.get_run", fake_get_run)
    response = client.post("/runs/fake/backtest", json={"mode": "full"})
    assert response.status_code == 409
    response = client.get("/runs/fake/backtest?mode=full")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
