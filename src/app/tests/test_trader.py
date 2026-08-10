"""Trader constraint tests (ARCHITECTURE.md §8.A)."""

from __future__ import annotations

import pytest

from app.agents.trader import TARGET_BASKET_SIZE, construct_basket
from app.data.queries import (
    create_run,
    get_basket_with_scores,
    save_basket,
    save_rankings,
)


def _ranked(
    n: int = 15, sub_exposures: list[str] | None = None, cap: float = 1e11, adv: float = 1e8
) -> list[dict[str, object]]:
    exposures = sub_exposures or ["a", "b", "c"]
    return [
        {
            "ticker": f"T{i:02d}",
            "rank": i + 1,
            "composite_score": 20.0 - i,
            "market_cap": cap,
            "avg_dollar_volume": adv,
            "sub_exposure": exposures[i % len(exposures)],
            "caveats": [],
        }
        for i in range(n)
    ]


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "screens": {
            "min_avg_dollar_volume": 5_000_000,
            "min_market_cap": 300_000_000,
            "max_per_sub_industry": 3,
        },
        "weighting_scheme": "equal_weight",
    }
    config.update(overrides)
    return config


def test_construct_basket_enforces_screens_before_rank() -> None:
    ranked = _ranked()
    ranked[0]["market_cap"] = 100_000_000
    ranked[1]["avg_dollar_volume"] = 1_000_000
    ranked[2]["caveats"] = ["exclude"]
    basket, near_misses, swaps = construct_basket(ranked, _config())
    tickers = {row["ticker"] for row in basket}
    assert "T00" not in tickers
    assert "T01" not in tickers
    assert "T02" not in tickers
    assert 5 <= len(basket) <= TARGET_BASKET_SIZE
    assert len(near_misses) == 3
    assert swaps == []


def test_construct_basket_skips_negative_composite_scores() -> None:
    ranked = _ranked(20, sub_exposures=["a", "b", "c", "d", "e"])
    for row in ranked[:3]:
        row["composite_score"] = -1.0
    basket, near_misses, _ = construct_basket(ranked, _config())

    assert all(float(row["composite_score"]) >= 0.0 for row in basket)
    assert len(basket) == 10
    assert len(near_misses) == 5


def test_construct_basket_enforces_sub_exposure_cap_with_swap_events() -> None:
    ranked = _ranked(12, sub_exposures=["a", "a", "a", "a", "b", "c", "d", "e", "f", "g"])
    basket, _, swaps = construct_basket(ranked, _config())
    assert len(basket) >= 5
    assert swaps, "a diversification skip should produce a structured swap event"


def test_score_weighted_sizing_renormalizes_after_clipping() -> None:
    ranked = _ranked(10, cap=1e11)
    for index, row in enumerate(ranked):
        row["composite_score"] = 100.0 if index < 3 else 1.0
    basket, _, _ = construct_basket(ranked, _config(weighting_scheme="score_weighted"))
    total = sum(float(row["weight"]) for row in basket)
    assert total == pytest.approx(1.0, abs=1e-9)
    assert all(float(row["weight"]) > 0.0 for row in basket)


def test_partial_basket_returns_near_misses_without_raising() -> None:
    ranked = _ranked(6)
    basket, near_misses, swaps = construct_basket(ranked, _config())
    assert len(basket) == 6
    assert near_misses == []
    assert swaps == []


@pytest.mark.asyncio
async def test_get_basket_with_scores_joins_rankings(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-000000000001")
    run_id = run["run_id"]
    await save_rankings(
        run_id,
        [
            {
                "ticker": "AAA",
                "composite_score": 2.5,
                "rank": 1,
                "factor_contributions": {"thematic_z": 1.0},
                "caveats": [],
            }
        ],
    )
    await save_basket(
        run_id,
        [{"ticker": "AAA", "weight": 0.5, "rank": 1, "sub_exposure": "a"}],
    )
    rows = await get_basket_with_scores(run_id)
    assert rows[0]["composite_score"] == 2.5
