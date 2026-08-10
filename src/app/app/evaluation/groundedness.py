"""Groundedness checkers (ARCHITECTURE.md §8.B).

These read completed Runs only; they are never called from api/ or
agents/ and never block a Run's completion.
"""

from __future__ import annotations

import re
from typing import Any

from app.data.queries import (
    get_analyst_reports,
    get_basket_rows,
    get_rankings,
    get_report,
)
from app.integrations.langfuse_client import get_trace_tool_results

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?%?")


async def check_analyst_groundedness(run_id: str) -> list[dict[str, Any]]:
    """Flag Analyst sources that have no matching tool result in the trace."""
    reports = await get_analyst_reports(run_id)
    known_sources = await get_trace_tool_results(run_id)
    flags: list[dict[str, Any]] = []
    for report in reports:
        for source in report.get("sources", []):
            if not known_sources or str(source) not in known_sources:
                flags.append(
                    {
                        "ticker": report["ticker"],
                        "source": source,
                        "reason": "no matching tool result in Langfuse trace",
                    }
                )
    return flags


def _allowed_numbers(run_data: dict[str, Any]) -> set[float]:
    allowed: set[float] = set()
    for report in run_data["analyst_reports"]:
        score = report.get("thematic_relevance_score")
        if score is not None:
            allowed.add(float(score))
        revenue = report.get("revenue_pct_theme_estimate")
        if revenue is not None:
            allowed.add(float(revenue))
            allowed.add(float(revenue) * 100)
    for ranking in run_data["rankings"]:
        composite = ranking.get("composite_score")
        if composite is not None:
            allowed.add(float(composite))
        for contribution in (ranking.get("factor_contributions") or {}).values():
            if contribution is not None:
                allowed.add(float(contribution))
    for basket_row in run_data["basket"]:
        weight = basket_row.get("weight")
        if weight is not None:
            allowed.add(float(weight))
            allowed.add(float(weight) * 100)
    return allowed


async def check_report_groundedness(run_id: str) -> list[dict[str, Any]]:
    """Flag report numbers that don't match persisted upstream values."""
    report_md = await get_report(run_id)
    if report_md is None:
        return [{"run_id": run_id, "reason": "no report persisted for run"}]
    run_data = {
        "analyst_reports": await get_analyst_reports(run_id),
        "rankings": await get_rankings(run_id),
        "basket": await get_basket_rows(run_id),
    }
    allowed = _allowed_numbers(run_data)
    flags: list[dict[str, Any]] = []
    for match in NUMBER_PATTERN.finditer(report_md):
        token = match.group(0)
        is_percent = token.endswith("%")
        value = float(token.rstrip("%"))
        normalized = value / 100.0 if is_percent else value
        if not allowed:
            flags.append({"number": token, "reason": "no upstream numbers available"})
            continue
        if not any(
            abs(normalized - allowed_value)
            <= max(0.005, abs(allowed_value) * 0.02)
            for allowed_value in allowed
        ):
            flags.append(
                {
                    "number": token,
                    "reason": "number not matched within rounding tolerance",
                }
            )
    return flags
