"""Screener agent: theme -> bounded Candidate Universe.

Deterministic candidate assembly lives here (``assemble_candidate_universe``);
``search_sector``/``search_holdings`` are backed by integrations.
"""

from __future__ import annotations

from typing import Any

from app.data.queries import save_candidates
from app.integrations.etf_holdings import search_holdings
from app.integrations.reference_universe import search_sector
from app.logging_conf import get_logger

logger = get_logger(__name__)

MIN_CANDIDATES = 50
MAX_CANDIDATES = 100

SCREENER_SYSTEM_PROMPT = """You are a Universe Screener for a thematic equity research desk. Your job is
to convert an investment theme into a bounded, verifiable list of candidate
tickers — not to judge or rank them.

Given a theme (e.g. "grid modernization," "GLP-1 supply chain," "onshoring
of semiconductor capacity"), you will:

1. Decompose the theme into 3-6 sub-exposures (e.g. for "grid modernization":
   transmission equipment, smart meters, grid software, utilities capex
   beneficiaries, battery storage).
2. For each sub-exposure, call the `search_holdings` and `search_sector`
   tools to pull constituent tickers from relevant thematic ETFs, GICS
   sub-industries, and index membership — do not invent tickers from memory.
3. Deduplicate and output a candidate list of 50-100 US and major
   international listed equities/ETFs with: ticker, company name, GICS
   sub-industry, sub-exposure tag, market cap, and average daily dollar
   volume (for a later liquidity filter).
4. Flag (but do not exclude) any name with ADV under $5M or market cap
   under $300M — the Trader agent will apply the final liquidity screen.

Do not include an investment opinion. Do not rank. Output only the
structured candidate table as JSON matching the provided schema. If a
sub-exposure returns fewer than 5 candidates, say so explicitly rather than
padding the list with loosely related names."""

SCREENER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_sector",
            "description": "Find tickers whose GICS sub-industry matches a keyword",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_holdings",
            "description": "Find constituent tickers of ETFs mapped to a sub-exposure",
            "parameters": {
                "type": "object",
                "properties": {"sub_exposure": {"type": "string"}},
                "required": ["sub_exposure"],
            },
        },
    },
]


def enrich_with_market_cap(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing market caps from the reference universe when available."""
    by_ticker = {row["ticker"]: row for row in search_sector("")}
    for candidate in candidates:
        if candidate.get("market_cap") is None:
            row = by_ticker.get(candidate["ticker"])
            if row is not None:
                candidate["market_cap"] = row.get("market_cap")
    return candidates


def assemble_candidate_universe(
    sub_exposure_hits: dict[str, list[dict[str, Any]]],
    max_candidates: int = MAX_CANDIDATES,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge, dedupe, and cap raw tool hits into the Candidate Universe.

    Deterministic floor-then-fill by market cap (SCREENER_SKILL.md Hard
    Rule 7). Returns ``(candidates, warnings)``; a universe under the
    minimum is returned as-is so the bounded retry loop can widen it.
    """
    warnings: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    for sub_exposure, hits in sub_exposure_hits.items():
        if len(hits) < 5:
            warnings.append(
                f"sub_exposure '{sub_exposure}' returned only {len(hits)} candidates"
            )
        for hit in hits:
            ticker = str(hit["ticker"]).upper()
            if ticker not in merged:
                merged[ticker] = {**hit, "ticker": ticker, "sub_exposure_tags": set()}
            merged[ticker]["sub_exposure_tags"].add(sub_exposure)

    candidates = enrich_with_market_cap(list(merged.values()))

    if len(candidates) < MIN_CANDIDATES:
        warnings.append(
            f"universe below target minimum: {len(candidates)} < {MIN_CANDIDATES}"
        )
        return _finalize(candidates), warnings

    if len(candidates) <= max_candidates:
        return _finalize(candidates), warnings

    n_sub_exposures = len(sub_exposure_hits)
    floor = max(3, max_candidates // (2 * n_sub_exposures))
    selected: dict[str, dict[str, Any]] = {}
    for sub_exposure in sub_exposure_hits:
        pool = sorted(
            (
                c
                for c in candidates
                if sub_exposure in c["sub_exposure_tags"]
            ),
            key=lambda c: c.get("market_cap") or 0,
            reverse=True,
        )
        for candidate in pool[:floor]:
            selected[candidate["ticker"]] = candidate

    remaining_slots = max_candidates - len(selected)
    remaining_pool = sorted(
        (c for c in candidates if c["ticker"] not in selected),
        key=lambda c: c.get("market_cap") or 0,
        reverse=True,
    )
    for candidate in remaining_pool[:remaining_slots]:
        selected[candidate["ticker"]] = candidate

    warnings.append(
        f"universe capped: {len(candidates)} raw hits -> {len(selected)} candidates"
    )
    return _finalize(list(selected.values())), warnings


def _finalize(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert sets to JSON-safe lists and pick the primary sub-exposure."""
    for candidate in candidates:
        tags = sorted(candidate.get("sub_exposure_tags", set()))
        candidate["sub_exposure_tags"] = list(tags)
        candidate["sub_exposure"] = tags[0] if tags else candidate.get("sub_exposure")
    return candidates


def _stub_sub_exposure_hits(
    sub_exposures: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Deterministic tool-call results for offline runs (no LLM needed)."""
    hits: dict[str, list[dict[str, Any]]] = {}
    for sub_exposure in sub_exposures:
        holdings = search_holdings(sub_exposure)
        keyword = sub_exposure.replace("_", " ").split()[0]
        sector_hits = search_sector(keyword)
        hits[sub_exposure] = holdings + sector_hits
    return hits


async def screener_node(state: dict[str, Any]) -> dict[str, Any]:
    """Run the Screener agent and persist the Candidate Universe."""
    from app.integrations.deepseek_client import DeepSeekClient, stubbing_enabled

    run_id = str(state["run_id"])
    theme_config = state["theme_config"]
    sub_exposures = list(theme_config.get("sub_exposures", []))
    retry_count = int(state.get("retry_count", 0))
    max_candidates = MAX_CANDIDATES + 100 * retry_count

    if stubbing_enabled():
        hits = _stub_sub_exposure_hits(sub_exposures)
    else:
        client = DeepSeekClient()
        user_message = (
            f"Theme: {state.get('theme', '')}\n"
            f"Theme definition: {state.get('theme_definition', '')}\n"
            f"Sub-exposures to search (call tools for each): {sub_exposures}\n"
            f"Retry pass (widen if needed): {retry_count}"
        )
        await client.complete_with_tools(
            model="deepseek-v4-pro",
            temperature=0.5,
            system=SCREENER_SYSTEM_PROMPT,
            user_message=user_message,
            tools=SCREENER_TOOLS,
            handlers={
                "search_sector": lambda args: search_sector(str(args["keyword"])),
                "search_holdings": lambda args: search_holdings(
                    str(args["sub_exposure"])
                ),
            },
        )
        hits = {
            sub_exposure: search_holdings(sub_exposure) + search_sector(
                sub_exposure.replace("_", " ").split()[0]
            )
            for sub_exposure in sub_exposures
        }

    candidates, warnings = assemble_candidate_universe(
        hits, max_candidates=max_candidates
    )
    await save_candidates(run_id, candidates)
    logger.info(
        "screener_complete",
        run_id=run_id,
        candidates=len(candidates),
        retry_count=retry_count,
    )
    return {
        "candidates": candidates,
        "warnings": warnings,
        "retry_count": retry_count + 1,
    }
