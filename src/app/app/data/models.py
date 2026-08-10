"""SQLAlchemy models for the domain database (ARCHITECTURE.md §2.1).

The production schema is created by ``infra/init.sql``; these models are
kept in sync with it and are also used by ``create_all`` for local
development and tests. UUID primary keys are stored as 36-char strings
so the same models work on both Postgres and SQLite.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Theme(Base):
    __tablename__ = "themes"

    theme_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    theme_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("themes.theme_id", ondelete="CASCADE"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class Candidate(Base):
    __tablename__ = "candidates"

    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    gics_subindustry: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_exposure_tag: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_dollar_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AnalystReport(Base):
    __tablename__ = "analyst_reports"
    __table_args__ = (UniqueConstraint("ticker", "run_id", name="uq_analyst_ticker_run"),)

    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    thematic_relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    thematic_relevance_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    revenue_pct_theme_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    catalysts: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    risks: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    sentiment_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sentiment_evidence: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    sources: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    news: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_TYPE, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FactorPanel(Base):
    __tablename__ = "factor_panel"

    factor_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    factor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class Ranking(Base):
    __tablename__ = "rankings"

    ranking_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    factor_contributions: Mapped[dict[str, float] | None] = mapped_column(
        JSON_TYPE, nullable=True
    )
    caveats: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)


class Basket(Base):
    __tablename__ = "baskets"

    basket_row_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sub_exposure: Mapped[str | None] = mapped_column(Text, nullable=True)
    swap_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Report(Base):
    __tablename__ = "reports"

    report_doc_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BasketPerformance(Base):
    __tablename__ = "basket_performance"

    perf_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    realized_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha: Mapped[float | None] = mapped_column(Float, nullable=True)
