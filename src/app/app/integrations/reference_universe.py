"""Cached reference universe backing ``search_sector`` (SCREENER_SKILL.md)."""

from __future__ import annotations

import time
from typing import Any, cast

import httpx
import pandas as pd

from app.config import CONFIG_DIR, get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE: dict[str, tuple[pd.DataFrame, float]] = {}

SEED_PATH = CONFIG_DIR / "reference_universe_seed.csv"


def _load_seed() -> pd.DataFrame:
    frame = pd.read_csv(SEED_PATH, dtype={"ticker": str})
    return frame.fillna("")


def _fetch_live(url: str) -> pd.DataFrame | None:
    try:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        return pd.read_csv(pd.io.common.StringIO(response.text), dtype={"ticker": str})
    except Exception as exc:
        logger.warning("reference_universe_fetch_failed", error=str(exc))
        return None


def fetch_and_parse_index_constituents() -> pd.DataFrame:
    """Live source when configured, bundled seed otherwise."""
    settings = get_settings()
    if settings.reference_universe_url:
        live = _fetch_live(settings.reference_universe_url)
        if live is not None and not live.empty:
            return live.fillna("")
    return _load_seed()


def get_reference_universe() -> pd.DataFrame:
    """Return the cached universe, refetching only when stale (Hard Rule 2)."""
    now = time.time()
    cached = _CACHE.get("universe")
    if cached is not None and now - cached[1] < CACHE_TTL_SECONDS:
        return cached[0]
    frame = fetch_and_parse_index_constituents()
    _CACHE["universe"] = (frame, now)
    return frame


def search_sector(keyword: str) -> list[dict[str, object]]:
    """Tickers whose GICS sub-industry matches ``keyword`` (never invented)."""
    universe = get_reference_universe()
    matches = universe[
        universe["gics_subindustry"].str.contains(keyword, case=False, na=False)
    ]
    records = cast(list[dict[str, Any]], matches.to_dict("records"))
    for record in records:
        record["source"] = "index:russell3000"
    return [dict(record) for record in records]
