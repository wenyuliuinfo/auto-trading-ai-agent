"""Optional Validator node (bull/bear check, top ~12 names).

No canonical skill exists for this agent yet (ARCHITECTURE.md §11 flags
it as future work), so the node currently passes the ranked list through
unchanged while honoring ``validator_enabled``.
"""

from __future__ import annotations

from typing import Any

from app.logging_conf import get_logger

logger = get_logger(__name__)


async def validator_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pass through the ranked list; the validator is optional per theme."""
    enabled = bool(state.get("theme_config", {}).get("validator_enabled", True))
    if enabled:
        logger.info("validator_pass_through", run_id=state["run_id"])
    return {"ranked_list": state["ranked_list"]}
