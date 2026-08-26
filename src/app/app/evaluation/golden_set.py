"""Golden-set checks (ARCHITECTURE.md §8.B).

These compare already-persisted Runs against curated theme mappings and
ETF holdings; they are never called from api/ or agents/ and never block
a Run's completion.
"""

from __future__ import annotations

from typing import Any

from app.config import load_sub_exposure_etf_map
from app.data.queries import get_candidates, get_run, get_theme
from app.integrations.etf_holdings import fetch_etf_holdings

GOLDEN_SET_TOP_N = 15
MIN_COVERAGE_RATIO = 0.5


def _expected_tickers(sub_exposure: str) -> list[str]:
    """Top holdings across the ETFs mapped to a sub-exposure, deduplicated."""
    expected: list[str] = []
    seen: set[str] = set()
    for etf_ticker in load_sub_exposure_etf_map().get(sub_exposure, []):
        holdings = fetch_etf_holdings(etf_ticker).head(GOLDEN_SET_TOP_N)
        for record in holdings.to_dict("records"):
            ticker = str(record["ticker"]).upper()
            if ticker not in seen:
                seen.add(ticker)
                expected.append(ticker)
    return expected


async def check_candidate_coverage(run_id: str) -> list[dict[str, Any]]:
    """Flag sub-exposures whose Candidate Universe misses known ETF names."""
    run = await get_run(run_id)
    if run is None:
        return [{"run_id": run_id, "reason": "no run persisted for run"}]
    theme = await get_theme(str(run["theme_id"]))
    if theme is None:
        return [{"run_id": run_id, "reason": "no theme persisted for run"}]

    sub_exposures = list((theme["config"] or {}).get("sub_exposures", []))
    candidate_tickers = {
        str(row["ticker"]).upper() for row in await get_candidates(run_id)
    }
    flags: list[dict[str, Any]] = []
    for sub_exposure in sub_exposures:
        expected = _expected_tickers(sub_exposure)
        if not expected:
            flags.append(
                {
                    "sub_exposure": sub_exposure,
                    "reason": "no mapped ETF holdings available",
                }
            )
            continue
        covered = [ticker for ticker in expected if ticker in candidate_tickers]
        coverage_ratio = len(covered) / len(expected)
        if coverage_ratio >= MIN_COVERAGE_RATIO:
            continue
        flags.append(
            {
                "sub_exposure": sub_exposure,
                "coverage_ratio": coverage_ratio,
                "covered_tickers": covered,
                "missing_tickers": [
                    ticker for ticker in expected if ticker not in candidate_tickers
                ],
                "reason": (
                    f"candidate coverage {coverage_ratio:.0%} below "
                    f"{MIN_COVERAGE_RATIO:.0%} of mapped ETF top holdings"
                ),
            }
        )
    return flags
