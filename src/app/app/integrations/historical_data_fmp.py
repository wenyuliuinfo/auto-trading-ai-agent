"""FMP-backed point-in-time historical store for the Backtest agent."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from app.config import get_settings
from app.integrations.etf_holdings import fetch_etf_holdings as fetch_seed_etf_holdings
from app.integrations.fundamentals import Fundamentals
from app.integrations.reference_universe import get_reference_universe
from app.integrations.yfinance_client import PriceHistory
from app.logging_conf import get_logger

logger = get_logger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"


class DataBudgetExceeded(RuntimeError):
    """Raised when the configured per-backtest FMP call budget is exhausted."""


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("historical", "holdings", "data", "results"):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, dict)]
        if isinstance(payload, dict):
            return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _first_row(payload: Any) -> dict[str, Any]:
    rows = _rows(payload)
    return rows[0] if rows else {}


class FmpStore:
    """Real FMP data with explicit as-of slicing and a per-job cache."""

    def __init__(self, cfg: dict[str, Any], theme_config: dict[str, Any]) -> None:
        self.cfg = cfg
        self.theme_config = theme_config
        self.sub_exposures = list(theme_config.get("sub_exposures", []))
        data_cfg = cfg.get("data", {})
        self.max_calls = int(data_cfg.get("max_fmp_calls_per_backtest", 4000))
        self.timeout = float(data_cfg.get("fmp_timeout_s", 30))
        self.max_retries = int(data_cfg.get("fmp_max_retries", 3))
        self.requests_per_minute = int(data_cfg.get("fmp_requests_per_minute", 300))
        self.allow_stub_results = bool(data_cfg.get("allow_stub_results", False))
        self.statement_field = str(
            data_cfg.get("statement_availability_field", "filingDate")
        )
        self.snapshot_max_age_days = int(
            cfg.get("signals", {}).get("thematic", {}).get(
                "etf_snapshot_max_age_days", 100
            )
        )
        self._call_count = 0
        self._lock = threading.Lock()
        self._last_call_at = 0.0
        self._price_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self._fundamentals_cache: dict[tuple[str, date], Fundamentals] = {}
        self._market_cap_cache: dict[tuple[str, date], float] = {}
        self._etf_cache: dict[tuple[str, date], list[dict[str, Any]]] = {}
        self._benchmark_cache: dict[str, dict[date, float]] = {}
        self._known_tickers: set[str] = set()
        self._dated_holdings_used = False
        self._etf_holder_endpoint_supported: bool | None = None
        self._market_cap_endpoint_supported: bool | None = None
        self._reference = self._load_reference()
        self._settings = get_settings()
        if not self._settings.fmp_api_key:
            raise RuntimeError("FMP_API_KEY is not configured")

    def _load_reference(self) -> dict[str, dict[str, Any]]:
        try:
            universe = get_reference_universe()
        except Exception as exc:
            logger.warning("reference_universe_failed", error=str(exc))
            universe = pd.DataFrame(
                columns=[
                    "ticker",
                    "company_name",
                    "gics_subindustry",
                    "market_cap",
                    "avg_dollar_volume",
                ]
            )
        return {
            str(row["ticker"]).upper(): {
                "ticker": str(row["ticker"]).upper(),
                "company_name": row.get("company_name") or f"{row['ticker']} Inc.",
                "gics_subindustry": row.get("gics_subindustry") or "Unclassified",
                "market_cap": _as_float(row.get("market_cap")) or 10_000_000_000,
                "avg_dollar_volume": _as_float(row.get("avg_dollar_volume"))
                or 100_000_000,
            }
            for _, row in universe.iterrows()
        }

    # --- FMP transport -------------------------------------------------------

    def _call(self, endpoint: str, params: dict[str, Any]) -> Any:
        with self._lock:
            if self._call_count >= self.max_calls:
                raise DataBudgetExceeded("FMP call budget exceeded")
            interval = 60.0 / self.requests_per_minute if self.requests_per_minute else 0
            wait = interval - (time.monotonic() - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
            self._call_count += 1
            self._last_call_at = time.monotonic()

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(
                        f"{FMP_BASE_URL}{endpoint}",
                        params={**params, "apikey": self._settings.fmp_api_key},
                    )
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

    # --- Price data ----------------------------------------------------------

    def _fetch_price_frame(self, ticker: str) -> pd.DataFrame:
        end = date.today()
        start = end - timedelta(days=int(365 * 8))
        try:
            payload = self._call(
                "/historical-price-eod/full",
                {
                    "symbol": ticker,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                },
            )
            rows = _rows(payload)
        except Exception as exc:
            logger.warning("fmp_full_price_failed", ticker=ticker, error=str(exc))
            rows = []
        if not rows:
            payload = self._call(
                "/historical-price-eod/light",
                {
                    "symbol": ticker,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                },
            )
            rows = _rows(payload)
        if not rows:
            return pd.DataFrame()
        parsed: list[dict[str, Any]] = []
        for row in rows:
            day = _as_date(row.get("date"))
            if day is None:
                continue
            close = _as_float(row.get("close") or row.get("price"))
            if close is None:
                continue
            adj_close = (
                _as_float(row.get("adjClose") or row.get("adjustedClose"))
                or close
            )
            high = _as_float(row.get("high")) or close
            low = _as_float(row.get("low")) or close
            open_price = _as_float(row.get("open")) or close
            volume = _as_float(row.get("volume") or row.get("unadjustedVolume")) or 0.0
            parsed.append(
                {
                    "date": day,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "adj_close": adj_close,
                    "volume": volume,
                }
            )
        frame = pd.DataFrame(parsed).set_index("date").sort_index()
        return frame

    def _ensure_price(self, ticker: str) -> pd.DataFrame:
        ticker = ticker.upper()
        self._known_tickers.add(ticker)
        if ticker not in self._price_cache:
            try:
                frame = self._fetch_price_frame(ticker)
            except Exception as exc:
                logger.warning("fmp_price_failed", ticker=ticker, error=str(exc))
                frame = pd.DataFrame()
            self._price_cache[(ticker, "full")] = frame
        return self._price_cache[(ticker, "full")]

    def _slice_price(
        self, ticker: str, as_of: date, series: str = "split"
    ) -> pd.DataFrame:
        frame = self._ensure_price(ticker)
        if frame.empty:
            return frame
        sliced = frame.loc[:as_of]
        column = "close" if series == "raw" else "adj_close"
        result = sliced[["high", "low", "volume", column]].rename(
            columns={column: "close"}
        ).copy()
        return result

    def make_price_fetcher(self, as_of: date) -> Callable[..., PriceHistory]:
        def fetch(ticker: str, lookback_days: int = 504) -> PriceHistory:
            frame = self._slice_price(ticker, as_of, "split").tail(lookback_days)
            if frame.empty:
                raise RuntimeError(f"FMP returned no price history for {ticker}")
            return PriceHistory(
                ticker=ticker,
                close=frame["close"].astype(float),
                volume=frame["volume"].astype(float),
                source="fmp",
            )

        return fetch

    def ohlcv(self, tickers: list[str], as_of: date) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            frame = self._slice_price(ticker, as_of, "split")
            if not frame.empty:
                result[ticker] = frame[["close", "high", "low", "volume"]]
        return result

    def total_return_prices(self) -> dict[str, dict[date, float]]:
        result: dict[str, dict[date, float]] = {}
        for ticker in sorted(self._known_tickers):
            frame = self._ensure_price(ticker)
            if frame.empty:
                continue
            result[ticker] = {
                day.date() if hasattr(day, "date") else day: float(row["adj_close"])
                for day, row in frame.iterrows()
            }
        return result

    # --- Benchmarks ----------------------------------------------------------

    def _benchmark_frame(self, name: str) -> dict[date, float]:
        if name in self._benchmark_cache:
            return self._benchmark_cache[name]
        frame = self._ensure_price(name)
        prices = {
            day.date() if hasattr(day, "date") else day: float(row["adj_close"])
            for day, row in frame.iterrows()
        }
        self._benchmark_cache[name] = prices
        return prices

    def benchmark_prices(self, name: str) -> dict[date, float]:
        try:
            return self._benchmark_frame(name)
        except Exception as exc:
            logger.warning("fmp_benchmark_failed", benchmark=name, error=str(exc))
            return {}

    def trading_days(self) -> list[date]:
        qqq = self.benchmark_prices("QQQ")
        if qqq:
            return sorted(qqq)
        return sorted(
            day.date() for day in pd.bdate_range("2018-01-01", date.today())
        )

    # --- Fundamentals --------------------------------------------------------

    def _availability_date(self, row: dict[str, Any]) -> date | None:
        values: list[date] = []
        for field in (self.statement_field, "acceptedDate", "filingDate", "date"):
            parsed = _as_date(row.get(field))
            if parsed is not None:
                values.append(parsed)
        return max(values) if values else None

    def _statements(self, ticker: str, statement: str, as_of: date) -> list[dict[str, Any]]:
        payload = self._call(
            f"/{statement}",
            {"symbol": ticker, "period": "quarter", "limit": 40},
        )
        rows = _rows(payload)
        result: list[dict[str, Any]] = []
        for row in rows:
            available = self._availability_date(row)
            if available is not None and available <= as_of:
                result.append({**row, "_available": available})
        return result

    def _annual_statements(self, ticker: str, as_of: date) -> list[dict[str, Any]]:
        payload = self._call(
            "/income-statement",
            {"symbol": ticker, "period": "annual", "limit": 8},
        )
        rows = _rows(payload)
        return [
            row
            for row in rows
            if (available := self._availability_date(row)) is not None
            and available <= as_of
        ]

    def _historical_market_cap(self, ticker: str, as_of: date) -> float | None:
        key = (ticker, as_of)
        if key in self._market_cap_cache:
            return self._market_cap_cache[key]
        if self._market_cap_endpoint_supported is not False:
            try:
                payload = self._call(
                    "/historical-market-capitalization",
                    {
                        "symbol": ticker,
                        "from": (as_of - timedelta(days=10)).isoformat(),
                        "to": as_of.isoformat(),
                    },
                )
                rows = _rows(payload)
                best: tuple[date, float] | None = None
                for row in rows:
                    day = _as_date(row.get("date"))
                    value = _as_float(row.get("marketCap") or row.get("market_cap"))
                    if (
                        day is not None
                        and value is not None
                        and day <= as_of
                        and (best is None or day > best[0])
                    ):
                        best = (day, value)
                if best is not None:
                    self._market_cap_cache[key] = best[1]
                    self._market_cap_endpoint_supported = True
                    return best[1]
            except Exception as exc:
                if "404" in str(exc):
                    if self._market_cap_endpoint_supported is None:
                        logger.info(
                            "fmp_historical_market_cap_unavailable",
                            reason="404 Not Found",
                        )
                    self._market_cap_endpoint_supported = False
                else:
                    logger.warning(
                        "fmp_market_cap_failed", ticker=ticker, error=str(exc)
                    )
        fallback = self._reference.get(ticker, {}).get("market_cap")
        return _as_float(fallback)

    def _fundamentals(self, ticker: str, as_of: date) -> Fundamentals:
        key = (ticker.upper(), as_of)
        if key in self._fundamentals_cache:
            return self._fundamentals_cache[key]

        frame = self._slice_price(ticker, as_of, "raw")
        price = float(frame["close"].iloc[-1]) if not frame.empty else None
        income = self._statements(ticker, "income-statement", as_of)
        balance = self._statements(ticker, "balance-sheet-statement", as_of)
        cash_flow = self._statements(ticker, "cash-flow-statement", as_of)
        latest_balance = balance[0] if balance else {}
        latest_cash_flow = cash_flow[0] if cash_flow else {}
        market_cap = self._historical_market_cap(ticker, as_of) or _as_float(
            latest_balance.get("marketCap")
        )

        def _sum(field: str, count: int = 4) -> float | None:
            values = [_as_float(row.get(field)) for row in income[:count]]
            finite = [value for value in values if value is not None]
            return sum(finite) if finite else None

        revenue_ttm = _sum("revenue")
        net_income_ttm = _sum("netIncome")
        gross_profit_ttm = _sum("grossProfit")
        ebitda_ttm = _sum("ebitda")
        eps_values = [
            _as_float(row.get("epsDiluted")) for row in income[:4]
        ]
        finite_eps = [value for value in eps_values if value is not None]
        diluted_eps_ttm = sum(finite_eps) if finite_eps else None

        annual = self._annual_statements(ticker, as_of)
        current_annual = annual[0] if annual else {}
        previous_annual = annual[1] if len(annual) > 1 else {}

        def _growth(current: float | None, prior: float | None) -> float | None:
            if current is None or prior is None or prior == 0:
                return None
            return current / prior - 1

        revenue_growth = _growth(
            _as_float(current_annual.get("revenue")),
            _as_float(previous_annual.get("revenue")),
        )
        eps_growth = _growth(
            _as_float(current_annual.get("epsDiluted"))
            or _as_float(current_annual.get("eps")),
            _as_float(previous_annual.get("epsDiluted"))
            or _as_float(previous_annual.get("eps")),
        )
        fundamentals = Fundamentals(
            ticker=ticker.upper(),
            price=price,
            diluted_eps_ttm=diluted_eps_ttm,
            market_cap=market_cap,
            total_debt=_as_float(latest_balance.get("totalDebt")),
            cash=_as_float(latest_balance.get("cashAndCashEquivalents")),
            ebitda_ttm=ebitda_ttm,
            revenue_ttm=revenue_ttm,
            revenue_growth_yoy=revenue_growth,
            eps_growth_yoy=eps_growth,
            net_income_ttm=net_income_ttm,
            shareholders_equity=_as_float(
                latest_balance.get("totalStockholdersEquity")
            ),
            gross_profit_ttm=gross_profit_ttm,
            free_cash_flow_ttm=_as_float(latest_cash_flow.get("freeCashFlow")),
            source="fmp",
        )
        self._fundamentals_cache[key] = fundamentals
        return fundamentals

    def make_fundamentals_fetcher(self, as_of: date) -> Callable[..., Fundamentals]:
        def fetch(ticker: str) -> Fundamentals:
            return self._fundamentals(ticker, as_of)

        return fetch

    # --- ETF holdings --------------------------------------------------------

    def _fetch_etf_holdings(
        self, etf: str, as_of: date
    ) -> list[dict[str, Any]]:
        key = (etf, as_of)
        if key in self._etf_cache:
            return self._etf_cache[key]

        candidates: list[Any] = []
        if self._etf_holder_endpoint_supported is not False:
            for include_date in (True, False):
                try:
                    params: dict[str, Any] = {"symbol": etf, "limit": 10000}
                    if include_date:
                        params["date"] = as_of.isoformat()
                    payload = self._call("/etf/holdings", params)
                    candidates = _rows(payload)
                except DataBudgetExceeded:
                    raise
                except Exception as exc:
                    if "404" in str(exc):
                        if self._etf_holder_endpoint_supported is None:
                            logger.info(
                                "fmp_etf_holder_unavailable",
                                reason="404 Not Found",
                            )
                        self._etf_holder_endpoint_supported = False
                        break
                    logger.warning(
                        "fmp_etf_holdings_failed",
                        etf=etf,
                        dated=include_date,
                        error=str(exc),
                    )
                if candidates:
                    self._etf_holder_endpoint_supported = True
                    break

        holdings: list[dict[str, Any]] = []
        if candidates:
            for row in candidates:
                ticker = row.get("symbol") or row.get("ticker") or row.get("asset")
                if not ticker or str(ticker).upper() in {"CASH", "-", "USD"}:
                    continue
                snapshot_date = _as_date(
                    row.get("date")
                    or row.get("snapshotDate")
                    or row.get("filingDate")
                )
                if snapshot_date is not None:
                    self._dated_holdings_used = True
                holdings.append(
                    {
                        "ticker": str(ticker).upper(),
                        "weight": _as_float(
                            row.get("weight")
                            or row.get("weightPercent")
                            or row.get("weightPercentage")
                            or row.get("weight_percent")
                        ),
                        "source": f"etf_holdings:{etf}",
                        "snapshot_date": snapshot_date,
                    }
                )
        else:
            # Seed holdings keep the strategy runnable when FMP lacks an ETF
            # constituent endpoint. They are current, not point-in-time.
            for record in fetch_seed_etf_holdings(etf).to_dict("records"):
                holdings.append(
                    {
                        "ticker": str(record.get("ticker")).upper(),
                        "weight": _as_float(record.get("weight")),
                        "source": f"etf_holdings:{etf}",
                        "snapshot_date": None,
                    }
                )

        self._etf_cache[key] = holdings
        return holdings

    def etf_universe(
        self, sub_exposures: list[str], as_of: date
    ) -> dict[str, list[dict[str, Any]]]:
        from app.config import load_sub_exposure_etf_map

        etf_map = load_sub_exposure_etf_map()
        result: dict[str, list[dict[str, Any]]] = {}
        for sub_exposure in sub_exposures:
            hits: dict[str, dict[str, Any]] = {}
            for etf in etf_map.get(sub_exposure, []):
                for holding in self._fetch_etf_holdings(etf, as_of):
                    ticker = holding["ticker"]
                    snapshot_date = holding.get("snapshot_date") or as_of
                    if snapshot_date > as_of:
                        continue
                    age = (as_of - snapshot_date).days
                    if age > self.snapshot_max_age_days:
                        continue
                    reference = self._reference.get(ticker)
                    hits.setdefault(
                        ticker,
                        {
                            "ticker": ticker,
                            "company_name": (reference or {}).get("company_name"),
                            "gics_subindustry": (reference or {}).get(
                                "gics_subindustry"
                            ),
                            "market_cap": self._historical_market_cap(ticker, as_of)
                            or (reference or {}).get("market_cap"),
                            "avg_dollar_volume": (reference or {}).get(
                                "avg_dollar_volume"
                            ),
                            "sub_exposure": sub_exposure,
                            "source": holding["source"],
                            "snapshot_date": snapshot_date,
                        },
                    )
            result[sub_exposure] = list(hits.values())
        return result

    def etf_membership(self, as_of: date) -> dict[str, set[str]]:
        membership: dict[str, set[str]] = {}
        universe = self.etf_universe(self.sub_exposures, as_of)
        for hits in universe.values():
            for hit in hits:
                membership.setdefault(hit["ticker"], set()).update(
                    source.split(":", 1)[1]
                    for source in [hit.get("source")]
                    if source
                )
        return membership

    def reference_rows(self, as_of: date) -> list[dict[str, Any]]:
        return [
            {
                **row,
                "source": "index:russell3000",
            }
            for row in self._reference.values()
        ]

    async def prefetch(
        self,
        theme_config: dict[str, Any],
        schedule: list[Any],
        progress: Callable[[str, int, int], None],
    ) -> None:
        import asyncio

        def warm() -> None:
            progress("fetching_data", 0, len(schedule))
            self.benchmark_prices("QQQ")
            self.benchmark_prices("SPY")
            for index, rebalance in enumerate(schedule, start=1):
                self.etf_universe(self.sub_exposures, rebalance.signal_date)
                progress("fetching_data", index, len(schedule))

        await asyncio.to_thread(warm)

    def provenance(self) -> dict[str, Any]:
        return {
            "data_source": "fmp",
            "data_version": "fmp",
            "flags": [] if self._dated_holdings_used else ["universe_not_point_in_time"],
        }
