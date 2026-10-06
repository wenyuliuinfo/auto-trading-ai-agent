"""Backtest trigger, status, trades, and export endpoints."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response

from app.agents.backtest import (
    build_current_holdings,
    config_hash,
    load_backtest_config,
)
from app.data.queries import (
    create_backtest_run,
    get_active_backtest,
    get_backtest_artifacts,
    get_backtest_trades_page,
    get_latest_backtest,
    get_run,
    update_backtest_status,
)
from app.schemas import BacktestTriggerRequest, BacktestTriggerResponse
from app.worker import backtest_pipeline_task

router = APIRouter(tags=["backtests"])


def _disabled_payload(run_id: str, mode: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": mode,
        "status": "disabled",
        "disclaimer": load_backtest_config().get("disclaimer"),
    }


def _not_run_payload(run_id: str, mode: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": mode,
        "status": "not_run",
        "disclaimer": load_backtest_config().get("disclaimer"),
    }


async def _full_payload(run_id: str, mode: str, latest: dict[str, Any]) -> dict[str, Any]:
    artifacts = await get_backtest_artifacts(latest["backtest_id"])
    cfg = load_backtest_config()
    return {
        **latest,
        "series": artifacts["series"],
        "rebalances": artifacts["rebalances"],
        "trades": artifacts["trades"],
        "current_holdings": await build_current_holdings(run_id),
        "disclaimer": cfg.get("disclaimer"),
    }


@router.post(
    "/runs/{run_id}/backtest",
    response_model=BacktestTriggerResponse,
    status_code=202,
)
async def trigger_backtest(
    run_id: str, payload: BacktestTriggerRequest
) -> BacktestTriggerResponse:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    cfg = load_backtest_config()
    mode_cfg = cfg.get("modes", {}).get(payload.mode, {})
    if not bool(mode_cfg.get("enabled", False)):
        raise HTTPException(status_code=409, detail=f"backtest mode '{payload.mode}' is disabled")

    active = await get_active_backtest(run_id, payload.mode)
    if active is not None:
        return BacktestTriggerResponse(
            backtest_id=active["backtest_id"],
            run_id=run_id,
            mode=payload.mode,
            status="queued",
        )

    snapshot = cfg
    row = await create_backtest_run(
        run_id,
        payload.mode,
        snapshot,
        config_hash(snapshot),
        status="queued",
    )
    try:
        backtest_pipeline_task.delay(
            str(row["backtest_id"]), run_id, payload.mode
        )
    except Exception as exc:
        await update_backtest_status(
            str(row["backtest_id"]), "failed", "QUEUE_UNAVAILABLE", str(exc)
        )
        raise HTTPException(
            status_code=503, detail="backtest queue unavailable; try again shortly"
        ) from exc
    return BacktestTriggerResponse(
        backtest_id=str(row["backtest_id"]),
        run_id=run_id,
        mode=payload.mode,
    )


@router.get("/runs/{run_id}/backtest")
async def get_backtest(
    run_id: str, mode: Literal["trailing", "full"] = Query("trailing")
) -> dict[str, Any]:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    cfg = load_backtest_config()
    mode_cfg = cfg.get("modes", {}).get(mode, {})
    if not bool(mode_cfg.get("enabled", False)):
        return _disabled_payload(run_id, mode)
    latest = await get_latest_backtest(run_id, mode)
    if latest is None:
        return _not_run_payload(run_id, mode)
    return await _full_payload(run_id, mode, latest)


@router.get("/runs/{run_id}/backtest/trades")
async def get_backtest_trades(
    run_id: str,
    mode: Literal["trailing", "full"] = Query("trailing"),
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    latest = await get_latest_backtest(run_id, mode)
    if latest is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    rows, total = await get_backtest_trades_page(latest["backtest_id"], limit, offset)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def _neutralize(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value


@router.get("/runs/{run_id}/backtest/export")
async def export_backtest(
    run_id: str,
    mode: Literal["trailing", "full"] = Query("trailing"),
    format: Literal["csv", "json"] = Query("json"),
    part: Literal["equity", "trades", "rebalances"] = Query("equity"),
) -> Response:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    latest = await get_latest_backtest(run_id, mode)
    if latest is None:
        raise HTTPException(status_code=404, detail="backtest not ready")
    payload = await _full_payload(run_id, mode, latest)

    if format == "json":
        return Response(
            content=json.dumps(payload, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="backtest-{mode}.json"'},
        )

    if part == "equity":
        series = payload.get("series", {})
        dates = sorted(
            {
                point["date"]
                for points in series.values()
                for point in points
            }
        )
        rows = [
            {
                "date": day,
                **{
                    name: next(
                        (point["value"] for point in points if point["date"] == day),
                        "",
                    )
                    for name, points in series.items()
                },
            }
            for day in dates
        ]
    elif part == "rebalances":
        rows = [
            {
                "idx": item["idx"],
                "signal_date": item["signal_date"],
                "exec_date": item["exec_date"],
                "hold_end_date": item["hold_end_date"],
                "ticker": holding.get("ticker", ""),
                "weight": holding.get("weight", ""),
            }
            for item in payload.get("rebalances", [])
            for holding in item.get("basket", [])
        ]
    else:
        rows = payload.get("trades", [])

    if not rows:
        return Response(content="", media_type="text/csv")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _neutralize(value) for key, value in row.items()})
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="backtest-{part}.csv"'},
    )
