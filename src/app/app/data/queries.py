"""Plain database access functions used by the API, agents, and tools.

Everything in this module is async and owns its own session; callers
never open a session themselves (CONVENTIONS.md §2.1).
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from app.data.db import get_session
from app.data.models import (
    AnalystReport,
    Basket,
    BasketPerformance,
    Candidate,
    FactorPanel,
    Ranking,
    Report,
    Run,
    Theme,
)

JSONDict = dict[str, Any]


def _u(value: str) -> uuid.UUID:
    """Convert a UUID string to the native type the ORM expects."""
    return uuid.UUID(value)


def _theme_dict(theme: Theme) -> JSONDict:
    return {
        "theme_id": str(theme.theme_id),
        "name": theme.name,
        "definition": theme.definition,
        "config": theme.config,
        "created_at": theme.created_at,
    }


def _run_dict(run: Run) -> JSONDict:
    return {
        "run_id": str(run.run_id),
        "theme_id": str(run.theme_id),
        "status": run.status,
        "requested_at": run.requested_at,
        "retry_count": run.retry_count,
        "error_detail": run.error_detail,
    }


def _analyst_dict(row: AnalystReport) -> JSONDict:
    return {
        "report_id": str(row.report_id),
        "run_id": str(row.run_id),
        "ticker": row.ticker,
        "thematic_relevance_score": row.thematic_relevance_score,
        "thematic_relevance_rationale": row.thematic_relevance_rationale,
        "revenue_pct_theme_estimate": row.revenue_pct_theme_estimate,
        "catalysts": row.catalysts or [],
        "risks": row.risks or [],
        "sentiment_label": row.sentiment_label,
        "sentiment_evidence": row.sentiment_evidence or [],
        "sources": row.sources or [],
        "news": row.news or [],
        "fetched_at": row.fetched_at,
    }


def _ranking_dict(row: Ranking) -> JSONDict:
    return {
        "ranking_id": str(row.ranking_id),
        "run_id": str(row.run_id),
        "ticker": row.ticker,
        "composite_score": row.composite_score,
        "rank": row.rank,
        "factor_contributions": row.factor_contributions or {},
        "caveats": row.caveats or [],
    }


def _basket_dict(row: Basket) -> JSONDict:
    return {
        "basket_row_id": str(row.basket_row_id),
        "run_id": str(row.run_id),
        "ticker": row.ticker,
        "weight": row.weight,
        "rank": row.rank,
        "sub_exposure": row.sub_exposure,
        "swap_reason": row.swap_reason,
    }


# --- Themes --------------------------------------------------------------


async def create_theme(name: str, definition: str, config: JSONDict) -> JSONDict:
    async with get_session() as session:
        theme = Theme(name=name, definition=definition, config=config)
        session.add(theme)
        await session.commit()
        await session.refresh(theme)
        return _theme_dict(theme)


async def get_theme(theme_id: str) -> JSONDict | None:
    async with get_session() as session:
        row = await session.get(Theme, _u(theme_id))
        return _theme_dict(row) if row else None


async def list_themes() -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(select(Theme).order_by(Theme.created_at.desc()))
        return [_theme_dict(row) for row in result.scalars().all()]


# --- Runs -----------------------------------------------------------------


async def create_run(theme_id: str) -> JSONDict:
    async with get_session() as session:
        run = Run(theme_id=_u(theme_id), status="queued")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return _run_dict(run)


async def get_run(run_id: str) -> JSONDict | None:
    async with get_session() as session:
        row = await session.get(Run, _u(run_id))
        return _run_dict(row) if row else None


async def update_run_status(
    run_id: str, status: str, error_detail: str | None = None
) -> None:
    async with get_session() as session:
        row = await session.get(Run, _u(run_id))
        if row is None:
            raise KeyError(f"run {run_id} not found")
        row.status = status
        if error_detail is not None:
            row.error_detail = error_detail
        await session.commit()


async def count_analyst_reports(run_id: str) -> int:
    async with get_session() as session:
        result = await session.execute(
            select(func.count()).select_from(AnalystReport).where(
                AnalystReport.run_id == _u(run_id)
            )
        )
        return int(result.scalar_one())


# --- Candidates ------------------------------------------------------------


async def save_candidates(run_id: str, candidates: list[JSONDict]) -> None:
    async with get_session() as session:
        # A retry pass replaces the previous pass's universe for this run.
        await session.execute(delete(Candidate).where(Candidate.run_id == _u(run_id)))
        for candidate in candidates:
            session.add(
                Candidate(
                    run_id=_u(run_id),
                    ticker=candidate["ticker"],
                    company_name=candidate.get("company_name"),
                    gics_subindustry=candidate.get("gics_subindustry"),
                    sub_exposure_tag=candidate.get("sub_exposure"),
                    market_cap=candidate.get("market_cap"),
                    avg_dollar_volume=candidate.get("avg_dollar_volume"),
                )
            )
        await session.commit()


async def get_candidates(run_id: str) -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(
            select(Candidate).where(Candidate.run_id == _u(run_id)).order_by(Candidate.ticker)
        )
        rows = result.scalars().all()
        return [
            {
                "candidate_id": str(row.candidate_id),
                "run_id": str(row.run_id),
                "ticker": row.ticker,
                "company_name": row.company_name,
                "gics_subindustry": row.gics_subindustry,
                "sub_exposure": row.sub_exposure_tag,
                "market_cap": row.market_cap,
                "avg_dollar_volume": row.avg_dollar_volume,
            }
            for row in rows
        ]


# --- Analyst reports --------------------------------------------------------


async def get_recent_analyst_report(
    ticker: str, max_age_hours: int = 24
) -> JSONDict | None:
    """Find a fresh AnalystReport for ``ticker`` across any run."""
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    async with get_session() as session:
        result = await session.execute(
            select(AnalystReport)
            .where(AnalystReport.ticker == ticker)
            .where(AnalystReport.fetched_at >= cutoff)
            .order_by(AnalystReport.fetched_at.desc())
            .limit(1)
        )
        row = result.scalars().first()
        return _analyst_dict(row) if row else None


def _has_stub_sources(report: JSONDict) -> bool:
    return any(str(source).startswith("stub_") for source in report.get("sources", []))


async def copy_recent_analyst_report(
    run_id: str, ticker: str, reject_stub: bool = False
) -> JSONDict | None:
    """Return a report for ``(run_id, ticker)``, copying one only when missing.

    Idempotent under Celery/LangGraph retries: a report already persisted
    for this run is returned as-is instead of inserted again, which would
    violate the ``(ticker, run_id)`` unique constraint. When ``reject_stub``
    is true, stub-generated reports are never reused by a live run.
    """
    async with get_session() as session:
        existing = await session.execute(
            select(AnalystReport)
            .where(
                AnalystReport.run_id == _u(run_id),
                AnalystReport.ticker == ticker,
            )
            .limit(1)
        )
        row = existing.scalars().first()
        if row is not None:
            existing_report = _analyst_dict(row)
            if reject_stub and _has_stub_sources(existing_report):
                await session.delete(row)
                await session.commit()
                return None
            return existing_report
    cached = await get_recent_analyst_report(ticker)
    if cached is None:
        return None
    if reject_stub and _has_stub_sources(cached):
        return None
    report = AnalystReport(
        run_id=_u(run_id),
        ticker=ticker,
        thematic_relevance_score=cached["thematic_relevance_score"],
        thematic_relevance_rationale=cached["thematic_relevance_rationale"],
        revenue_pct_theme_estimate=cached["revenue_pct_theme_estimate"],
        catalysts=cached["catalysts"],
        risks=cached["risks"],
        sentiment_label=cached["sentiment_label"],
        sentiment_evidence=cached["sentiment_evidence"],
        sources=cached["sources"],
        news=cached["news"],
    )
    async with get_session() as session:
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return _analyst_dict(report)


async def save_analyst_report(run_id: str, report: JSONDict) -> None:
    async with get_session() as session:
        row = AnalystReport(
            run_id=_u(run_id),
            ticker=report["ticker"],
            thematic_relevance_score=report.get("thematic_relevance_score"),
            thematic_relevance_rationale=report.get("thematic_relevance_rationale"),
            revenue_pct_theme_estimate=report.get("revenue_pct_theme_estimate"),
            catalysts=report.get("catalysts", []),
            risks=report.get("risks", []),
            sentiment_label=report.get("sentiment_label"),
            sentiment_evidence=report.get("sentiment_evidence", []),
            sources=report.get("sources", []),
            news=report.get("news", []),
        )
        session.add(row)
        await session.commit()


async def get_analyst_reports(run_id: str) -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(
            select(AnalystReport)
            .where(AnalystReport.run_id == _u(run_id))
            .order_by(AnalystReport.ticker)
        )
        return [_analyst_dict(row) for row in result.scalars().all()]


# --- Factor panel ------------------------------------------------------------


async def save_factor_panel(run_id: str, rows: list[JSONDict]) -> None:
    """Persist raw + z-scored factor rows for one run."""
    async with get_session() as session:
        # A Screener retry pass re-runs Modeling; replace the prior pass's rows.
        await session.execute(
            delete(FactorPanel).where(FactorPanel.run_id == _u(run_id))
        )
        for row in rows:
            session.add(
                FactorPanel(
                    run_id=_u(run_id),
                    ticker=row["ticker"],
                    as_of_date=row["as_of_date"],
                    factor_name=row["factor_name"],
                    raw_value=row.get("raw_value"),
                    z_score=row.get("z_score"),
                )
            )
        await session.commit()


async def get_factor_panel_rows(run_id: str) -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(
            select(FactorPanel)
            .where(FactorPanel.run_id == _u(run_id))
            .order_by(FactorPanel.ticker, FactorPanel.factor_name)
        )
        return [
            {
                "ticker": row.ticker,
                "as_of_date": row.as_of_date,
                "factor_name": row.factor_name,
                "raw_value": row.raw_value,
                "z_score": row.z_score,
            }
            for row in result.scalars().all()
        ]


async def get_cached_factor_tickers(as_of_date: date) -> list[str]:
    """Tickers with a complete raw factor row fetched today (Hard Rule 10).

    A ticker only counts as cached when the raw ``pe_ratio`` row exists and
    has a non-null value; all-null rows from a failed fetch must be retried.
    """
    async with get_session() as session:
        result = await session.execute(
            select(FactorPanel.ticker)
            .where(FactorPanel.as_of_date == as_of_date)
            .where(FactorPanel.factor_name == "pe_ratio")
            .where(FactorPanel.raw_value.is_not(None))
            .distinct()
        )
        return [str(t) for t in result.scalars().all()]


async def get_factor_panel_for_tickers(
    tickers: list[str], as_of_date: date
) -> list[JSONDict]:
    """Factor rows for ``tickers`` fetched today across any run (cache reuse)."""
    async with get_session() as session:
        result = await session.execute(
            select(FactorPanel)
            .where(FactorPanel.ticker.in_(tickers))
            .where(FactorPanel.as_of_date == as_of_date)
        )
        return [
            {
                "ticker": row.ticker,
                "as_of_date": row.as_of_date,
                "factor_name": row.factor_name,
                "raw_value": row.raw_value,
                "z_score": row.z_score,
            }
            for row in result.scalars().all()
        ]


# --- Rankings -----------------------------------------------------------------


async def save_rankings(run_id: str, ranked_list: list[JSONDict]) -> None:
    async with get_session() as session:
        # A Screener retry pass re-runs Modeling; replace the prior pass's rows.
        await session.execute(delete(Ranking).where(Ranking.run_id == _u(run_id)))
        for row in ranked_list:
            session.add(
                Ranking(
                    run_id=_u(run_id),
                    ticker=row["ticker"],
                    composite_score=row.get("composite_score"),
                    rank=row.get("rank"),
                    factor_contributions=row.get("factor_contributions", {}),
                    caveats=row.get("caveats", []),
                )
            )
        await session.commit()


async def get_rankings(run_id: str) -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(
            select(Ranking)
            .where(Ranking.run_id == _u(run_id))
            .order_by(Ranking.rank.asc().nullslast())
        )
        return [_ranking_dict(row) for row in result.scalars().all()]


# --- Basket ---------------------------------------------------------------------


async def save_basket(run_id: str, basket: list[JSONDict]) -> None:
    """Persist basket rows.

    Only ticker/weight/rank/sub_exposure/swap_reason are stored;
    composite_score lives in rankings (TRADER_SKILL.md Hard Rule 5).
    """
    async with get_session() as session:
        # A Screener retry pass re-runs Trader; replace the prior pass's rows.
        await session.execute(delete(Basket).where(Basket.run_id == _u(run_id)))
        for row in basket:
            session.add(
                Basket(
                    run_id=_u(run_id),
                    ticker=row["ticker"],
                    weight=row["weight"],
                    rank=row.get("rank"),
                    sub_exposure=row.get("sub_exposure"),
                    swap_reason=row.get("swap_reason"),
                )
            )
        await session.commit()


async def get_basket_rows(run_id: str) -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(
            select(Basket).where(Basket.run_id == _u(run_id)).order_by(Basket.rank.asc())
        )
        return [_basket_dict(row) for row in result.scalars().all()]


async def get_basket_with_scores(run_id: str) -> list[JSONDict]:
    """Join baskets + rankings on (run_id, ticker).

    Shared single source of truth for the /runs/{run_id}/basket API and
    the Report agent's context assembly (TRADER_SKILL.md). Raises if a
    basket row has no matching ranking row.
    """
    basket_rows = await get_basket_rows(run_id)
    ranking_rows = {r["ticker"]: r for r in await get_rankings(run_id)}
    joined: list[JSONDict] = []
    for basket_row in basket_rows:
        ranking = ranking_rows.get(basket_row["ticker"])
        if ranking is None:
            raise KeyError(
                f"basket row for {basket_row['ticker']} has no ranking row"
            )
        joined.append(
            {
                **basket_row,
                "composite_score": ranking["composite_score"],
                "factor_contributions": ranking["factor_contributions"],
            }
        )
    return joined


# --- Report ---------------------------------------------------------------------


async def save_report(run_id: str, report_md: str) -> None:
    async with get_session() as session:
        session.add(Report(run_id=_u(run_id), report_md=report_md))
        await session.commit()


async def get_report(run_id: str) -> str | None:
    async with get_session() as session:
        result = await session.execute(
            select(Report.report_md).where(Report.run_id == _u(run_id))
        )
        return result.scalar_one_or_none()


# --- Operations/evaluation support -------------------------------------------------


async def get_recent_completed_runs(limit: int = 10) -> list[JSONDict]:
    async with get_session() as session:
        result = await session.execute(
            select(Run)
            .where(Run.status == "complete")
            .order_by(Run.requested_at.desc())
            .limit(limit)
        )
        return [_run_dict(row) for row in result.scalars().all()]


async def save_basket_performance(
    run_id: str, as_of_date: date, **values: float | None
) -> None:
    async with get_session() as session:
        session.add(
            BasketPerformance(
                run_id=_u(run_id),
                as_of_date=as_of_date,
                realized_return=values.get("realized_return"),
                benchmark_return=values.get("benchmark_return"),
                alpha=values.get("alpha"),
            )
        )
        await session.commit()


def finite_float(value: Any) -> float | None:
    """Coerce JSON-ish numbers to float, mapping NaN/None to None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
