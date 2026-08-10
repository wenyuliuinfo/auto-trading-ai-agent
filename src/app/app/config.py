"""Application settings and config-file loading.

All secrets and runtime knobs come from environment variables via
pydantic-settings (CONVENTIONS.md §3.1). Config YAML files under
``config/`` are data, not settings: they are loaded explicitly by the
code that owns them (e.g. factor weights at theme-creation time).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_repo_root() -> Path:
    """Locate the repo root that owns ``config/factor_weights.yaml``."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "config" / "factor_weights.yaml").is_file():
            return candidate
    raise RuntimeError("could not locate config/factor_weights.yaml")


REPO_ROOT = _find_repo_root()
CONFIG_DIR = REPO_ROOT / "config"


class Settings(BaseSettings):
    """Environment-driven settings. Never read ``os.environ`` directly elsewhere."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Domain Postgres (system of record + LangGraph checkpoints).
    postgres_database_url: str | None = None

    # Postgres connection pool sizing. Analyst fan-out can open many
    # concurrent sessions in one run, so the SQLAlchemy default 5+10 pool
    # is too small and causes QueuePool timeouts under parallel branches.
    database_pool_size: int = 20
    database_pool_max_overflow: int = 40
    database_pool_timeout: int = 60

    # Redis-backed Celery broker.
    redis_url: str = "redis://localhost:6379/0"

    # Backend base URL, used for self-referencing links.
    api_url: str = "http://localhost:8000"

    # LLM provider.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Free-tier data vendors.
    fmp_api_key: str = ""
    finnhub_api_key: str = ""
    serp_api_key: str = ""

    # Pinecone (local container or managed).
    pinecone_api_key: str = ""
    pinecone_host_url: str = "http://localhost:5080"
    pinecone_index_name: str = "vector_store"

    # Langfuse (write-side SDK + read-side query client).
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # Deterministic local stubs. When true, agent nodes and data clients
    # return canned outputs so the full pipeline can be exercised without
    # network access or API spend.
    stub_agents: bool = False

    # Optional live reference-universe source (e.g. a CSV URL). When
    # empty, integrations/reference_universe.py falls back to the bundled
    # seed file.
    reference_universe_url: str = ""

    # API-layer rate limit for run triggers (ARCHITECTURE.md §9).
    rate_limit_runs_per_minute: int = 5

    @property
    def effective_database_url(self) -> str:
        if not self.postgres_database_url:
            raise RuntimeError("POSTGRES_DATABASE_URL is not configured")
        return self.postgres_database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=8)
def load_yaml(filename: str) -> dict[str, Any]:
    """Load one YAML file from ``config/`` as a dict.

    Used for the factor-weights policy file and the sub-exposure -> ETF
    mapping. Callers own interpretation of the contents.
    """
    path = CONFIG_DIR / filename
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"config/{filename} must contain a YAML mapping")
    return loaded


@lru_cache(maxsize=1)
def load_factor_weights() -> dict[str, float]:
    """Load the global factor weighting policy.

    This is the single place the YAML is read; POST /themes copies the
    result verbatim into a theme's persisted config (ARCHITECTURE.md
    §2.1, MODELING_SKILL.md Hard Rule 2).
    """
    raw = load_yaml("factor_weights.yaml")
    weights = {
        k: float(v) for k, v in raw.items() if isinstance(v, int | float)
    }
    if len(weights) != len(raw):
        raise ValueError("config/factor_weights.yaml contains non-numeric entries")
    return weights


@lru_cache(maxsize=1)
def load_sub_exposure_etf_map() -> dict[str, list[str]]:
    """Load the curated sub-exposure -> ETF ticker mapping."""
    raw = load_yaml("sub_exposure_etf_map.yaml")
    return {k: list(v) for k, v in raw.items() if isinstance(v, list)}


def asyncpg_url_to_dsn(url: str) -> str:
    """Convert an SQLAlchemy asyncpg URL to a plain psycopg DSN.

    ``AsyncPostgresSaver`` expects ``postgresql://``, not the
    ``postgresql+asyncpg://`` dialect prefix used by SQLAlchemy.
    """
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    return url
