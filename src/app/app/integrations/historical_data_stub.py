"""Deterministic synthetic historical store for tests and labeled demos.

This module is intentionally the only production data module besides test
fixtures allowed to use randomness (BACKTEST_SKILL.md Rule 16).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pandas as pd
from dateutil.easter import easter

from app.config import CONFIG_DIR, load_sub_exposure_etf_map
from app.integrations.etf_holdings import fetch_etf_holdings
from app.integrations.fundamentals import Fundamentals
from app.integrations.yfinance_client import PriceHistory


def _quarter(as_of: date) -> int:
    return (as_of.month - 1) // 3 + 1


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth requested weekday in a month (1-based)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last requested weekday in a month."""
    first_next = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
    candidate = first_next - timedelta(days=1)
    return candidate - timedelta(days=(candidate.weekday() - weekday) % 7)


def _market_holidays(year: int) -> set[date]:
    """A practical US equity holiday set for the stub calendar."""
    holidays: set[date] = set()

    def observed(target: date) -> date:
        if target.weekday() == 5:
            return target - timedelta(days=1)
        if target.weekday() == 6:
            return target + timedelta(days=1)
        return target

    holidays.add(observed(date(year, 1, 1)))
    holidays.add(_nth_weekday(year, 1, 0, 3))
    holidays.add(_nth_weekday(year, 2, 0, 3))
    holidays.add(easter(year) - timedelta(days=2))
    holidays.add(_last_weekday(year, 5, 0))
    if year >= 2022:
        holidays.add(observed(date(year, 6, 19)))
    holidays.add(observed(date(year, 7, 4)))
    holidays.add(_nth_weekday(year, 9, 0, 1))
    holidays.add(_nth_weekday(year, 11, 3, 4))
    holidays.add(observed(date(year, 12, 25)))
    return holidays


def _stub_trading_days(start: date, end: date) -> list[date]:
    business_days = pd.bdate_range(start, end)
    holidays = {
        holiday
        for year in range(start.year, end.year + 1)
        for holiday in _market_holidays(year)
    }
    return [
        day.date()
        for day in business_days
        if day.date() not in holidays
    ]


class StubStore:
    """A seeded, offline, point-in-time historical store."""

    def __init__(
        self, cfg: dict[str, Any], theme_config: dict[str, Any]
    ) -> None:
        self.cfg = cfg
        self.theme_config = theme_config
        self.sub_exposures = list(
            theme_config.get("sub_exposures") or sorted(load_sub_exposure_etf_map())
        )
        self._trading_days = _stub_trading_days(date(2019, 1, 1), date(2026, 12, 31))
        self._etf_map = load_sub_exposure_etf_map()
        self._reference = self._load_reference()
        self._all_tickers = sorted(
            set(self._reference) | self._collect_seed_tickers()
        )
        self._holdings_by_etf = self._load_holdings_by_etf()
        self._price_frames = self._build_price_frames()
        self._benchmarks = {
            name: self._build_benchmark(name)
            for name in ("QQQ", "SPY")
        }

    def _load_reference(self) -> dict[str, dict[str, Any]]:
        path = CONFIG_DIR / "reference_universe_seed.csv"
        if not path.is_file():
            return {}
        frame = pd.read_csv(path, dtype={"ticker": str}).fillna("")
        return {
            str(row["ticker"]).upper(): {
                "ticker": str(row["ticker"]).upper(),
                "company_name": row.get("company_name") or f"{row['ticker']} Inc.",
                "gics_subindustry": row.get("gics_subindustry") or "Unclassified",
                "market_cap": float(row.get("market_cap") or 10_000_000_000),
                "avg_dollar_volume": float(
                    row.get("avg_dollar_volume") or 100_000_000
                ),
            }
            for _, row in frame.iterrows()
        }

    def _collect_seed_tickers(self) -> set[str]:
        tickers: set[str] = set()
        for etfs in self._etf_map.values():
            for etf in etfs:
                holdings = fetch_etf_holdings(etf)
                if not holdings.empty:
                    tickers.update(str(ticker).upper() for ticker in holdings["ticker"])
        return tickers

    def _load_holdings_by_etf(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for etf in {etf for etfs in self._etf_map.values() for etf in etfs}:
            holdings = fetch_etf_holdings(etf)
            result[etf] = [
                str(ticker).upper() for ticker in holdings["ticker"]
            ] if not holdings.empty else []
        return result

    def _reference_for(self, ticker: str, as_of: date) -> dict[str, Any]:
        row = self._reference.get(ticker)
        if row is not None:
            return {
                **row,
                "market_cap": self._market_cap(ticker, as_of),
                "avg_dollar_volume": self._dollar_volume(ticker, as_of),
            }
        return {
            "ticker": ticker,
            "company_name": f"{ticker} Inc.",
            "gics_subindustry": "Unclassified",
            "market_cap": self._market_cap(ticker, as_of),
            "avg_dollar_volume": self._dollar_volume(ticker, as_of),
        }

    def _market_cap(self, ticker: str, as_of: date) -> float:
        seed = random.Random(f"cap:{ticker}:{as_of.year}:{_quarter(as_of)}")
        return seed.uniform(5e9, 1.2e12)

    def _dollar_volume(self, ticker: str, as_of: date) -> float:
        seed = random.Random(f"adv:{ticker}:{as_of.year}:{_quarter(as_of)}")
        return seed.uniform(5e6, 2e10)

    def _build_price_frames(self) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for ticker in self._all_tickers:
            rng = random.Random(f"price:{ticker}")
            drift = rng.uniform(-0.0004, 0.0011)
            amplitude = rng.uniform(0.004, 0.02)
            phase = rng.uniform(0.0, 2 * math.pi)
            period = rng.uniform(180.0, 700.0)
            noise = rng.uniform(0.004, 0.018)
            volume_base = rng.uniform(5e6, 8e7)
            records: list[dict[str, Any]] = []
            close = 100.0
            for index, day in enumerate(self._trading_days):
                day_rng = random.Random(f"day:{ticker}:{day.isoformat()}")
                ret = (
                    drift
                    + amplitude * math.sin(phase + index / period)
                    + day_rng.gauss(0.0, noise)
                )
                close *= math.exp(ret)
                position = day_rng.random()
                spread = close * 0.025
                low = close - spread * position
                high = low + spread
                volume = volume_base * day_rng.uniform(0.5, 1.8)
                records.append(
                    {
                        "date": day,
                        "close": close,
                        "high": high,
                        "low": low,
                        "volume": volume,
                    }
                )
            frames[ticker] = pd.DataFrame(records).set_index("date")
        return frames

    def _build_benchmark(self, name: str) -> dict[date, float]:
        rng = random.Random(f"benchmark:{name}")
        drift = rng.uniform(0.0002, 0.0008)
        amplitude = rng.uniform(0.003, 0.011)
        phase = rng.uniform(0.0, 2 * math.pi)
        period = rng.uniform(250.0, 900.0)
        noise = rng.uniform(0.003, 0.011)
        close = 100.0
        prices: dict[date, float] = {}
        for index, day in enumerate(self._trading_days):
            day_rng = random.Random(f"bench-day:{name}:{day.isoformat()}")
            ret = (
                drift
                + amplitude * math.sin(phase + index / period)
                + day_rng.gauss(0.0, noise)
            )
            close *= math.exp(ret)
            prices[day] = close
        return prices

    def trading_days(self) -> list[date]:
        return list(self._trading_days)

    async def prefetch(
        self,
        theme_config: dict[str, Any],
        schedule: list[Any],
        progress: Callable[[str, int, int], None],
    ) -> None:
        # Data is deterministic and in memory; no network work is needed.
        progress("fetching_data", 1, 1)
        return None

    def make_price_fetcher(self, as_of: date) -> Callable[..., PriceHistory]:
        def fetch(ticker: str, lookback_days: int = 504) -> PriceHistory:
            frame = self._price_frames.get(ticker.upper())
            if frame is None:
                raise RuntimeError(f"no stub price history for {ticker}")
            sliced = frame.loc[:as_of].tail(lookback_days)
            return PriceHistory(
                ticker=ticker,
                close=sliced["close"].astype(float),
                volume=sliced["volume"].astype(float),
                source="stub",
            )

        return fetch

    def make_fundamentals_fetcher(self, as_of: date) -> Callable[..., Fundamentals]:
        def fetch(ticker: str) -> Fundamentals:
            ticker = ticker.upper()
            frame = self._price_frames.get(ticker)
            if frame is None:
                raise RuntimeError(f"no stub fundamentals for {ticker}")
            close_at_as_of = float(
                frame.loc[:as_of, "close"].iloc[-1]
            )
            seed = random.Random(f"fund:{ticker}:{as_of.year}:{_quarter(as_of)}")
            market_cap = seed.uniform(5e9, 1.2e12)
            pe = seed.uniform(12.0, 48.0)
            eps = close_at_as_of / pe
            price_sales = seed.uniform(1.0, 12.0)
            revenue = market_cap / price_sales
            ebitda = revenue * seed.uniform(0.08, 0.35)
            net_income = revenue * seed.uniform(0.04, 0.25)
            equity = market_cap * seed.uniform(0.2, 0.8)
            return Fundamentals(
                ticker=ticker,
                price=close_at_as_of,
                diluted_eps_ttm=eps,
                market_cap=market_cap,
                total_debt=market_cap * seed.uniform(0.1, 0.6),
                cash=market_cap * seed.uniform(0.02, 0.15),
                ebitda_ttm=ebitda,
                revenue_ttm=revenue,
                revenue_growth_yoy=seed.uniform(-0.05, 0.35),
                eps_growth_yoy=seed.uniform(-0.10, 0.40),
                net_income_ttm=net_income,
                shareholders_equity=equity,
                gross_profit_ttm=revenue * seed.uniform(0.25, 0.75),
                free_cash_flow_ttm=net_income * seed.uniform(0.5, 1.5),
                source="stub",
            )

        return fetch

    def _etf_launch_year(self, etf: str) -> int:
        seed = random.Random(f"launch:{etf}")
        return seed.randint(2019, 2023)

    def _is_member(self, ticker: str, etf: str, as_of: date) -> bool:
        if self._etf_launch_year(etf) > as_of.year:
            return False
        seed = random.Random(
            f"membership:{ticker}:{etf}:{as_of.year}:{_quarter(as_of)}"
        )
        return seed.random() > 0.18

    def _membership(self, as_of: date) -> dict[str, set[str]]:
        membership: dict[str, set[str]] = {}
        for sub_exposure in self.sub_exposures:
            for etf in self._etf_map.get(sub_exposure, []):
                for ticker in self._holdings_by_etf.get(etf, []):
                    if self._is_member(ticker, etf, as_of):
                        membership.setdefault(ticker, set()).add(etf)
        return membership

    def etf_universe(
        self, sub_exposures: list[str], as_of: date
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for sub_exposure in sub_exposures:
            hits: dict[str, dict[str, Any]] = {}
            for etf in self._etf_map.get(sub_exposure, []):
                for ticker in self._holdings_by_etf.get(etf, []):
                    if not self._is_member(ticker, etf, as_of):
                        continue
                    if ticker not in hits:
                        hits[ticker] = {
                            **self._reference_for(ticker, as_of),
                            "sub_exposure": sub_exposure,
                        }
            result[sub_exposure] = list(hits.values())
        return result

    def etf_membership(self, as_of: date) -> dict[str, set[str]]:
        return self._membership(as_of)

    def ohlcv(self, tickers: list[str], as_of: date) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            frame = self._price_frames.get(ticker.upper())
            if frame is not None:
                result[ticker] = frame.loc[:as_of][
                    ["close", "high", "low", "volume"]
                ]
        return result

    def reference_rows(self, as_of: date) -> list[dict[str, Any]]:
        return [
            {
                **self._reference_for(ticker, as_of),
                "source": "index:russell3000",
            }
            for ticker in self._all_tickers
        ]

    def total_return_prices(self) -> dict[str, dict[date, float]]:
        def _as_date(day: Any) -> date:
            return day if isinstance(day, date) else day.date()

        return {
            ticker: {
                _as_date(day): float(row["close"])
                for day, row in frame.iterrows()
            }
            for ticker, frame in self._price_frames.items()
        }

    def benchmark_prices(self, name: str) -> dict[date, float]:
        return dict(self._benchmarks.get(name, {}))

    def provenance(self) -> dict[str, Any]:
        return {
            "data_source": "stub",
            "data_version": "stub-1",
            "flags": ["synthetic_data"],
        }
