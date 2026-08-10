"""Trader agent: deterministic basket construction under hard constraints."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from app.data.queries import save_basket
from app.logging_conf import get_logger

logger = get_logger(__name__)

TARGET_BASKET_SIZE = 10
MIN_BASKET_SIZE = 5
NEAR_MISS_COUNT = 5

TRADER_MODEL = "deepseek-v4-pro"
TRADER_TEMPERATURE = 0.2

TRADER_SWAP_REASON_PROMPT = """You are a Portfolio Construction Agent. You take the ranked list from the
Modeling Agent and construct a 5-10 name basket. You are not re-analyzing
company merits — the ranking is your primary input.

Constraints you must enforce:
1. Select top-ranked names, but skip any that fail the hard screens:
   ADV < $5M, market cap < $300M, or a `caveats` flag marked "exclude"
   from the Modeling Agent, or a negative/missing composite score.
2. Sector/sub-exposure diversification: no single GICS sub-industry may
   account for more than 3 of the 5-10 positions, so the basket reflects
   the theme's breadth, not one sub-exposure.
3. Position sizing: default to equal_weight unless `weighting_scheme` is
   set to score_weighted (`config/theme_create_request.schema.json` —
   these are the only two valid values). If score_weighted, normalize
   composite scores to sum to 100%, floor any position below 5%, cap any
   position above 20%, then renormalize the clipped weights so the
   basket still sums to 100% (`TRADER_SKILL.md` Hard Rule 4).
4. If enforcing constraint 2 requires skipping a higher-ranked name for a
   lower-ranked one in an underrepresented sub-exposure, log that swap
   explicitly with the reason.

Output: final basket {ticker, weight, rank, sub_exposure, swap_reason if
applicable}, plus a list of near-miss names (the next ~5 eligible names
after the cutoff) for the Report Agent to reference as "considered but
excluded."

For each swap event below, write one short sentence of prose explaining
the diversification skip. Return JSON: {"reasons": {"<included_ticker>":
"<reason>"}}. The swap decision is already made by deterministic code;
your prose must not change which ticker was included."""


class SwapReasons(BaseModel):
    reasons: dict[str, str]


def construct_basket(
    ranked_list: list[dict[str, Any]], theme_config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic basket construction (TRADER_SKILL.md Hard Rule 1).

    Returns ``(basket, near_misses, swap_events)``; swap_events is
    structured data for the narrow LLM call, not prose itself.
    """
    screens = theme_config.get("screens", {})
    min_cap = float(screens.get("min_market_cap", 300_000_000))
    min_adv = float(screens.get("min_avg_dollar_volume", 5_000_000))
    max_per_sub = int(screens.get("max_per_sub_industry", 3))

    eligible = [
        candidate
        for candidate in ranked_list
        if candidate.get("composite_score") is not None
        and candidate["composite_score"] >= 0
        and (candidate.get("market_cap") or 0) >= min_cap
        and (candidate.get("avg_dollar_volume") or 0) >= min_adv
        and "exclude" not in (candidate.get("caveats") or [])
    ]

    basket: list[dict[str, Any]] = []
    sub_exposure_counts: dict[str, int] = defaultdict(int)
    swap_events: list[dict[str, Any]] = []
    most_recent_skip: dict[str, Any] | None = None

    for candidate in eligible:
        if len(basket) >= TARGET_BASKET_SIZE:
            break
        sub_exposure = str(candidate.get("sub_exposure") or "unassigned")
        if sub_exposure_counts[sub_exposure] >= max_per_sub:
            most_recent_skip = {
                "skipped_ticker": candidate["ticker"],
                "skipped_rank": candidate.get("rank"),
                "sub_exposure": sub_exposure,
                "cap": max_per_sub,
            }
            continue
        basket.append(candidate)
        sub_exposure_counts[sub_exposure] += 1
        if most_recent_skip is not None:
            swap_events.append(
                {
                    **most_recent_skip,
                    "included_ticker": candidate["ticker"],
                    "included_rank": candidate.get("rank"),
                }
            )
            most_recent_skip = None

    _apply_position_sizing(
        basket, str(theme_config.get("weighting_scheme", "equal_weight"))
    )
    near_misses = eligible[len(basket) : len(basket) + NEAR_MISS_COUNT]
    return basket, near_misses, swap_events


def _apply_position_sizing(basket: list[dict[str, Any]], weighting_scheme: str) -> None:
    if not basket:
        return
    if weighting_scheme == "equal_weight":
        weight = 1.0 / len(basket)
        for candidate in basket:
            candidate["weight"] = weight
        return

    total_score = sum(
        float(candidate.get("composite_score") or 0.0) for candidate in basket
    )
    if total_score <= 0:
        weight = 1.0 / len(basket)
        for candidate in basket:
            candidate["weight"] = weight
        return
    raw_weights = {
        candidate["ticker"]: float(candidate.get("composite_score") or 0.0)
        / total_score
        for candidate in basket
    }
    clipped = {
        ticker: min(max(weight, 0.05), 0.20) for ticker, weight in raw_weights.items()
    }
    clipped_total = sum(clipped.values())
    for candidate in basket:
        candidate["weight"] = clipped[candidate["ticker"]] / clipped_total


def _stub_swap_reasons(swap_events: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(event["included_ticker"]): (
            f"{event['skipped_ticker']} (rank {event['skipped_rank']}) was skipped "
            f"because {event['sub_exposure']} already has {event['cap']} positions "
            "at the cap."
        )
        for event in swap_events
    }


async def trader_node(state: dict[str, Any]) -> dict[str, Any]:
    """Construct the basket deterministically, then explain swaps (LLM only)."""
    from app.integrations.deepseek_client import DeepSeekClient, stubbing_enabled

    basket, near_misses, swap_events = construct_basket(
        state["ranked_list"], state["theme_config"]
    )
    if swap_events:
        if stubbing_enabled():
            reasons = _stub_swap_reasons(swap_events)
        else:
            client = DeepSeekClient()
            output = await client.complete_json(
                model=TRADER_MODEL,
                temperature=TRADER_TEMPERATURE,
                system=TRADER_SWAP_REASON_PROMPT,
                input_data={"swap_events": swap_events},
                response_schema=SwapReasons,
            )
            reasons = {str(k): str(v) for k, v in output["reasons"].items()}
        for candidate in basket:
            if candidate["ticker"] in reasons:
                candidate["swap_reason"] = reasons[candidate["ticker"]]

    await save_basket(state["run_id"], basket)
    logger.info(
        "trader_complete",
        run_id=state["run_id"],
        basket_size=len(basket),
        swaps=len(swap_events),
    )
    return {"basket": basket, "near_misses": near_misses}
