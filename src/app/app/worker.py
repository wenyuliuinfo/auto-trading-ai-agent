"""Celery app + task definitions (enqueue-not-execute boundary)."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

from celery import Celery

from app.agents.backtest import execute_backtest
from app.agents.graph import execute_run
from app.config import get_settings
from app.data.db import dispose_db

settings = get_settings()

celery_app = Celery(
    "auto_trading_ai_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true",
    task_eager_propagates=True,
    task_routes={
        "backtest_pipeline_task": {
            "queue": os.getenv("BACKTEST_QUEUE", "celery")
        },
    },
)


async def _run_with_dispose(run_id: str) -> None:
    """Run one pipeline and release its event-loop-bound DB connections."""
    try:
        await execute_run(run_id)
    finally:
        await dispose_db()


@celery_app.task(  # type: ignore[misc]  # celery has no type stubs
    name="run_pipeline_task", bind=True, max_retries=3
)
def run_pipeline_task(self: Any, run_id: str) -> None:
    """Execute one Run's LangGraph pipeline (Celery is the sync entry point)."""
    try:
        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False
        if loop_running:
            # Celery eager mode called from inside a running event loop
            # (e.g. TestClient): run the pipeline on a worker thread instead
            # of nesting asyncio.run inside the active loop.
            errors: list[BaseException] = []

            def runner() -> None:
                try:
                    asyncio.run(_run_with_dispose(run_id))
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=runner, daemon=True)
            thread.start()
            thread.join()
            if errors:
                raise errors[0]
        else:
            asyncio.run(_run_with_dispose(run_id))
    except Exception as exc:
        raise self.retry(
            exc=exc, countdown=2 ** (self.request.retries * 2)
        ) from exc


async def _run_backtest_with_dispose(backtest_id: str, run_id: str, mode: str) -> None:
    try:
        await execute_backtest(backtest_id, run_id, mode)
    finally:
        await dispose_db()


@celery_app.task(  # type: ignore[misc]  # celery has no type stubs
    name="backtest_pipeline_task", bind=True, max_retries=2
)
def backtest_pipeline_task(
    self: Any, backtest_id: str, run_id: str, mode: str
) -> None:
    """Execute one Backtest job on the dedicated ``backtest`` queue."""
    try:
        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False
        if loop_running:
            errors: list[BaseException] = []

            def runner() -> None:
                try:
                    asyncio.run(_run_backtest_with_dispose(backtest_id, run_id, mode))
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=runner, daemon=True)
            thread.start()
            thread.join()
            if errors:
                raise errors[0]
        else:
            asyncio.run(_run_backtest_with_dispose(backtest_id, run_id, mode))
    except Exception as exc:
        raise self.retry(
            exc=exc, countdown=2 ** (self.request.retries * 2)
        ) from exc
