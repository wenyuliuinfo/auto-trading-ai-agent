"""Pydantic request/response schemas for the FastAPI surface.

``ThemeCreateRequest`` deliberately has no ``factor_weights`` field and
``extra="forbid"`` so a caller submitting one gets a 422
(ARCHITECTURE.md §2.1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ScreensRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_avg_dollar_volume: float | None = None
    min_market_cap: float | None = None
    max_per_sub_industry: int | None = None


class ThemeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    sub_exposures: list[str] = Field(min_length=3, max_length=6)
    screens: ScreensRequest | None = None
    weighting_scheme: Literal["equal_weight", "score_weighted"] = "equal_weight"
    validator_enabled: bool = True


class ThemeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub_exposures: list[str] = Field(min_length=3, max_length=6)
    factor_weights: dict[str, float]
    screens: dict[str, Any]
    weighting_scheme: Literal["equal_weight", "score_weighted"] = "equal_weight"
    validator_enabled: bool = True


class ThemeResponse(BaseModel):
    theme_id: str
    name: str
    definition: str
    config: ThemeConfig
    created_at: datetime


class Progress(BaseModel):
    analyzed: int
    total: int


class RunResponse(BaseModel):
    run_id: str
    theme_id: str
    status: Literal["queued", "running", "complete", "failed"]
    requested_at: datetime
    retry_count: int
    error_detail: str | None = None
    progress: Progress | None = None


class BasketHolding(BaseModel):
    ticker: str
    weight: float
    rank: int | None
    sub_exposure: str | None
    swap_reason: str | None
    composite_score: float | None
    factor_contributions: dict[str, float | None]


class RankingRow(BaseModel):
    ticker: str
    composite_score: float | None
    rank: int | None
    factor_contributions: dict[str, float | None]
    caveats: list[str]


class ReportResponse(BaseModel):
    run_id: str
    report_md: str
    disclaimer: str


class RunTriggerResponse(BaseModel):
    run_id: str
    status: Literal["queued"] = "queued"
