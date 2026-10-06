"""Historical data-store contract used by the Backtest agent.

The backtest engine itself never imports this module. ``agents/backtest.py``
chooses a concrete store, and every accessor takes an explicit ``as_of`` date.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

import pandas as pd


class HistoricalStore(Protocol):
    """Point-in-time data accessors required by the backtest loop."""

    def trading_days(self) -> list[date]: ...

    async def prefetch(
        self,
        theme_config: dict[str, Any],
        schedule: list[Any],
        progress: Callable[[str, int, int], None],
    ) -> None: ...

    def make_price_fetcher(self, as_of: date) -> Callable[..., Any]: ...

    def make_fundamentals_fetcher(self, as_of: date) -> Callable[..., Any]: ...

    def etf_universe(
        self, sub_exposures: list[str], as_of: date
    ) -> dict[str, list[dict[str, Any]]]: ...

    def etf_membership(self, as_of: date) -> dict[str, set[str]]: ...

    def ohlcv(self, tickers: list[str], as_of: date) -> dict[str, pd.DataFrame]: ...

    def reference_rows(self, as_of: date) -> list[dict[str, Any]]: ...

    def total_return_prices(self) -> dict[str, dict[date, float]]: ...

    def benchmark_prices(self, name: str) -> dict[date, float]: ...

    def provenance(self) -> dict[str, Any]: ...


def make_store(
    cfg: dict[str, Any], theme_config: dict[str, Any]
) -> HistoricalStore:
    """Return a concrete store based on the backtest config snapshot."""
    data_cfg = cfg.get("data", {})
    provider = str(data_cfg.get("provider", "fmp"))
    if provider == "stub" or cfg.get("_force_stub_store"):
        from app.integrations.historical_data_stub import StubStore

        return StubStore(cfg=cfg, theme_config=theme_config)
    from app.config import get_settings

    if get_settings().stub_agents:
        from app.integrations.historical_data_stub import StubStore

        return StubStore(cfg=cfg, theme_config=theme_config)
    from app.integrations.historical_data_fmp import FmpStore

    return FmpStore(cfg=cfg, theme_config=theme_config)
