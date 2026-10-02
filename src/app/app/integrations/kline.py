"""K-line snapshot integration for the report holdings chart.

The Node bridge runs ``tools/stock-sdk-kline/fetch_klines.mjs``; this module
owns validation, normalization, flags, and the deterministic stub path. It
never calls an LLM and never fails a run on per-ticker errors.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any

import pandas as pd

from app.config import get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)

KLINE_BARS = 126
KLINE_FETCH_BARS = 140
KLINE_MIN_BARS_CHART = 20
KLINE_MIN_BARS_RETURN = 120
KLINE_STALE_DAYS = 7
KLINE_TIMEOUT_TOTAL_S = 60
KLINE_MAX_OUTPUT_BYTES = 5_000_000
SUSPECT_ADJUSTMENT_MOVE = 0.35

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,6}([.\-][A-Z]{1,2})?$")


@dataclass
class KlineBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class KlineSnapshot:
    ticker: str
    status: str
    source: str
    sdk_version: str | None
    adjust: str
    as_of: str | None = None
    bars: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    error_code: str | None = None


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_bar(raw: dict[str, Any]) -> bool:
    o = _to_float(raw.get("open"))
    h = _to_float(raw.get("high"))
    low = _to_float(raw.get("low"))
    c = _to_float(raw.get("close"))
    if o is None or h is None or low is None or c is None:
        return False
    if o <= 0 or h <= 0 or low <= 0 or c <= 0:
        return False
    return h >= max(o, c) and low <= min(o, c)


def _normalize_bars(raw_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for raw in raw_bars:
        if not isinstance(raw, dict) or not _valid_bar(raw):
            continue
        date_value = str(raw.get("date", "")).strip()
        if not date_value:
            continue
        cleaned.append(
            {
                "date": date_value,
                "open": float(raw["open"]),
                "high": float(raw["high"]),
                "low": float(raw["low"]),
                "close": float(raw["close"]),
                "volume": float(raw.get("volume", 0.0) or 0.0),
            }
        )
    cleaned.sort(key=lambda bar: bar["date"])
    deduped: dict[str, dict[str, Any]] = {}
    for bar in cleaned:
        deduped[bar["date"]] = bar
    return list(deduped.values())[-KLINE_BARS:]


def _snapshot_flags(
    bars: list[dict[str, Any]], status: str
) -> list[str]:
    if status != "ok" or not bars:
        return []
    flags: list[str] = []
    last_date = datetime.fromisoformat(bars[-1]["date"][:10]).date()
    if (date.today() - last_date).days > KLINE_STALE_DAYS:
        flags.append("stale")
    if len(bars) < KLINE_BARS:
        flags.append("short_history")
    for previous, current in pairwise(bars):
        previous_close = float(previous["close"])
        current_close = float(current["close"])
        if previous_close > 0:
            move = abs(current_close / previous_close - 1)
            if move >= SUSPECT_ADJUSTMENT_MOVE:
                flags.append("suspect_adjustment")
                break
    return flags


def _snapshot_from_bridge(
    ticker: str, raw: dict[str, Any], adjust: str, sdk_version: str | None
) -> KlineSnapshot:
    if raw.get("status") == "error":
        return KlineSnapshot(
            ticker=ticker,
            status="unavailable",
            source="stock-sdk",
            sdk_version=sdk_version,
            adjust=adjust,
            error_code=str(raw.get("code") or "NO_DATA"),
        )
    bars = _normalize_bars(list(raw.get("bars") or []))
    if len(bars) < KLINE_MIN_BARS_CHART:
        return KlineSnapshot(
            ticker=ticker,
            status="insufficient",
            source="stock-sdk",
            sdk_version=sdk_version,
            adjust=adjust,
            bars=bars,
            flags=[],
            error_code="INSUFFICIENT_HISTORY",
        )
    return KlineSnapshot(
        ticker=ticker,
        status="ok",
        source="stock-sdk",
        sdk_version=sdk_version,
        adjust=adjust,
        as_of=bars[-1]["date"][:10],
        bars=bars,
        flags=_snapshot_flags(bars, "ok"),
    )


def _stub_bars(ticker: str) -> list[dict[str, Any]]:
    rng = random.Random(ticker)
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    dates = pd.bdate_range(end=end - timedelta(days=KLINE_BARS - 1), periods=KLINE_BARS)
    price = 50.0 + (sum(ord(ch) for ch in ticker) % 100)
    bars: list[dict[str, Any]] = []
    for day in dates:
        change = rng.uniform(-0.03, 0.03)
        previous_close = price
        close = max(1.0, previous_close * (1 + change))
        open_price = previous_close
        high = max(open_price, close) * (1 + rng.uniform(0.0, 0.01))
        low = min(open_price, close) * (1 - rng.uniform(0.0, 0.01))
        bars.append(
            {
                "date": day.date().isoformat(),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": float(rng.randint(1_000_000, 20_000_000)),
            }
        )
        price = close
    return bars


async def fetch_klines(tickers: list[str]) -> dict[str, KlineSnapshot]:
    settings = get_settings()
    valid = [ticker for ticker in tickers if SYMBOL_PATTERN.fullmatch(ticker)]
    invalid = [ticker for ticker in tickers if ticker not in valid]
    if settings.stub_agents:
        snapshots = {
            ticker: KlineSnapshot(
                ticker=ticker,
                status="ok",
                source="stub",
                sdk_version=None,
                adjust="none",
                as_of=_stub_bars(ticker)[-1]["date"],
                bars=_stub_bars(ticker),
                flags=[],
            )
            for ticker in valid
        }
    elif not settings.kline_enabled:
        snapshots = {
            ticker: KlineSnapshot(
                ticker=ticker,
                status="unavailable",
                source="stock-sdk",
                sdk_version=None,
                adjust="none",
                error_code="DISABLED",
            )
            for ticker in valid
        }
    else:
        snapshots = await _run_bridge(valid, settings)
    for ticker in invalid:
        snapshots[ticker] = KlineSnapshot(
            ticker=ticker,
            status="unavailable",
            source="stock-sdk",
            sdk_version=None,
            adjust="none",
            error_code="INVALID_SYMBOL",
        )
    return snapshots


async def _run_bridge(
    tickers: list[str], settings: Any
) -> dict[str, KlineSnapshot]:
    script = settings.kline_script_path
    if not script:
        return {
            ticker: KlineSnapshot(
                ticker=ticker,
                status="unavailable",
                source="stock-sdk",
                sdk_version=None,
                adjust="none",
                error_code="BRIDGE_FAILED",
            )
            for ticker in tickers
        }
    request = {
        "version": 1,
        "symbols": tickers,
        "bars": KLINE_FETCH_BARS,
        "adjust": "forward",
    }
    process = await asyncio.create_subprocess_exec(
        settings.kline_node_bin,
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(request).encode()),
            timeout=settings.kline_timeout_s,
        )
    except TimeoutError:
        process.kill()
        logger.warning("kline_bridge_timeout")
        return _all_bridge_failed(tickers)
    if process.returncode != 0:
        logger.warning(
            "kline_bridge_failed",
            returncode=process.returncode,
            stderr=stderr.decode(errors="replace")[:500],
        )
        return _all_bridge_failed(tickers)
    if len(stdout) > KLINE_MAX_OUTPUT_BYTES:
        logger.warning("kline_bridge_output_too_large")
        return _all_bridge_failed(tickers)
    try:
        payload = json.loads(stdout.decode())
    except json.JSONDecodeError:
        logger.warning("kline_bridge_invalid_json")
        return _all_bridge_failed(tickers)
    sdk_version = payload.get("sdk_version")
    results = payload.get("results", {})
    return {
        ticker: _snapshot_from_bridge(ticker, results.get(ticker, {}), "forward", sdk_version)
        for ticker in tickers
    }


def _all_bridge_failed(tickers: list[str]) -> dict[str, KlineSnapshot]:
    return {
        ticker: KlineSnapshot(
            ticker=ticker,
            status="unavailable",
            source="stock-sdk",
            sdk_version=None,
            adjust="forward",
            error_code="BRIDGE_FAILED",
        )
        for ticker in tickers
    }


def snapshot_to_dict(snapshot: KlineSnapshot) -> dict[str, Any]:
    return asdict(snapshot)
