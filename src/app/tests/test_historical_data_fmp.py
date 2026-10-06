"""FmpStore point-in-time and dated-holdings tests using recorded fixtures."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.integrations.historical_data_fmp import FmpStore


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.payloads = {
            "/historical-price-eod/full": {
                "historical": [
                    {
                        "date": "2025-03-28",
                        "open": 90.0,
                        "high": 102.0,
                        "low": 89.0,
                        "close": 100.0,
                        "adjClose": 95.0,
                        "volume": 1_000_000,
                    },
                    {
                        "date": "2025-04-01",
                        "open": 100.0,
                        "high": 112.0,
                        "low": 99.0,
                        "close": 110.0,
                        "adjClose": 105.0,
                        "volume": 1_200_000,
                    },
                    {
                        "date": "2025-04-02",
                        "open": 110.0,
                        "high": 120.0,
                        "low": 108.0,
                        "close": 118.0,
                        "adjClose": 112.0,
                        "volume": 1_300_000,
                    },
                ]
            },
            "/etf/holdings": [
                {
                    "symbol": "AAPL",
                    "weight": 0.05,
                    "date": "2025-03-28",
                },
                {
                    "symbol": "MSFT",
                    "weight": 0.04,
                    "date": "2025-03-28",
                },
            ],
            "/historical-market-capitalization": [
                {"date": "2025-03-28", "marketCap": 3_000_000_000_000},
                {"date": "2025-04-01", "marketCap": 3_100_000_000_000},
            ],
            "/income-statement": [
                {
                    "date": "2025-03-31",
                    "filingDate": "2025-03-30",
                    "revenue": 100,
                    "netIncome": 20,
                    "grossProfit": 40,
                    "ebitda": 30,
                    "epsDiluted": 1.5,
                },
                {
                    "date": "2024-12-31",
                    "filingDate": "2025-01-20",
                    "revenue": 90,
                    "netIncome": 18,
                    "grossProfit": 36,
                    "ebitda": 27,
                    "epsDiluted": 1.4,
                },
                {
                    "date": "2025-04-05",
                    "filingDate": "2025-04-05",
                    "revenue": 120,
                    "netIncome": 25,
                },
            ],
            "/balance-sheet-statement": [
                {
                    "date": "2025-03-31",
                    "filingDate": "2025-03-30",
                    "totalDebt": 1000,
                    "cashAndCashEquivalents": 200,
                    "totalStockholdersEquity": 900,
                }
            ],
            "/cash-flow-statement": [
                {
                    "date": "2025-03-31",
                    "filingDate": "2025-03-30",
                    "freeCashFlow": 15,
                }
            ],
        }

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, params: dict[str, object] | None = None) -> FakeResponse:
        endpoint = url.split("financialmodelingprep.com/stable", 1)[1].split("?")[0]
        if endpoint == "/historical-market-capitalization":
            return FakeResponse(self.payloads["/historical-market-capitalization"])
        if endpoint == "/etf/holdings":
            return FakeResponse(self.payloads["/etf/holdings"])
        if endpoint == "/income-statement" and params and params.get("period") == "annual":
            return FakeResponse(
                [
                    {
                        "date": "2024-12-31",
                        "filingDate": "2025-01-20",
                        "revenue": 360,
                        "epsDiluted": 5.0,
                    },
                    {
                        "date": "2023-12-31",
                        "filingDate": "2024-01-20",
                        "revenue": 300,
                        "epsDiluted": 4.0,
                    },
                ]
            )
        return FakeResponse(self.payloads[endpoint])


def _store() -> FmpStore:
    return FmpStore(
        cfg={
            "data": {
                "provider": "fmp",
                "fmp_timeout_s": 10,
                "fmp_max_retries": 1,
                "fmp_requests_per_minute": 1000,
                "max_fmp_calls_per_backtest": 100,
                "statement_availability_field": "filingDate",
            },
            "signals": {
                "thematic": {"etf_snapshot_max_age_days": 100},
                "sentiment": {"window_trading_days": 126, "money_flow_min_obs": 100},
            },
        },
        theme_config={
            "sub_exposures": ["artificial_intelligence"],
            "factor_weights": {"thematic_z": 1.0},
        },
    )


def test_fmp_store_price_and_etf_views_obey_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.integrations.historical_data_fmp.get_settings",
        lambda: SimpleNamespace(fmp_api_key="test"),
    )
    monkeypatch.setattr(
        "app.integrations.historical_data_fmp.httpx.Client", FakeClient
    )
    store = _store()
    as_of = date(2025, 4, 1)

    prices = store.make_price_fetcher(as_of)("AAPL", lookback_days=504)
    assert prices.close.index.max() <= as_of
    assert prices.close.iloc[-1] == 105.0

    universe = store.etf_universe(["artificial_intelligence"], as_of)
    assert "AAPL" in {row["ticker"] for row in universe["artificial_intelligence"]}

    fundamentals = store.make_fundamentals_fetcher(as_of)("AAPL")
    assert fundamentals.price == 110.0
    assert fundamentals.revenue_ttm == 190.0
    assert fundamentals.revenue_growth_yoy == pytest.approx(0.2)


def test_fmp_store_excludes_future_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.integrations.historical_data_fmp.get_settings",
        lambda: SimpleNamespace(fmp_api_key="test"),
    )
    monkeypatch.setattr(
        "app.integrations.historical_data_fmp.httpx.Client", FakeClient
    )
    store = _store()
    as_of = date(2025, 4, 1)
    universe = store.etf_universe(["artificial_intelligence"], as_of)
    assert all(
        row["ticker"] != "AAPL" or row["snapshot_date"] <= as_of
        for row in universe["artificial_intelligence"]
    )
