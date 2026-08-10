"""Theme endpoints. POST /themes is the only place factor weights load."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import load_factor_weights, load_sub_exposure_etf_map
from app.data.queries import create_theme, get_theme, list_themes
from app.schemas import ThemeCreateRequest, ThemeResponse

router = APIRouter(prefix="/themes", tags=["themes"])


@router.post("", response_model=ThemeResponse, status_code=201)
async def post_theme(payload: ThemeCreateRequest) -> ThemeResponse:
    """Create a theme with server-populated factor weights (never user input)."""
    weights = load_factor_weights()
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise HTTPException(
            status_code=500,
            detail="factor_weights.yaml does not sum to 1.0; refusing to persist",
        )
    mapped = load_sub_exposure_etf_map()
    unknown = [sub for sub in payload.sub_exposures if sub not in mapped]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"sub_exposures not in config/sub_exposure_etf_map.yaml: {unknown}",
        )
    screens = {
        "min_avg_dollar_volume": (
            payload.screens.min_avg_dollar_volume
            if payload.screens and payload.screens.min_avg_dollar_volume is not None
            else 5_000_000
        ),
        "min_market_cap": (
            payload.screens.min_market_cap
            if payload.screens and payload.screens.min_market_cap is not None
            else 300_000_000
        ),
        "max_per_sub_industry": (
            payload.screens.max_per_sub_industry
            if payload.screens and payload.screens.max_per_sub_industry is not None
            else 3
        ),
    }
    config = {
        "sub_exposures": payload.sub_exposures,
        "factor_weights": weights,
        "screens": screens,
        "weighting_scheme": payload.weighting_scheme,
        "validator_enabled": payload.validator_enabled,
    }
    theme = await create_theme(payload.name, payload.definition, config)
    return ThemeResponse.model_validate(theme)


@router.get("", response_model=list[ThemeResponse])
async def get_themes() -> list[ThemeResponse]:
    themes = await list_themes()
    return [ThemeResponse.model_validate(theme) for theme in themes]


@router.get("/{theme_id}", response_model=ThemeResponse)
async def get_theme_by_id(theme_id: str) -> ThemeResponse:
    theme = await get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    return ThemeResponse.model_validate(theme)
