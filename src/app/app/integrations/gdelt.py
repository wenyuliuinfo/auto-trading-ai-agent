"""GDELT client: free, high-volume news source (primary news feed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from app.logging_conf import get_logger

logger = get_logger(__name__)

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_gdelt(ticker: str, lookback_days: int = 90) -> list[dict[str, Any]]:
    """Fetch raw GDELT article records mentioning ``ticker``."""
    start = datetime.now(UTC) - timedelta(days=lookback_days)
    params = {
        "query": f'"{ticker}"',
        "mode": "artlist",
        "format": "json",
        "maxrecords": "25",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
    }
    try:
        response = httpx.get(GDELT_API_URL, params=params, timeout=30.0)
        response.raise_for_status()
        data = cast(dict[str, Any], response.json())
        return cast(list[dict[str, Any]], data.get("articles", []))
    except Exception as exc:
        logger.warning("gdelt_fetch_failed", ticker=ticker, error=str(exc))
        return []
