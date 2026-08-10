"""Database plumbing tests: loop isolation for the Celery worker."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.data.db import configure_database, dispose_db, get_engine, init_db
from app.data.queries import (
    create_run,
    get_basket_rows,
    get_cached_factor_tickers,
    get_factor_panel_rows,
    get_rankings,
    save_basket,
    save_factor_panel,
    save_rankings,
)


def test_dispose_db_resets_engine_for_next_loop(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path}/loop.db"

    async def first_loop() -> None:
        configure_database(url)
        await init_db()
        await create_run("00000000-0000-0000-0000-0000000000a1")

    async def second_loop() -> None:
        # Would reuse a stale loop-bound pool if dispose_db had not reset it.
        await create_run("00000000-0000-0000-0000-0000000000a2")

    asyncio.run(first_loop())
    asyncio.run(dispose_db())
    engine_before = get_engine()
    asyncio.run(second_loop())
    asyncio.run(dispose_db())
    assert get_engine() is not engine_before


@pytest.mark.asyncio
async def test_cached_factor_tickers_ignore_null_raw_rows(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-0000000000b1")
    today = date.today()
    await save_factor_panel(
        run["run_id"],
        [
            {
                "ticker": "NULLY",
                "as_of_date": today,
                "factor_name": "pe_ratio",
                "raw_value": None,
                "z_score": None,
            },
            {
                "ticker": "GOOD",
                "as_of_date": today,
                "factor_name": "pe_ratio",
                "raw_value": 20.0,
                "z_score": None,
            },
        ],
    )

    cached = await get_cached_factor_tickers(today)

    assert "GOOD" in cached
    assert "NULLY" not in cached


@pytest.mark.asyncio
async def test_save_rankings_replaces_previous_rows(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-0000000000c1")
    rows = [
        {
            "ticker": "AAA",
            "composite_score": 2.5,
            "rank": 1,
            "factor_contributions": {"thematic_z": 1.0},
            "caveats": [],
        },
        {
            "ticker": "BBB",
            "composite_score": 1.5,
            "rank": 2,
            "factor_contributions": {"quality_z": 0.5},
            "caveats": [],
        },
    ]

    await save_rankings(run["run_id"], rows)
    await save_rankings(run["run_id"], rows)

    saved = await get_rankings(run["run_id"])
    assert [row["ticker"] for row in saved] == ["AAA", "BBB"]


@pytest.mark.asyncio
async def test_save_basket_replaces_previous_rows(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-0000000000c2")
    rows = [
        {"ticker": "AAA", "weight": 0.6, "rank": 1, "sub_exposure": "a"},
        {"ticker": "BBB", "weight": 0.4, "rank": 2, "sub_exposure": "b"},
    ]

    await save_basket(run["run_id"], rows)
    await save_basket(run["run_id"], rows)

    saved = await get_basket_rows(run["run_id"])
    assert [row["ticker"] for row in saved] == ["AAA", "BBB"]


@pytest.mark.asyncio
async def test_save_factor_panel_replaces_previous_rows(db: None) -> None:
    run = await create_run("00000000-0000-0000-0000-0000000000c3")
    today = date.today()
    rows = [
        {
            "ticker": "AAA",
            "as_of_date": today,
            "factor_name": "pe_ratio",
            "raw_value": 20.0,
            "z_score": 1.0,
        },
        {
            "ticker": "BBB",
            "as_of_date": today,
            "factor_name": "pe_ratio",
            "raw_value": 10.0,
            "z_score": 0.5,
        },
    ]

    await save_factor_panel(run["run_id"], rows)
    await save_factor_panel(run["run_id"], rows)

    saved = await get_factor_panel_rows(run["run_id"])
    assert [(row["ticker"], row["factor_name"]) for row in saved] == [
        ("AAA", "pe_ratio"),
        ("BBB", "pe_ratio"),
    ]
