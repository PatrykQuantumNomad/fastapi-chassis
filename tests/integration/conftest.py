"""
Integration test fixtures.

Provides fully-configured application instances and HTTP clients
that exercise the complete ASGI stack.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import create_app
from app.settings import Settings
from tests.helpers import make_settings


def _postgres_url() -> str | None:
    """Return the Postgres async URL from env, or None if unavailable."""
    return os.environ.get("TEST_POSTGRES_URL")


def _postgres_alembic_url() -> str | None:
    """Return the Postgres sync (Alembic) URL from env, or None if unavailable."""
    return os.environ.get("TEST_POSTGRES_ALEMBIC_URL")


def _redis_url() -> str | None:
    """Return the Redis URL from env, or None if unavailable."""
    return os.environ.get("TEST_REDIS_URL")


requires_postgres = pytest.mark.skipif(
    not _postgres_url(),
    reason="TEST_POSTGRES_URL not set (Postgres service unavailable)",
)

requires_redis = pytest.mark.skipif(
    not _redis_url(),
    reason="TEST_REDIS_URL not set (Redis service unavailable)",
)


@pytest.fixture
def test_settings() -> Settings:
    """Settings tuned for fast, isolated test runs."""
    return make_settings(
        app_name="Test App",
        app_version="0.0.1-test",
        debug=True,
        docs_enabled=True,
        redoc_enabled=True,
        openapi_enabled=True,
        log_level="DEBUG",
        metrics_enabled=False,
        readiness_include_details=True,
        info_endpoint_enabled=True,
        endpoints_listing_enabled=True,
        request_timeout=5,
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """A fully-configured test application."""
    return create_app(settings=test_settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to the ASGI app (no real network)."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def app_with_metrics() -> FastAPI:
    """Application with Prometheus metrics enabled."""
    settings = make_settings(
        app_name="Metrics Test App",
        app_version="0.0.1-test",
        debug=True,
        docs_enabled=True,
        redoc_enabled=True,
        openapi_enabled=True,
        log_level="WARNING",
        metrics_enabled=True,
        readiness_include_details=True,
        info_endpoint_enabled=True,
        endpoints_listing_enabled=True,
        request_timeout=5,
    )
    return create_app(settings=settings)


@pytest.fixture
async def client_with_metrics(app_with_metrics: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app_with_metrics.router.lifespan_context(app_with_metrics):
        transport = ASGITransport(app=app_with_metrics)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def slow_app() -> FastAPI:
    """App with a 1-second timeout for testing 504 responses."""
    from fastapi.responses import JSONResponse

    settings = make_settings(
        app_name="Slow Test App",
        app_version="0.0.1-test",
        debug=True,
        docs_enabled=True,
        redoc_enabled=True,
        openapi_enabled=True,
        log_level="WARNING",
        metrics_enabled=False,
        readiness_include_details=True,
        info_endpoint_enabled=True,
        endpoints_listing_enabled=True,
        request_timeout=1,
    )
    _app = create_app(settings=settings)

    @_app.get("/slow")
    async def slow_endpoint() -> JSONResponse:
        await asyncio.sleep(3)
        return JSONResponse(content={"done": True})

    return _app


@pytest.fixture
async def slow_client(slow_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with slow_app.router.lifespan_context(slow_app):
        transport = ASGITransport(app=slow_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def postgres_app() -> FastAPI | None:
    """App wired to a real Postgres database (skipped when unavailable)."""
    url = _postgres_url()
    alembic_url = _postgres_alembic_url()
    if not url or not alembic_url:
        return None
    settings = make_settings(
        app_name="Postgres Test App",
        app_version="0.0.1-test",
        debug=True,
        docs_enabled=True,
        redoc_enabled=True,
        openapi_enabled=True,
        log_level="WARNING",
        metrics_enabled=False,
        readiness_include_details=True,
        database_backend="custom",
        database_url=url,
        alembic_database_url=alembic_url,
        request_timeout=10,
    )
    return create_app(settings=settings)


@pytest.fixture
async def postgres_client(postgres_app: FastAPI | None) -> AsyncIterator[AsyncClient]:
    if postgres_app is None:
        pytest.skip("Postgres app not available")
    async with postgres_app.router.lifespan_context(postgres_app):
        transport = ASGITransport(app=postgres_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def redis_rate_limit_app() -> FastAPI | None:
    """App wired to a real Redis for rate limiting (skipped when unavailable)."""
    url = _redis_url()
    if not url:
        return None
    settings = make_settings(
        app_name="Redis RL Test App",
        app_version="0.0.1-test",
        debug=True,
        docs_enabled=True,
        redoc_enabled=True,
        openapi_enabled=True,
        log_level="WARNING",
        metrics_enabled=False,
        readiness_include_details=True,
        rate_limit_enabled=True,
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
        rate_limit_storage_backend="redis",
        rate_limit_storage_url=url,
        request_timeout=10,
    )
    return create_app(settings=settings)


@pytest.fixture
async def redis_client(redis_rate_limit_app: FastAPI | None) -> AsyncIterator[AsyncClient]:
    if redis_rate_limit_app is None:
        pytest.skip("Redis app not available")
    async with redis_rate_limit_app.router.lifespan_context(redis_rate_limit_app):
        transport = ASGITransport(app=redis_rate_limit_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
