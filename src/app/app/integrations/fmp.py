"""Financial Modeling Prep client (stable API: fundamentals + EOD prices)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd

from app.config import get_settings
from app.integrations.yfinance_client import PriceHistory
from app.logging_conf import get_logger

logger = get_logger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_TIMEOUT_SECONDS = 30.0


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    return [payload] if isinstance(payload, dict) else []


def _first(payload: Any) -> dict[str, Any]:
    for item in _as_list(payload):
        if isinstance(item, dict):
            return item
    return {}


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return current / prior - 1


def _get_json(
    client: httpx.Client, endpoint: str, params: dict[str, Any], api_key: str
) -> Any:
    """GET one stable FMP endpoint and fail on empty list responses."""
    response = client.get(
        f"{FMP_BASE_URL}{endpoint}", params={**params, "apikey": api_key}
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and not data:
        raise RuntimeError(f"FMP returned no data for {endpoint}")
    return data


def fetch_fmp_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch the pipeline's normalized fundamentals from FMP stable endpoints.

    FMP's current API does not expose the old ``/api/v3/ratios`` shape, so
    quote, TTM ratios/key metrics, and annual statements are combined into
    the same normalized dict the rest of the pipeline already consumes.
    """
    settings = get_settings()
    if not settings.fmp_api_key:
        raise RuntimeError("FMP_API_KEY is not configured")
    with httpx.Client(timeout=FMP_TIMEOUT_SECONDS) as client:
        quote = _first(
            _get_json(client, "/quote", {"symbol": ticker}, settings.fmp_api_key)
        )
        ratios_ttm = _first(
            _get_json(client, "/ratios-ttm", {"symbol": ticker}, settings.fmp_api_key)
        )
        key_metrics_ttm = _first(
            _get_json(
                client, "/key-metrics-ttm", {"symbol": ticker}, settings.fmp_api_key
            )
        )
        income_rows = _as_list(
            _get_json(
                client,
                "/income-statement",
                {"symbol": ticker, "period": "annual", "limit": 2},
                settings.fmp_api_key,
            )
        )
        balance = _first(
            _get_json(
                client,
                "/balance-sheet-statement",
                {"symbol": ticker, "period": "annual", "limit": 1},
                settings.fmp_api_key,
            )
        )
        cash_flow = _first(
            _get_json(
                client,
                "/cash-flow-statement",
                {"symbol": ticker, "period": "annual", "limit": 1},
                settings.fmp_api_key,
            )
        )
    if not income_rows:
        raise RuntimeError(f"FMP returned no income statement data for {ticker}")
    income = income_rows[0]
    previous = income_rows[1] if len(income_rows) > 1 else {}

    price = _as_float(quote.get("price"))
    market_cap = _as_float(quote.get("marketCap")) or _as_float(
        key_metrics_ttm.get("marketCap")
    )
    pe_ratio_ttm = _as_float(ratios_ttm.get("priceToEarningsRatioTTM"))
    diluted_eps_ttm = _safe_divide(price, pe_ratio_ttm) or _as_float(
        income.get("epsDiluted")
    )
    price_to_sales_ttm = _as_float(ratios_ttm.get("priceToSalesRatioTTM"))
    revenue_ttm = _safe_divide(market_cap, price_to_sales_ttm) or _as_float(
        income.get("revenue")
    )
    enterprise_value_ttm = _as_float(key_metrics_ttm.get("enterpriseValueTTM"))
    ev_to_ebitda_ttm = _as_float(key_metrics_ttm.get("evToEBITDATTM"))
    ebitda_ttm = _safe_divide(
        enterprise_value_ttm, ev_to_ebitda_ttm
    ) or _as_float(income.get("ebitda"))
    profit_margin_ttm = _as_float(ratios_ttm.get("bottomLineProfitMarginTTM"))
    earnings_yield_ttm = _as_float(key_metrics_ttm.get("earningsYieldTTM"))
    if revenue_ttm is not None and profit_margin_ttm is not None:
        net_income_ttm = revenue_ttm * profit_margin_ttm
    elif market_cap is not None and earnings_yield_ttm is not None:
        net_income_ttm = market_cap * earnings_yield_ttm
    else:
        net_income_ttm = None
    gross_margin_ttm = _as_float(ratios_ttm.get("grossProfitMarginTTM"))
    gross_profit_ttm = (
        revenue_ttm * gross_margin_ttm
        if revenue_ttm is not None and gross_margin_ttm is not None
        else None
    )
    ev_to_free_cash_flow_ttm = _as_float(key_metrics_ttm.get("evToFreeCashFlowTTM"))
    free_cash_flow_ttm = _safe_divide(
        enterprise_value_ttm, ev_to_free_cash_flow_ttm
    ) or _as_float(cash_flow.get("freeCashFlow"))

    return {
        "source": "fmp",
        "price": price,
        "diluted_eps_ttm": diluted_eps_ttm,
        "market_cap": market_cap,
        "total_debt": _as_float(balance.get("totalDebt")),
        "cash": _as_float(balance.get("cashAndCashEquivalents")),
        "ebitda_ttm": ebitda_ttm,
        "revenue_ttm": revenue_ttm,
        "revenue_growth_yoy": _growth(
            _as_float(income.get("revenue")), _as_float(previous.get("revenue"))
        ),
        "eps_growth_yoy": _growth(
            _as_float(income.get("epsDiluted")) or _as_float(income.get("eps")),
            _as_float(previous.get("epsDiluted")) or _as_float(previous.get("eps")),
        ),
        "net_income_ttm": net_income_ttm,
        "shareholders_equity": _as_float(balance.get("totalStockholdersEquity")),
        "gross_profit_ttm": gross_profit_ttm,
        "free_cash_flow_ttm": free_cash_flow_ttm,
    }


def fetch_fmp_prices(ticker: str, lookback_days: int = 504) -> PriceHistory:
    """Fetch normalized daily close/volume series from FMP EOD history."""
    settings = get_settings()
    if not settings.fmp_api_key:
        raise RuntimeError("FMP_API_KEY is not configured")
    end = date.today()
    start = end - timedelta(days=int(lookback_days * 1.9) + 90)
    with httpx.Client(timeout=FMP_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{FMP_BASE_URL}/historical-price-eod/light",
            params={
                "symbol": ticker,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "apikey": settings.fmp_api_key,
            },
        )
        response.raise_for_status()
        rows = response.json()
    if not rows:
        raise RuntimeError(f"FMP returned no price history for {ticker}")
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    if "volume" in frame:
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    else:
        frame["volume"] = float("nan")
    frame = frame.dropna(subset=["price"]).tail(lookback_days)
    if frame.empty:
        raise RuntimeError(f"FMP returned no usable price history for {ticker}")
    return PriceHistory(
        ticker=ticker,
        close=frame["price"].astype(float),
        volume=frame["volume"].astype(float),
        source="fmp",
    )
