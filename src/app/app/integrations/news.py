"""Normalized news across GDELT + SerpApi Google News (Hard Rule 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import httpx

from app.config import get_settings
from app.integrations.gdelt import fetch_gdelt
from app.logging_conf import get_logger

logger = get_logger(__name__)


def _normalize_article(raw: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "headline": raw.get("title") or raw.get("headline") or "",
        "body": raw.get("body") or raw.get("snippet") or "",
        "published_at": raw.get("seendate") or raw.get("date") or raw.get("published_at"),
        "url": raw.get("url") or raw.get("link") or "",
        "source": source,
    }


def _dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for article in articles:
        key = str(article.get("url") or article.get("headline") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(article)
    return unique


def fetch_google_news_serp(ticker: str, lookback_days: int = 90) -> list[dict[str, Any]]:
    """SerpApi Google News: free tier is rate-limited, so use sparingly."""
    settings = get_settings()
    if not settings.serp_api_key:
        return []
    params = {
        "engine": "google_news",
        "q": ticker,
        "api_key": settings.serp_api_key,
        "num": "10",
        "hl": "en",
        "gl": "us",
    }
    try:
        response = httpx.get("https://serpapi.com/search.json", params=params, timeout=30.0)
        response.raise_for_status()
        data = cast(dict[str, Any], response.json())
        return cast(list[dict[str, Any]], data.get("news_results", []))
    except Exception as exc:
        logger.warning("serp_news_failed", ticker=ticker, error=str(exc))
        return []


def _stub_news(ticker: str) -> list[dict[str, Any]]:
    return [
        {
            "headline": f"{ticker} reports continued thematic demand in latest quarter",
            "body": (
                f"Analysts note that {ticker} remains exposed to the theme's "
                "core growth drivers, citing recent product momentum and channel checks."
            ),
            "published_at": datetime.utcnow().isoformat() + "Z",
            "url": f"https://example.invalid/news/{ticker}/1",
            "source": "stub_gdelt",
        },
        {
            "headline": f"Supply chain update for {ticker}",
            "body": (
                f"Industry commentary highlights {ticker}'s positioning across "
                "thematic end markets, with management guiding to stable demand."
            ),
            "published_at": datetime.utcnow().isoformat() + "Z",
            "url": f"https://example.invalid/news/{ticker}/2",
            "source": "stub_google_news",
        },
        {
            "headline": f"Risk watch: {ticker} faces competitive pressure",
            "body": (
                "Competitors continue to invest in adjacent segments, a factor "
                "the analyst desk is tracking for {ticker}."
            ),
            "published_at": datetime.utcnow().isoformat() + "Z",
            "url": f"https://example.invalid/news/{ticker}/3",
            "source": "stub_gdelt",
        },
    ]


def get_news(ticker: str, lookback_days: int = 90) -> list[dict[str, Any]]:
    """Pull and normalize recent news, spreading load across both sources."""
    settings = get_settings()
    if settings.stub_agents:
        return _stub_news(ticker)
    gdelt = [_normalize_article(a, "gdelt") for a in fetch_gdelt(ticker, lookback_days)]
    serp = [
        _normalize_article(a, "google_news")
        for a in fetch_google_news_serp(ticker, lookback_days)
    ]
    return _dedupe_articles(gdelt + serp)
