"""FastAPI entry point (``uvicorn main:app``)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.runs import router as runs_router
from app.api.themes import router as themes_router
from app.data.db import dispose_db, init_db
from app.logging_conf import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Any:
    configure_logging()
    await init_db()
    yield
    await dispose_db()


app = FastAPI(
    title="Auto Trading AI Agent API",
    description="Thematic basket research pipeline (research only, not investment advice)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(themes_router)
app.include_router(runs_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
