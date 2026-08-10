"""Normalized fundamentals across FMP + Finnhub (Hard Rule 11)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.integrations.finnhub import fetch_finnhub_fundamentals
from app.integrations.fmp import fetch_fmp_fundamentals
from app.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass
class Fundamentals:
    ticker: str
    price: float | None
    diluted_eps_ttm: float | None
    market_cap: float | None
    total_debt: float | None
    cash: float | None
    ebitda_ttm: float | None
    revenue_ttm: float | None
    revenue_growth_yoy: float | None
    eps_growth_yoy: float | None
    net_income_ttm: float | None
    shareholders_equity: float | None
    gross_profit_ttm: float | None
    free_cash_flow_ttm: float | None
    source: str


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stub_fundamentals(ticker: str) -> Fundamentals:
    """Deterministic pseudo-financials for offline/stub runs."""
    rng = random.Random(ticker)
    market_cap = rng.uniform(5e9, 8e11)
    price = rng.uniform(20.0, 400.0)
    eps = rng.uniform(0.5, 20.0)
    revenue = rng.uniform(2e9, 2e11)
    ebitda = revenue * rng.uniform(0.08, 0.35)
    net_income = revenue * rng.uniform(0.04, 0.25)
    equity = market_cap * rng.uniform(0.2, 0.8)
    return Fundamentals(
        ticker=ticker,
        price=price,
        diluted_eps_ttm=eps,
        market_cap=market_cap,
        total_debt=market_cap * rng.uniform(0.1, 0.6),
        cash=market_cap * rng.uniform(0.02, 0.15),
        ebitda_ttm=ebitda,
        revenue_ttm=revenue,
        revenue_growth_yoy=rng.uniform(-0.05, 0.35),
        eps_growth_yoy=rng.uniform(-0.10, 0.40),
        net_income_ttm=net_income,
        shareholders_equity=equity,
        gross_profit_ttm=revenue * rng.uniform(0.25, 0.75),
        free_cash_flow_ttm=net_income * rng.uniform(0.5, 1.5),
        source="stub",
    )


def _normalize(raw: dict[str, Any], ticker: str, source: str) -> Fundamentals:
    return Fundamentals(
        ticker=ticker,
        price=_as_float(raw.get("price")),
        diluted_eps_ttm=_as_float(raw.get("diluted_eps_ttm")),
        market_cap=_as_float(raw.get("market_cap")),
        total_debt=_as_float(raw.get("total_debt")),
        cash=_as_float(raw.get("cash")),
        ebitda_ttm=_as_float(raw.get("ebitda_ttm")),
        revenue_ttm=_as_float(raw.get("revenue_ttm")),
        revenue_growth_yoy=_as_float(raw.get("revenue_growth_yoy")),
        eps_growth_yoy=_as_float(raw.get("eps_growth_yoy")),
        net_income_ttm=_as_float(raw.get("net_income_ttm")),
        shareholders_equity=_as_float(raw.get("shareholders_equity")),
        gross_profit_ttm=_as_float(raw.get("gross_profit_ttm")),
        free_cash_flow_ttm=_as_float(raw.get("free_cash_flow_ttm")),
        source=source,
    )


def fetch_fundamentals(ticker: str) -> Fundamentals:
    """FMP first, Finnhub per-field fallback on gaps or failure.

    Either source may be unavailable (free-tier quota/plan errors, network
    failure); the merge uses whichever source(s) succeeded, filling missing
    fields from the other. Never raises just because one source failed.
    """
    settings = get_settings()
    if settings.stub_agents:
        return _stub_fundamentals(ticker)
    try:
        fmp_raw = fetch_fmp_fundamentals(ticker)
        fmp = _normalize(fmp_raw, ticker, "fmp")
    except Exception as exc:
        logger.warning("fmp_fundamentals_failed", ticker=ticker, error=str(exc))
        fmp = None
    try:
        finnhub_raw = fetch_finnhub_fundamentals(ticker)
        finnhub = _normalize(finnhub_raw, ticker, "finnhub")
    except Exception as exc:
        logger.warning("finnhub_fundamentals_failed", ticker=ticker, error=str(exc))
        finnhub = None
    if fmp is None and finnhub is None:
        raise RuntimeError(f"no fundamentals source available for {ticker}")
    sources = [fund for fund in (fmp, finnhub) if fund is not None]

    def first_value(values: list[float | None]) -> float | None:
        for value in values:
            if value is not None:
                return value
        return None

    merged = Fundamentals(
        ticker=ticker,
        price=first_value([fund.price for fund in sources]),
        diluted_eps_ttm=first_value([fund.diluted_eps_ttm for fund in sources]),
        market_cap=first_value([fund.market_cap for fund in sources]),
        total_debt=first_value([fund.total_debt for fund in sources]),
        cash=first_value([fund.cash for fund in sources]),
        ebitda_ttm=first_value([fund.ebitda_ttm for fund in sources]),
        revenue_ttm=first_value([fund.revenue_ttm for fund in sources]),
        revenue_growth_yoy=first_value([fund.revenue_growth_yoy for fund in sources]),
        eps_growth_yoy=first_value([fund.eps_growth_yoy for fund in sources]),
        net_income_ttm=first_value([fund.net_income_ttm for fund in sources]),
        shareholders_equity=first_value([fund.shareholders_equity for fund in sources]),
        gross_profit_ttm=first_value([fund.gross_profit_ttm for fund in sources]),
        free_cash_flow_ttm=first_value([fund.free_cash_flow_ttm for fund in sources]),
        source="+".join(fund.source for fund in sources),
    )
    return merged
