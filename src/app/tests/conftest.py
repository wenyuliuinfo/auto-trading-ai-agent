"""Shared test fixtures: SQLite database + FastAPI TestClient."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

os.environ.setdefault("STUB_AGENTS", "true")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ["POSTGRES_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient

from app.data.db import configure_database, dispose_db, init_db
from main import app


@pytest.fixture()
def sqlite_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@pytest.fixture()
async def db(sqlite_url: str) -> AsyncIterator[None]:
    configure_database(sqlite_url)
    await init_db()
    yield
    await dispose_db()


@pytest.fixture()
def client(sqlite_url: str) -> Iterator[TestClient]:
    configure_database(sqlite_url)
    with TestClient(app) as test_client:
        yield test_client
