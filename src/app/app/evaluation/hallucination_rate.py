"""Hallucination-rate aggregation over the groundedness checkers.

This module only observes already-persisted Runs; it is never called from
api/ or agents/ and never blocks a Run's completion (ARCHITECTURE.md §8.B).
"""

from __future__ import annotations

from typing import Any

from app.data.queries import get_analyst_reports, get_report
from app.evaluation.groundedness import (
    NUMBER_PATTERN,
    check_analyst_groundedness,
    check_report_groundedness,
)

HALLUCINATION_RATE_LIMIT = 0.03


def analyst_hallucination_rate(
    flags: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> dict[str, Any]:
    """Flagged Analyst sources over total Analyst sources for one Run."""
    total = sum(len(report.get("sources", [])) for report in reports)
    flagged = len(flags)
    rate = flagged / total if total else None
    return {
        "flagged_sources": flagged,
        "total_sources": total,
        "rate": rate,
        "exceeds_limit": rate is not None and rate > HALLUCINATION_RATE_LIMIT,
    }


def report_hallucination_rate(
    flags: list[dict[str, Any]], report_md: str | None
) -> dict[str, Any]:
    """Flagged report numbers over numbers extracted from the report."""
    total = len(NUMBER_PATTERN.findall(report_md)) if report_md is not None else 0
    flagged = len(flags)
    rate = flagged / total if total else None
    return {
        "flagged_numbers": flagged,
        "total_numbers": total,
        "rate": rate,
        "exceeds_limit": rate is not None and rate > HALLUCINATION_RATE_LIMIT,
    }


async def check_hallucination_rate(run_id: str) -> dict[str, Any]:
    """Return groundedness-based hallucination rates for one Run."""
    analyst_flags = await check_analyst_groundedness(run_id)
    reports = await get_analyst_reports(run_id)
    report_flags = await check_report_groundedness(run_id)
    report_md = await get_report(run_id)
    analyst = analyst_hallucination_rate(analyst_flags, reports)
    report = report_hallucination_rate(report_flags, report_md)
    return {
        "run_id": run_id,
        "limit": HALLUCINATION_RATE_LIMIT,
        "analyst": analyst,
        "report": report,
        "exceeds_limit": analyst["exceeds_limit"] or report["exceeds_limit"],
    }
