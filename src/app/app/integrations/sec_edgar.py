"""SEC EDGAR client: business description + segment revenue (Analyst tool)."""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)

EDGAR_HEADERS = {
    "User-Agent": "thematic-basket-research local prototype contact@example.com"
}


def fetch_company_tickers() -> dict[str, str]:
    """Map ticker -> zero-padded CIK from SEC's canonical company list."""
    response = httpx.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=EDGAR_HEADERS,
        timeout=30.0,
    )
    response.raise_for_status()
    rows = response.json()
    result: dict[str, str] = {}
    for _, row in rows.items():
        result[str(row["ticker"]).upper()] = str(row["cik_str"]).zfill(10)
    return result


def fetch_sec_edgar_filing(
    ticker: str, form_types: list[str]
) -> dict[str, Any]:
    """Fetch the latest matching 10-K/10-Q and return business text.

    Returns ``{"item_1_text": str, "segment_revenue": None}``; XBRL
    segment-revenue parsing is intentionally left as a known gap for the
    stub/offline path (ANALYST_SKILL.md Hard Rule 4: missing data is
    null with a reason, never guessed).
    """
    tickers = fetch_company_tickers()
    cik = tickers.get(ticker.upper())
    if not cik:
        raise RuntimeError(f"no CIK found for {ticker}")
    submissions = httpx.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=EDGAR_HEADERS,
        timeout=30.0,
    )
    submissions.raise_for_status()
    data = submissions.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    selected: tuple[str, str, str] | None = None
    for form, accession, document in zip(forms, accessions, documents, strict=False):
        if form in form_types:
            selected = (str(accession), str(document), form)
            break
    if selected is None:
        raise RuntimeError(f"no {form_types} filing found for {ticker}")
    accession, document, form = selected
    accession_clean = accession.replace("-", "")
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{document}"
    )
    filing = httpx.get(url, headers=EDGAR_HEADERS, timeout=60.0)
    filing.raise_for_status()
    text = re.sub(r"<[^>]+>", " ", filing.text)
    text = re.sub(r"\s+", " ", text)
    return {"item_1_text": text[:20000], "segment_revenue": None, "form": form}


def get_business_description(ticker: str) -> dict[str, Any]:
    """Analyst tool: business description + optional segment revenue."""
    settings = get_settings()
    if settings.stub_agents:
        return {
            "business_description": (
                f"{ticker} designs, manufactures, and sells products serving "
                "thematic end markets including electrification, grid "
                "infrastructure, and adjacent digital demand drivers."
            ),
            "segment_revenue": None,
            "form": "stub",
        }
    try:
        filing = fetch_sec_edgar_filing(ticker, form_types=["10-K", "10-Q"])
        return {
            "business_description": filing["item_1_text"],
            "segment_revenue": filing["segment_revenue"],
            "form": filing["form"],
        }
    except Exception as exc:
        logger.warning("sec_edgar_failed", ticker=ticker, error=str(exc))
        return {"business_description": None, "segment_revenue": None, "form": None}


def estimate_revenue_pct_theme(
    segment_revenue: dict[str, float] | None,
    theme_keywords: list[str],
) -> tuple[float | None, str]:
    """Return (pct, method) from disclosed XBRL segments, if mappable."""
    if not segment_revenue:
        return None, "needs_llm_estimate"
    total = sum(segment_revenue.values())
    if total <= 0:
        return None, "needs_llm_estimate"
    matched = sum(
        value
        for segment_name, value in segment_revenue.items()
        if any(keyword.lower() in segment_name.lower() for keyword in theme_keywords)
    )
    if matched == 0:
        return None, "needs_llm_estimate"
    return matched / total, "disclosed"
