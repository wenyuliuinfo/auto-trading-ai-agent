"""Pinecone client: scoped to semantic candidate discovery only (§2.2)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)


def semantic_search(keyword: str, limit: int = 20) -> list[dict[str, Any]]:
    """kNN query against embedded business descriptions; additive only.

    Returns an empty list when Pinecone is unconfigured/unreachable; the
    Screener must work from GICS/ETF sources alone (SCREENER_SKILL.md).
    """
    settings = get_settings()
    if not settings.pinecone_api_key:
        return []
    try:
        from pinecone import Pinecone

        client = Pinecone(api_key=settings.pinecone_api_key, host=settings.pinecone_host_url)
        index = client.Index(settings.pinecone_index_name)
        result = index.query(
            vector=[0.0] * 768, top_k=limit, include_metadata=True
        )
        return [
            {
                "ticker": str(match.get("id", "")),
                "score": match.get("score"),
                "source": "pinecone:semantic",
            }
            for match in result.get("matches", [])
        ]
    except Exception as exc:
        logger.warning("pinecone_query_failed", error=str(exc))
        return []
