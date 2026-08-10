"""Run endpoints: trigger, status/progress, SSE events, and final artifacts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import enforce_run_rate_limit
from app.data.queries import (
    count_analyst_reports,
    get_basket_with_scores,
    get_candidates,
    get_rankings,
    get_report,
    get_run,
    get_theme,
    update_run_status,
)
from app.schemas import (
    BasketHolding,
    RankingRow,
    ReportResponse,
    RunResponse,
    RunTriggerResponse,
)
from app.worker import run_pipeline_task

router = APIRouter(tags=["runs"])


@router.post(
    "/themes/{theme_id}/runs",
    response_model=RunTriggerResponse,
    status_code=202,
    dependencies=[Depends(enforce_run_rate_limit)],
)
async def trigger_run(theme_id: str) -> RunTriggerResponse:
    """Enqueue a pipeline run and return immediately (never run synchronously)."""
    theme = await get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    run = await create_run_row(theme_id)
    try:
        run_pipeline_task.delay(str(run["run_id"]))
    except Exception as exc:
        await update_run_status(str(run["run_id"]), "failed", error_detail=str(exc))
        raise HTTPException(
            status_code=503, detail="run queue unavailable; try again shortly"
        ) from exc
    return RunTriggerResponse(run_id=str(run["run_id"]))


async def create_run_row(theme_id: str) -> dict[str, object]:
    from app.data.queries import create_run

    return await create_run(theme_id)


async def _progress(run_id: str) -> dict[str, int]:
    return {
        "analyzed": await count_analyst_reports(run_id),
        "total": len(await get_candidates(run_id)),
    }


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run_status(run_id: str) -> RunResponse:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    response = RunResponse.model_validate({**run, "progress": await _progress(run_id)})
    return response


@router.get("/runs/{run_id}/basket", response_model=list[BasketHolding])
async def get_basket(run_id: str) -> list[BasketHolding]:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows = await get_basket_with_scores(run_id)
    if not rows and run["status"] != "complete":
        raise HTTPException(status_code=404, detail="basket not ready")
    return [BasketHolding.model_validate(row) for row in rows]


@router.get("/runs/{run_id}/rankings", response_model=list[RankingRow])
async def get_rankings_endpoint(run_id: str) -> list[RankingRow]:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows = await get_rankings(run_id)
    if not rows:
        raise HTTPException(status_code=404, detail="rankings not ready")
    return [RankingRow.model_validate(row) for row in rows]


@router.get("/runs/{run_id}/report", response_model=ReportResponse)
async def get_report_endpoint(run_id: str) -> ReportResponse:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    report_md = await get_report(run_id)
    if report_md is None:
        raise HTTPException(status_code=404, detail="report not ready")
    return ReportResponse(
        run_id=run_id,
        report_md=report_md,
        disclaimer="not investment advice, for research purposes only",
    )


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str) -> StreamingResponse:
    """SSE progress stream for live UI updates."""

    async def event_generator() -> AsyncIterator[str]:
        while True:
            run = await get_run(run_id)
            if run is None:
                yield "event: error\ndata: {\"detail\": \"run not found\"}\n\n"
                break
            payload = json.dumps(
                {
                    "status": run["status"],
                    "progress": await _progress(run_id),
                    "error_detail": run["error_detail"],
                }
            )
            yield f"event: progress\ndata: {payload}\n\n"
            if run["status"] in {"complete", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
