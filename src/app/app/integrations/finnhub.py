"""Finnhub free-tier client (fundamentals fallback source)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_finnhub_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch normalized fundamentals from Finnhub quote + metric endpoints."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise RuntimeError("FINNHUB_API_KEY is not configured")
    with httpx.Client(timeout=30.0) as client:
        quote_response = client.get(
            f"{FINNHUB_BASE_URL}/quote",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
        )
        quote_response.raise_for_status()
        quote = quote_response.json()
        metric_response = client.get(
            f"{FINNHUB_BASE_URL}/stock/metric",
            params={
                "symbol": ticker,
                "metric": "all",
                "token": settings.finnhub_api_key,
            },
        )
        metric_response.raise_for_status()
        metric = (metric_response.json() or {}).get("metric", {})
    market_cap = _number(metric.get("marketCapitalization"))
    revenue_growth = _number(metric.get("revenueGrowthTTMYoy"))
    eps_growth = _number(metric.get("epsGrowthTTMYoy"))
    return {
        "source": "finnhub",
        "price": _number(quote.get("c")),
        "diluted_eps_ttm": _number(metric.get("epsTTM")),
        "market_cap": market_cap * 1_000_000 if market_cap is not None else None,
        "total_debt": _number(metric.get("totalDebt")),
        "cash": _number(metric.get("cashAndCashEquivalents")),
        "ebitda_ttm": _number(metric.get("ebitdaTTM")),
        "revenue_ttm": _number(metric.get("revenueTTM")),
        "revenue_growth_yoy": revenue_growth / 100 if revenue_growth is not None else None,
        "eps_growth_yoy": eps_growth / 100 if eps_growth is not None else None,
        "net_income_ttm": _number(metric.get("netIncomeTTM")),
        "shareholders_equity": _number(metric.get("totalStockholdersEquityTTM")),
        "gross_profit_ttm": _number(metric.get("grossProfitTTM")),
        "free_cash_flow_ttm": _number(metric.get("freeCashFlowTTM")),
    }
