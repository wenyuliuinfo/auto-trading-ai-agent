"""Fundamentals merge tests: one failing vendor must not break the run."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.fundamentals import fetch_fundamentals


def _finnhub_raw() -> dict[str, object]:
    return {
        "source": "finnhub",
        "price": 150.0,
        "diluted_eps_ttm": 5.0,
        "market_cap": 100_000_000_000.0,
        "total_debt": 20_000_000_000.0,
        "cash": 5_000_000_000.0,
        "ebitda_ttm": 15_000_000_000.0,
        "revenue_ttm": 40_000_000_000.0,
        "revenue_growth_yoy": 0.12,
        "eps_growth_yoy": 0.18,
        "net_income_ttm": 8_000_000_000.0,
        "shareholders_equity": 50_000_000_000.0,
        "gross_profit_ttm": 18_000_000_000.0,
        "free_cash_flow_ttm": 6_000_000_000.0,
    }


def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.integrations.fundamentals.get_settings",
        lambda: SimpleNamespace(stub_agents=False),
    )


def _raise(message: str):
    def raise_error(ticker: str) -> dict[str, object]:
        raise RuntimeError(message)

    return raise_error


def test_fetch_fundamentals_uses_finnhub_when_fmp_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: FMP 403 + Finnhub 200 must merge, not raise AssertionError."""
    _stub_settings(monkeypatch)
    monkeypatch.setattr(
        "app.integrations.fundamentals.fetch_fmp_fundamentals",
        _raise("403 Forbidden"),
    )
    monkeypatch.setattr(
        "app.integrations.fundamentals.fetch_finnhub_fundamentals",
        lambda ticker: _finnhub_raw(),
    )

    fundamentals = fetch_fundamentals("WAB")
    assert fundamentals.source == "finnhub"
    assert fundamentals.price == 150.0
    assert fundamentals.market_cap == 100_000_000_000.0


def test_fetch_fundamentals_raises_only_when_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_settings(monkeypatch)
    monkeypatch.setattr(
        "app.integrations.fundamentals.fetch_fmp_fundamentals",
        _raise("fmp down"),
    )
    monkeypatch.setattr(
        "app.integrations.fundamentals.fetch_finnhub_fundamentals",
        _raise("finnhub down"),
    )

    with pytest.raises(RuntimeError, match="no fundamentals source available"):
        fetch_fundamentals("WAB")
