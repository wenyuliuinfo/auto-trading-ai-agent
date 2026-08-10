"""Finnhub normalization tests (millions -> USD, percent -> fraction)."""

from __future__ import annotations

import pytest

from app.integrations.finnhub import fetch_finnhub_fundamentals


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, params: dict[str, object] | None = None) -> FakeResponse:
        if url.endswith("/quote"):
            return FakeResponse({"c": 100.0})
        if url.endswith("/stock/metric"):
            return FakeResponse(
                {
                    "metric": {
                        "marketCapitalization": "271116.94",
                        "revenueGrowthTTMYoy": 12.98,
                        "epsGrowthTTMYoy": 744.44,
                        "epsTTM": 10.0,
                    }
                }
            )
        raise AssertionError(f"unexpected Finnhub endpoint: {url}")


def test_finnhub_units_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.finnhub.httpx.Client", FakeClient)

    data = fetch_finnhub_fundamentals("GEV")

    assert data["market_cap"] == pytest.approx(271_116_940_000.0)
    assert data["revenue_growth_yoy"] == pytest.approx(0.1298)
    assert data["eps_growth_yoy"] == pytest.approx(7.4444)
