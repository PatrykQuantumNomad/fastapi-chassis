"""
Integration tests for the cache layer through the full ASGI stack.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import create_app
from tests.helpers import make_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def cache_settings() -> object:
    return make_settings(
        app_name="Cache Test",
        debug=True,
        docs_enabled=True,
        log_level="DEBUG",
        metrics_enabled=False,
        cache_enabled=True,
        cache_backend="memory",
        cache_default_ttl_seconds=60,
    )


@pytest.fixture
def cache_app(cache_settings: object) -> FastAPI:
    return create_app(settings=cache_settings)  # type: ignore[arg-type]


@pytest.fixture
async def cache_client(cache_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with cache_app.router.lifespan_context(cache_app):
        transport = ASGITransport(app=cache_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestCacheIntegration:
    """Full-stack tests for the cache layer."""

    @pytest.mark.asyncio
    async def test_cached_time_returns_live_then_cache(self, cache_client: AsyncClient) -> None:
        first = await cache_client.get("/api/v1/cached-time")
        assert first.status_code == 200
        assert first.json()["source"] == "live"

        second = await cache_client.get("/api/v1/cached-time")
        assert second.status_code == 200
        assert second.json()["source"] == "cache"
        assert second.json()["time"] == first.json()["time"]

    @pytest.mark.asyncio
    async def test_readiness_includes_cache_check(self, cache_client: AsyncClient) -> None:
        response = await cache_client.get("/ready")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cached_time_disabled_returns_live(self) -> None:
        """When cache is disabled the endpoint falls back to live response."""
        settings = make_settings(
            app_name="No Cache",
            debug=True,
            metrics_enabled=False,
            cache_enabled=False,
        )
        app = create_app(settings=settings)
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/cached-time")

        assert response.status_code == 200
        assert response.json()["cache"] == "disabled"
        assert response.json()["source"] == "live"
