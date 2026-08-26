"""Evaluation checker tests against fixture data (CONVENTIONS.md §5)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.data.queries import (
    create_run,
    create_theme,
    save_analyst_report,
    save_basket,
    save_candidates,
    save_rankings,
    save_report,
)
from app.evaluation import golden_set
from app.evaluation.groundedness import (
    check_analyst_groundedness,
    check_report_groundedness,
)
from app.evaluation.golden_set import check_candidate_coverage
from app.evaluation.hallucination_rate import (
    HALLUCINATION_RATE_LIMIT,
    analyst_hallucination_rate,
    check_hallucination_rate,
    report_hallucination_rate,
)

GOLDEN_HOLDINGS = {
    "SMH": ["NVDA", "AVGO", "AMD", "QCOM", "MU"],
    "SOXX": ["NVDA", "QCOM", "INTC", "TXN", "AMAT"],
}


def _fake_sub_exposure_map() -> dict[str, list[str]]:
    return {"ai_chips": ["SMH", "SOXX"]}


def _fake_fetch_etf_holdings(etf_ticker: str) -> pd.DataFrame:
    return pd.DataFrame(
        [{"ticker": ticker} for ticker in GOLDEN_HOLDINGS[etf_ticker]]
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


@pytest.mark.asyncio
async def test_check_candidate_coverage_passes_with_most_holdings(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    theme = await create_theme("AI chips", "test", {"sub_exposures": ["ai_chips"]})
    run = await create_run(theme["theme_id"])
    await save_candidates(
        run["run_id"],
        [
            {"ticker": "NVDA"},
            {"ticker": "AVGO"},
            {"ticker": "AMD"},
            {"ticker": "QCOM"},
            {"ticker": "MU"},
            {"ticker": "INTC"},
            {"ticker": "TXN"},
        ],
    )
    monkeypatch.setattr(golden_set, "load_sub_exposure_etf_map", _fake_sub_exposure_map)
    monkeypatch.setattr(golden_set, "fetch_etf_holdings", _fake_fetch_etf_holdings)

    assert await check_candidate_coverage(run["run_id"]) == []


@pytest.mark.asyncio
async def test_check_candidate_coverage_flags_systematic_gap(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    theme = await create_theme("AI chips", "test", {"sub_exposures": ["ai_chips"]})
    run = await create_run(theme["theme_id"])
    await save_candidates(run["run_id"], [{"ticker": "NVDA"}])
    monkeypatch.setattr(golden_set, "load_sub_exposure_etf_map", _fake_sub_exposure_map)
    monkeypatch.setattr(golden_set, "fetch_etf_holdings", _fake_fetch_etf_holdings)

    flags = await check_candidate_coverage(run["run_id"])

    assert len(flags) == 1
    assert flags[0]["sub_exposure"] == "ai_chips"
    assert flags[0]["coverage_ratio"] == 0.125
    assert flags[0]["missing_tickers"] == ["AVGO", "AMD", "QCOM", "MU", "INTC", "TXN", "AMAT"]
    assert "below" in flags[0]["reason"]


@pytest.mark.asyncio
async def test_check_candidate_coverage_flags_missing_theme(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000033")
    monkeypatch.setattr(golden_set, "load_sub_exposure_etf_map", _fake_sub_exposure_map)

    flags = await check_candidate_coverage(run["run_id"])

    assert flags == [{"run_id": run["run_id"], "reason": "no theme persisted for run"}]


def test_expected_tickers_caps_at_top_15_per_etf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        golden_set,
        "load_sub_exposure_etf_map",
        lambda: {"mapped": ["ETF"]},
    )

    def fake_fetch(etf_ticker: str) -> pd.DataFrame:
        return pd.DataFrame([{"ticker": f"T{i:02d}"} for i in range(20)])

    monkeypatch.setattr(golden_set, "fetch_etf_holdings", fake_fetch)

    assert golden_set._expected_tickers("mapped") == [f"T{i:02d}" for i in range(15)]


def test_analyst_hallucination_rate_computes_flagged_sources() -> None:
    reports = [
        {"ticker": "AAA", "sources": ["gdelt:https://a", "gdelt:https://b"]},
        {"ticker": "BBB", "sources": ["gdelt:https://c"]},
    ]

    result = analyst_hallucination_rate(
        [{"ticker": "AAA", "source": "gdelt:https://a"}], reports
    )

    assert result == {
        "flagged_sources": 1,
        "total_sources": 3,
        "rate": 1 / 3,
        "exceeds_limit": True,
    }


def test_analyst_hallucination_rate_at_three_percent_does_not_exceed() -> None:
    reports = [{"ticker": "AAA", "sources": [f"s{i}" for i in range(100)]}]
    flags = [{"ticker": "AAA", "source": f"s{i}"} for i in range(3)]

    result = analyst_hallucination_rate(flags, reports)

    assert result["rate"] == 0.03
    assert result["exceeds_limit"] is False


def test_analyst_hallucination_rate_returns_none_without_sources() -> None:
    result = analyst_hallucination_rate([], [{"ticker": "AAA", "sources": []}])

    assert result["rate"] is None
    assert result["exceeds_limit"] is False


def test_report_hallucination_rate_counts_numbers_and_flags() -> None:
    result = report_hallucination_rate(
        [{"number": "9.99"}], "Composite score was 9.99 and weight was 50%."
    )

    assert result == {
        "flagged_numbers": 1,
        "total_numbers": 2,
        "rate": 0.5,
        "exceeds_limit": True,
    }


def test_report_hallucination_rate_returns_none_without_report() -> None:
    result = report_hallucination_rate([], None)

    assert result["rate"] is None
    assert result["exceeds_limit"] is False


@pytest.mark.asyncio
async def test_check_hallucination_rate_aggregates_both_checkers(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000034")
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

    async def fake_trace(run_id: str) -> set[str]:
        return set()

    monkeypatch.setattr(
        "app.evaluation.groundedness.get_trace_tool_results", fake_trace
    )

    result = await check_hallucination_rate(run_id)

    assert result["run_id"] == run_id
    assert result["limit"] == HALLUCINATION_RATE_LIMIT
    assert result["analyst"] == {
        "flagged_sources": 1,
        "total_sources": 1,
        "rate": 1.0,
        "exceeds_limit": True,
    }
    assert result["report"]["flagged_numbers"] == 1
    assert result["report"]["total_numbers"] == 2
    assert result["report"]["rate"] == 0.5
    assert result["exceeds_limit"] is True
