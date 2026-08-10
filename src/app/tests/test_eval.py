"""Groundedness checker tests against fixture data (CONVENTIONS.md §5)."""

from __future__ import annotations

import pytest

from app.data.queries import (
    create_run,
    save_analyst_report,
    save_basket,
    save_rankings,
    save_report,
)
from app.evaluation.groundedness import (
    check_analyst_groundedness,
    check_report_groundedness,
)


@pytest.mark.asyncio
async def test_check_report_groundedness_flags_unmatched_number(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000031")
    run_id = run["run_id"]
    await save_analyst_report(
        run_id,
        {
            "ticker": "AAA",
            "thematic_relevance_score": 4.0,
            "thematic_relevance_rationale": "x",
            "revenue_pct_theme_estimate": 0.15,
            "catalysts": [],
            "risks": [],
            "sentiment_label": "bullish",
            "sentiment_evidence": [],
            "sources": [],
        },
    )
    await save_rankings(
        run_id,
        [
            {
                "ticker": "AAA",
                "composite_score": 1.25,
                "rank": 1,
                "factor_contributions": {},
                "caveats": [],
            }
        ],
    )
    await save_basket(
        run_id, [{"ticker": "AAA", "weight": 0.5, "rank": 1, "sub_exposure": "grid"}]
    )
    await save_report(run_id, "Composite score was 9.99 and weight was 50%.")
    flags = await check_report_groundedness(run_id)
    assert any(flag["number"] == "9.99" for flag in flags)
    assert not any(flag["number"] == "50" for flag in flags)


@pytest.mark.asyncio
async def test_check_analyst_groundedness_uses_trace_sources(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000032")
    run_id = run["run_id"]
    await save_analyst_report(
        run_id,
        {
            "ticker": "AAA",
            "thematic_relevance_score": 3.0,
            "thematic_relevance_rationale": "x",
            "revenue_pct_theme_estimate": None,
            "catalysts": [],
            "risks": [],
            "sentiment_label": "neutral",
            "sentiment_evidence": [],
            "sources": ["gdelt:https://example.com"],
        },
    )
    async def fake_trace(run_id: str) -> set[str]:
        return {"gdelt:https://example.com"}

    monkeypatch.setattr(
        "app.evaluation.groundedness.get_trace_tool_results", fake_trace
    )
    assert await check_analyst_groundedness(run_id) == []

    async def fake_trace_empty(run_id: str) -> set[str]:
        return set()

    monkeypatch.setattr(
        "app.evaluation.groundedness.get_trace_tool_results", fake_trace_empty
    )
    flags = await check_analyst_groundedness(run_id)
    assert flags and flags[0]["source"] == "gdelt:https://example.com"
