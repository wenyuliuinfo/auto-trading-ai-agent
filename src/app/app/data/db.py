"""Async SQLAlchemy engine/session plumbing.

Production uses Postgres (asyncpg); tests can point the same code at
in-memory SQLite via ``configure_database``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.config import get_settings
from app.data.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_configured_url: str | None = None


def configure_database(url: str | None = None) -> None:
    """(Re)create the engine, used by tests to point at SQLite."""
    global _engine, _sessionmaker, _configured_url
    target = url or _configured_url or get_settings().effective_database_url
    _configured_url = target
    kwargs: dict[str, Any] = {}
    if target.startswith("sqlite"):
        kwargs["poolclass"] = StaticPool if ":memory:" in target else NullPool
    else:
        settings = get_settings()
        kwargs["pool_size"] = settings.database_pool_size
        kwargs["max_overflow"] = settings.database_pool_max_overflow
        kwargs["pool_timeout"] = settings.database_pool_timeout
    _engine = create_async_engine(target, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure_database()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session; commit is the caller's responsibility."""
    async with get_sessionmaker()() as session:
        yield session


async def init_db() -> None:
    """Create tables if missing (idempotent)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    # Drop the globals so the next event loop builds a fresh engine against
    # the same URL. The Celery worker runs each task under its own
    # asyncio.run loop; keeping a pooled engine across loops makes asyncpg
    # hand connections bound to a previous loop back to the new one ("Future
    # attached to a different loop").
    _engine = None
    _sessionmaker = None
