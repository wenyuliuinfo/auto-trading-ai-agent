"""Server-rendered mini candlestick SVG for stored K-line snapshots."""

from __future__ import annotations

from typing import Any


def _aggregate_weekly(bars: list[dict[str, Any]]) -> list[dict[str, float]]:
    weeks: dict[str, dict[str, float]] = {}
    for bar in bars:
        week = str(bar.get("date"))[:10]
        # ISO week is enough for chart grouping; date prefix keeps the bucket stable.
        bucket = week[:4] + "-W" + week[5:7]
        if bucket not in weeks:
            weeks[bucket] = {
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
            }
            continue
        current = weeks[bucket]
        current["high"] = max(current["high"], float(bar["high"]))
        current["low"] = min(current["low"], float(bar["low"]))
        current["close"] = float(bar["close"])
    return list(weeks.values())


def render_kline_svg(bars: list[dict[str, Any]]) -> str:
    weekly = _aggregate_weekly(bars)
    if not weekly:
        return ""
    width = 160
    height = 48
    pad = 2.0
    values = [
        value
        for candle in weekly
        for value in (candle["high"], candle["low"])
    ]
    low = min(values)
    high = max(values)
    span = high - low or 1.0
    step = (width - pad * 2) / max(len(weekly), 1)
    candle_width = max(1.0, step * 0.55)

    rects: list[str] = []
    for index, candle in enumerate(weekly):
        x = pad + index * step + (step - candle_width) / 2
        up = candle["close"] >= candle["open"]
        color = "#22c55e" if up else "#ef4444"
        body_top = height - pad - (
            (max(candle["open"], candle["close"]) - low) / span * (height - pad * 2)
        )
        body_bottom = height - pad - (
            (min(candle["open"], candle["close"]) - low) / span * (height - pad * 2)
        )
        body_height = max(0.5, body_bottom - body_top)
        wick_x = x + candle_width / 2
        wick_top = height - pad - ((candle["high"] - low) / span * (height - pad * 2))
        wick_bottom = height - pad - ((candle["low"] - low) / span * (height - pad * 2))
        rects.append(
            f'<line x1="{wick_x:.1f}" y1="{wick_top:.1f}" '
            f'x2="{wick_x:.1f}" y2="{wick_bottom:.1f}" stroke="{color}" stroke-width="1"/>'
        )
        rects.append(
            f'<rect x="{x:.1f}" y="{body_top:.1f}" width="{candle_width:.1f}" '
            f'height="{body_height:.1f}" fill="{color}"/>'
        )
    first = bars[0]["close"]
    last = bars[-1]["close"]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="48" '
        'viewBox="0 0 160 48" role="img">'
        f"<title>start close {float(first):.2f}, end close {float(last):.2f}</title>"
        + "".join(rects)
        + "</svg>"
    )
