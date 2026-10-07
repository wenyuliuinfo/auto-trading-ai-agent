"""Finnhub free-tier client (fundamentals fallback source)."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from app.config import get_settings

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_REQUESTS_PER_SECOND = 1.0
_RATE_LIMIT_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _throttle() -> None:
    """Space out Finnhub calls to avoid free-tier 429 responses."""
    global _LAST_REQUEST_AT
    interval = 1.0 / FINNHUB_REQUESTS_PER_SECOND
    with _RATE_LIMIT_LOCK:
        wait = interval - (time.monotonic() - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


def _get_json_with_retry(
    client: httpx.Client, url: str, params: dict[str, str]
) -> dict[str, Any]:
    """GET Finnhub, retrying transient 429 responses with backoff."""
    last_status = 0
    for attempt in range(3):
        _throttle()
        response = client.get(url, params=params)
        last_status = response.status_code
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 2**attempt
            time.sleep(delay)
            continue
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {}
    raise RuntimeError(f"Finnhub rate limit exceeded (HTTP {last_status})")


def fetch_finnhub_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch normalized fundamentals from Finnhub quote + metric endpoints."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise RuntimeError("FINNHUB_API_KEY is not configured")
    with httpx.Client(timeout=30.0) as client:
        quote = _get_json_with_retry(
            client,
            f"{FINNHUB_BASE_URL}/quote",
            {"symbol": ticker, "token": settings.finnhub_api_key},
        )
        metric_response = _get_json_with_retry(
            client,
            f"{FINNHUB_BASE_URL}/stock/metric",
            {
                "symbol": ticker,
                "metric": "all",
                "token": settings.finnhub_api_key,
            },
        )
        metric = metric_response.get("metric", {})
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
