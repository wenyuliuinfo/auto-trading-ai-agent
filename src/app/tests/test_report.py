"""Report agent tests: risk clustering, disclaimer, context assembly."""

from __future__ import annotations

import pytest

from app.agents.report import (
    REPORT_SYSTEM_PROMPT,
    _reformat_holdings_table,
    apply_disclaimer,
    assemble_report_context,
    group_shared_risks,
)
from app.data.queries import (
    create_run,
    save_analyst_report,
    save_basket,
    save_rankings,
)


def _report(ticker: str, risks: list[str]) -> dict[str, object]:
    return {
        "ticker": ticker,
        "thematic_relevance_score": 3.0,
        "thematic_relevance_rationale": "theme fit",
        "revenue_pct_theme_estimate": 0.1,
        "catalysts": [],
        "risks": risks,
        "sentiment_label": "neutral",
        "sentiment_evidence": [],
        "sources": ["stub_gdelt"],
    }


def test_group_shared_risks_threshold() -> None:
    reports = {
        "A": _report("A", ["Regulatory risk."]),
        "B": _report("B", ["regulatory risk"]),
        "C": _report("C", ["Balance sheet leverage"]),
    }
    clusters = group_shared_risks(reports, ["A", "B", "C"])
    assert len(clusters) == 1
    assert set(clusters[0]["tickers"]) == {"A", "B"}


def test_apply_disclaimer_unconditional() -> None:
    output = apply_disclaimer("Body text. This is not investment advice.")
    assert "for research purposes only" in output
    assert "constitute investment advice" in output
    assert output.count("not investment advice") >= 1


def test_reformat_holdings_table_converts_to_paragraphs() -> None:
    table = "\n".join(
        [
            "| Ticker | Company | Why Included | Latest News Headline | 1-Year Return |",
            "|--------|---------|--------------|----------------------|---------------|",
            "| **PWR** | Quanta Services | Ranked #1 with strong sentiment. | Headline here. | +73.5% |",
            "| **GEV** | GE Vernova | Ranked #2 on momentum. | Another headline. | +53.3% |",
        ]
    )

    output = _reformat_holdings_table(table)

    assert "| Ticker |" not in output
    assert "**PWR - Quanta Services**" in output
    assert "- Why included: Ranked #1 with strong sentiment." in output
    assert "- Latest news: Headline here." in output
    assert "- 1-Year Return: +73.5%" in output
    assert "**GEV - GE Vernova**" in output


def test_report_prompt_requires_paragraph_format() -> None:
    assert "never a table" in REPORT_SYSTEM_PROMPT
    assert "Ticker - Company Name" in REPORT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_assemble_report_context_surfaces_caveats(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000021")
    run_id = run["run_id"]
    await save_analyst_report(run_id, _report("AAA", ["Regulatory risk"]))
    await save_rankings(
        run_id,
        [
            {
                "ticker": "AAA",
                "composite_score": 2.0,
                "rank": 1,
                "factor_contributions": {"thematic_z": 1.0},
                "caveats": ["top-ranked name is small-cap"],
            }
        ],
    )
    await save_basket(
        run_id, [{"ticker": "AAA", "weight": 0.1, "rank": 1, "sub_exposure": "grid"}]
    )
    context = await assemble_report_context(run_id, "grid modernization", [])
    assert context["basket"][0]["caveats"] == ["top-ranked name is small-cap"]
