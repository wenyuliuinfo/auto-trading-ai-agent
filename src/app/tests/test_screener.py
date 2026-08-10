"""Screener assembly tests (SCREENER_SKILL.md test fixtures)."""

from __future__ import annotations

from app.agents.screener import MAX_CANDIDATES, assemble_candidate_universe
from app.integrations.etf_holdings import search_holdings


def _hit(ticker: str, market_cap: float | None = 1e10) -> dict[str, object]:
    return {"ticker": ticker, "market_cap": market_cap}


def test_under_minimum_returns_as_is_with_warning() -> None:
    hits = {"a": [_hit("T1"), _hit("T2")], "b": [_hit("T3")]}
    candidates, warnings = assemble_candidate_universe(hits)
    assert len(candidates) == 3
    assert any("below target minimum" in w for w in warnings)


def test_floor_then_fill_keeps_narrow_sub_exposure() -> None:
    broad = [_hit(f"B{i:02d}", 1e11) for i in range(40)]
    narrow = [_hit(f"N{i:02d}", 1e8) for i in range(10)]
    candidates, warnings = assemble_candidate_universe(
        {"broad": broad, "narrow": narrow}, max_candidates=30
    )
    tickers = {c["ticker"] for c in candidates}
    assert any(ticker.startswith("N") for ticker in tickers)
    assert any("capped" in w for w in warnings)


def test_missing_market_cap_does_not_crash_or_drop() -> None:
    hits = {"a": [_hit("T1", None), _hit("T2", 1e10)]}
    candidates, _ = assemble_candidate_universe(hits)
    assert {c["ticker"] for c in candidates} == {"T1", "T2"}


def test_unmapped_sub_exposure_returns_empty_holdings() -> None:
    assert search_holdings("not_a_real_sub_exposure_xyz") == []


def test_max_candidates_is_100() -> None:
    assert MAX_CANDIDATES == 100
