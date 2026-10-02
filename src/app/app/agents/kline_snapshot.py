"""Deterministic K-line snapshot node between Trader and Report."""

from __future__ import annotations

from typing import Any

from app.data.queries import save_klines
from app.integrations.kline import fetch_klines, snapshot_to_dict
from app.logging_conf import get_logger

logger = get_logger(__name__)


async def kline_snapshot_node(state: dict[str, Any]) -> dict[str, Any]:
    """Fetch and persist K-lines for basket holdings; never fail the run."""
    run_id = str(state["run_id"])
    basket = state.get("basket", [])
    tickers = [str(holding["ticker"]) for holding in basket]
    if not tickers:
        return {}
    try:
        snapshots = await fetch_klines(tickers)
        await save_klines(run_id, [snapshot_to_dict(s) for s in snapshots.values()])
    except Exception as exc:
        logger.warning("kline_snapshot_failed", run_id=run_id, error=str(exc))
    return {}
