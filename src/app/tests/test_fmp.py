"""FMP stable API mapping tests for fundamentals and EOD prices."""

from __future__ import annotations

import pytest

from app.integrations.fmp import fetch_fmp_fundamentals, fetch_fmp_prices


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.payloads: dict[str, object] = {
            "/quote": [
                {"price": 1017.96, "marketCap": 271_116_951_456.0}
            ],
            "/ratios-ttm": [
                {
                    "priceToEarningsRatioTTM": 28.878,
                    "priceToSalesRatioTTM": 6.5538,
                    "bottomLineProfitMarginTTM": 0.230347,
                    "grossProfitMarginTTM": 0.202113,
                }
            ],
            "/key-metrics-ttm": [
                {
                    "enterpriseValueTTM": 261_956_951_456.0,
                    "evToEBITDATTM": 30.235,
                    "evToFreeCashFlowTTM": 21.059,
                    "earningsYieldTTM": 0.034929,
                }
            ],
            "/income-statement": [
                {"revenue": 38_068_000_000.0, "epsDiluted": 17.69},
                {"revenue": 34_942_000_000.0, "epsDiluted": 5.58},
            ],
            "/balance-sheet-statement": [
                {
                    "totalDebt": 0.0,
                    "cashAndCashEquivalents": 8_848_000_000.0,
                    "totalStockholdersEquity": 11_178_000_000.0,
                }
            ],
            "/cash-flow-statement": [{"freeCashFlow": 3_711_000_000.0}],
            "/historical-price-eod/light": [
                {"date": "2026-08-05", "price": 1017.96, "volume": 1_457_360},
                {"date": "2026-08-04", "price": 1001.0, "volume": 1_300_000},
                {"date": "2026-08-03", "price": 990.0, "volume": 1_200_000},
            ],
        }

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, params: dict[str, object] | None = None) -> FakeResponse:
        for endpoint, payload in self.payloads.items():
            if url.endswith(endpoint):
                return FakeResponse(payload)
        raise AssertionError(f"unexpected FMP endpoint: {url}")


def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.fmp.httpx.Client", FakeClient)


def test_fetch_fmp_fundamentals_maps_stable_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch)

    data = fetch_fmp_fundamentals("GEV")

    assert data["market_cap"] == 271_116_951_456.0
    assert data["diluted_eps_ttm"] == pytest.approx(35.25, rel=1e-3)
    assert data["revenue_ttm"] == pytest.approx(41_368_000_000.0, rel=1e-3)
    assert data["ebitda_ttm"] == pytest.approx(8_664_000_000.0, rel=1e-3)
    assert data["revenue_growth_yoy"] == pytest.approx(0.08943, rel=1e-3)
    assert data["eps_growth_yoy"] == pytest.approx(2.17025, rel=1e-3)
    assert data["gross_profit_ttm"] == pytest.approx(8_361_000_000.0, rel=1e-3)
    assert data["free_cash_flow_ttm"] == pytest.approx(12_439_000_000.0, rel=1e-3)


def test_fetch_fmp_prices_builds_close_and_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch)

    prices = fetch_fmp_prices("GEV", lookback_days=2)

    assert prices.source == "fmp"
    assert len(prices.close) == 2
    assert prices.close.iloc[0] == pytest.approx(1001.0)
    assert prices.close.iloc[-1] == pytest.approx(1017.96)
    assert prices.volume.iloc[-1] == pytest.approx(1_457_360)
