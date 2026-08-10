"""Langfuse integration: write-side trace helper + read-side query client.

The read path (``get_trace_tool_results``) is used only by
``app/evaluation/groundedness.py`` after a run completes; it is a
different API surface from the write-side callback (CONVENTIONS.md §2.1).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)


def start_run_trace(run_id: str) -> Any:
    """Create a Langfuse trace named by run_id; returns a no-op when unconfigured."""
    settings = get_settings()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return client.trace(name=run_id, tags=[run_id, "pipeline"])
    except Exception as exc:
        logger.warning("langfuse_trace_start_failed", error=str(exc))
        return None


async def get_trace_tool_results(run_id: str) -> set[str]:
    """Collect tool-result strings recorded for a run's trace.

    Returns an empty set when Langfuse is unconfigured or unreachable;
    the groundedness checker treats that as "no evidence available" and
    flags sources for human review (advisory only, never blocking).
    """
    settings = get_settings()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return set()
    try:
        async with httpx.AsyncClient(
            base_url=settings.langfuse_host,
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            timeout=30.0,
        ) as client:
            traces_response = await client.get(
                "/api/public/traces", params={"name": run_id}
            )
            traces_response.raise_for_status()
            traces = traces_response.json().get("data", [])
            results: set[str] = set()
            for trace in traces:
                trace_id = trace.get("id")
                if not trace_id:
                    continue
                detail = await client.get(f"/api/public/traces/{trace_id}")
                detail.raise_for_status()
                observations = detail.json().get("observations", [])
                for observation in observations:
                    output = observation.get("output")
                    if isinstance(output, str) and output:
                        results.add(output)
            return results
    except Exception as exc:
        logger.warning("langfuse_read_failed", run_id=run_id, error=str(exc))
        return set()
