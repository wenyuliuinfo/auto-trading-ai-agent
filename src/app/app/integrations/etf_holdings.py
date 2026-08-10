"""ETF holdings client backing ``search_holdings`` (SCREENER_SKILL.md)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import yaml

from app.config import CONFIG_DIR, load_sub_exposure_etf_map

SEED_PATH = CONFIG_DIR / "etf_holdings_seed.yaml"


def _load_seed() -> dict[str, list[str]]:
    with SEED_PATH.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return {
        key: [str(ticker) for ticker in value]
        for key, value in raw.items()
        if isinstance(value, list)
    }


def _seed_holdings(etf_ticker: str) -> pd.DataFrame:
    seed = _load_seed()
    rows = seed.get(etf_ticker) or seed.get("_fallback") or []
    return pd.DataFrame([{"ticker": ticker} for ticker in rows])


def fetch_etf_holdings(etf_ticker: str) -> pd.DataFrame:
    """Return normalized (ticker, weight) holdings from the seed YAML.

    Live issuer CSV downloads are intentionally not attempted; the seed
    file is the single source of ETF constituents.
    """
    return _seed_holdings(etf_ticker)


def search_holdings(sub_exposure: str) -> list[dict[str, Any]]:
    """Constituent tickers of ETFs mapped to a sub-exposure (Hard Rule 3)."""
    etfs = load_sub_exposure_etf_map().get(sub_exposure, [])
    if not etfs:
        return []
    results: list[dict[str, Any]] = []
    for etf in etfs:
        holdings = fetch_etf_holdings(etf)
        for record in holdings.to_dict("records"):
            results.append(
                {
                    "ticker": record["ticker"],
                    "weight": record.get("weight"),
                    "source": f"etf_holdings:{etf}",
                }
            )
    return results
