"""Analyst node tests: cache-before-fetch, error stubs, schema validation."""

from __future__ import annotations

import pytest

from app.agents.analyst import (
    _normalize_sentiment_label,
    analyst_node,
    estimate_revenue_pct_theme,
)
from app.data.queries import (
    copy_recent_analyst_report,
    create_run,
    get_analyst_reports,
    get_recent_analyst_report,
    save_analyst_report,
)


def test_estimate_revenue_pct_theme_disclosed_vs_fallback() -> None:
    pct, method = estimate_revenue_pct_theme(
        {"grid technology": 300.0, "other": 700.0}, ["grid", "smart"]
    )
    assert method == "disclosed"
    assert pct == pytest.approx(0.3)
    pct2, method2 = estimate_revenue_pct_theme(None, ["grid"])
    assert method2 == "needs_llm_estimate"
    assert pct2 is None
    pct3, method3 = estimate_revenue_pct_theme({"unrelated": 100.0}, ["grid"])
    assert method3 == "needs_llm_estimate"
    assert pct3 is None


def test_normalize_sentiment_label_maps_synonyms() -> None:
    assert _normalize_sentiment_label({"sentiment_label": "positive"})["sentiment_label"] == "bullish"
    assert _normalize_sentiment_label({"sentiment_label": "negative"})["sentiment_label"] == "bearish"
    assert _normalize_sentiment_label({"sentiment_label": "Bullish"})["sentiment_label"] == "bullish"
    assert _normalize_sentiment_label({"sentiment_label": "neutral"})["sentiment_label"] == "neutral"


@pytest.mark.asyncio
async def test_analyst_node_stub_mode_returns_report(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000011")
    result = await analyst_node(
        {
            "run_id": run["run_id"],
            "ticker": "AAA",
            "theme": "grid modernization",
            "theme_config": {"sub_exposures": ["smart_grid"]},
        }
    )
    report = result["analyst_reports"][0]
    assert report["ticker"] == "AAA"
    assert report.get("status") != "error"


@pytest.mark.asyncio
async def test_analyst_node_cache_hit_skips_llm_and_apis(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000012")
    await save_analyst_report(
        run["run_id"],
        {
            "ticker": "BBB",
            "thematic_relevance_score": 4.0,
            "thematic_relevance_rationale": "cached",
            "revenue_pct_theme_estimate": 0.2,
            "catalysts": [],
            "risks": [],
            "sentiment_label": "bullish",
            "sentiment_evidence": [],
            "sources": ["stub_gdelt"],
        },
    )
    # A second run for the same ticker must reuse the fresh cached report
    # without re-running the Analyst LLM/tools.
    run2 = await create_run("00000000-0000-0000-0000-000000000013")
    result = await analyst_node(
        {
            "run_id": run2["run_id"],
            "ticker": "BBB",
            "theme": "grid modernization",
            "theme_config": {"sub_exposures": ["smart_grid"]},
        }
    )
    assert result["analyst_reports"][0]["thematic_relevance_rationale"] == "cached"
    assert await get_recent_analyst_report("BBB") is not None


@pytest.mark.asyncio
async def test_copy_recent_analyst_report_rejects_stub_cache_when_live(db: None) -> None:
    run1 = await create_run("00000000-0000-0000-0000-0000000000c1")
    run2 = await create_run("00000000-0000-0000-0000-0000000000c2")
    await save_analyst_report(
        run1["run_id"],
        {
            "ticker": "STUBY",
            "thematic_relevance_score": 4.0,
            "thematic_relevance_rationale": "stub cached",
            "revenue_pct_theme_estimate": 0.2,
            "catalysts": [],
            "risks": [],
            "sentiment_label": "bullish",
            "sentiment_evidence": [],
            "sources": ["stub_gdelt", "stub_google_news"],
        },
    )

    assert await copy_recent_analyst_report(run2["run_id"], "STUBY", reject_stub=True) is None
    assert len(await get_analyst_reports(run2["run_id"])) == 0
    assert await copy_recent_analyst_report(run2["run_id"], "STUBY") is not None


@pytest.mark.asyncio
async def test_analyst_node_retry_reuses_same_run_report(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000015")
    await save_analyst_report(
        run["run_id"],
        {
            "ticker": "DDD",
            "thematic_relevance_score": 4.0,
            "thematic_relevance_rationale": "cached in this run",
            "revenue_pct_theme_estimate": 0.3,
            "catalysts": [],
            "risks": [],
            "sentiment_label": "bullish",
            "sentiment_evidence": [],
            "sources": ["stub_gdelt"],
        },
    )
    state = {
        "run_id": run["run_id"],
        "ticker": "DDD",
        "theme": "grid modernization",
        "theme_config": {"sub_exposures": ["smart_grid"]},
    }
    first = await analyst_node(state)
    second = await analyst_node(state)
    assert first["analyst_reports"][0]["thematic_relevance_rationale"] == (
        "cached in this run"
    )
    assert second["analyst_reports"][0]["thematic_relevance_rationale"] == (
        "cached in this run"
    )
    assert len(await get_analyst_reports(run["run_id"])) == 1


@pytest.mark.asyncio
async def test_analyst_node_error_returns_stub(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000014")
    monkeypatch.setattr(
        "app.integrations.deepseek_client.stubbing_enabled", lambda: False
    )
    monkeypatch.setattr("app.agents.analyst.get_news", lambda ticker: (_ for _ in ()).throw(RuntimeError("boom")))
    result = await analyst_node(
        {
            "run_id": run["run_id"],
            "ticker": "CCC",
            "theme": "x",
            "theme_config": {"sub_exposures": ["y"]},
        }
    )
    entry = result["analyst_reports"][0]
    assert entry["status"] == "error"
    assert "boom" in entry["error"]
