"""
Integration tests for cross-cutting middleware interactions.

Verifies that middleware layers compose correctly — request IDs, security
headers, rate limiting, and error handlers all work together through the
full ASGI stack.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import pytest
from fastapi import Query
from httpx import ASGITransport, AsyncClient

from app import create_app
from app.settings import Settings
from tests.helpers import make_settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_request_id_on_404() -> None:
    """X-Request-ID is present on 404 responses."""
    app = create_app(settings=make_settings(metrics_enabled=False))

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/nonexistent")

    assert response.status_code == 404
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36


@pytest.mark.asyncio
async def test_request_id_on_422() -> None:
    """X-Request-ID is present on validation error responses."""
    settings = make_settings(metrics_enabled=False)
    app = create_app(settings=settings)

    @app.get("/validated")
    async def validated(count: int = Query(..., ge=1)) -> dict[str, int]:
        return {"count": count}

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/validated?count=abc")

    assert response.status_code == 422
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36


@pytest.mark.asyncio
async def test_500_returns_json_error(test_settings: Settings) -> None:
    """Unhandled exceptions return structured JSON, not stack traces."""
    test_settings.debug = False
    app = create_app(settings=test_settings)

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("boom")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/crash")

    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "internal_error"
    assert "boom" not in data["detail"]


@pytest.mark.asyncio
async def test_security_headers_on_429() -> None:
    """Security headers are present on rate-limited responses."""
    settings = make_settings(
        metrics_enabled=False,
        rate_limit_enabled=True,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
    )
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/")
            response = await client.get("/")

    assert response.status_code == 429
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_security_headers_on_504() -> None:
    """Security headers are present on timeout responses."""
    import asyncio

    settings = make_settings(metrics_enabled=False, request_timeout=1)
    app = create_app(settings=settings)

    @app.get("/slow")
    async def slow() -> dict[str, bool]:
        await asyncio.sleep(3)
        return {"done": True}

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/slow")

    assert response.status_code == 504
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_correlation_id_propagated_through_auth_error() -> None:
    """X-Correlation-ID is preserved on authentication failure responses."""
    settings = make_settings(
        metrics_enabled=False,
        auth_enabled=True,
        auth_jwt_secret="super-secret-test-key-for-hs256-123",
        auth_jwt_audience="fastapi-template",
        auth_jwt_issuer="https://issuer.example.com/",
    )
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/me",
                headers={"X-Correlation-ID": "corr-auth-test"},
            )

    assert response.status_code == 401
    assert response.headers["x-correlation-id"] == "corr-auth-test"


@pytest.mark.asyncio
async def test_error_responses_never_contain_query_string() -> None:
    """Error response paths never include the query string."""
    settings = make_settings(metrics_enabled=False)
    app = create_app(settings=settings)

    @app.get("/validated")
    async def validated(count: int = Query(..., ge=1)) -> dict[str, int]:
        return {"count": count}

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            not_found = await client.get("/nope?token=secret")
            validation = await client.get("/validated?count=abc&token=secret")

    assert not_found.status_code == 404
    assert "?" not in not_found.json()["path"]
    assert "secret" not in str(not_found.json())

    assert validation.status_code == 422
    assert "?" not in validation.json()["path"]
    assert "secret" not in str(validation.json())


@pytest.mark.asyncio
async def test_rate_limit_and_security_and_request_id_headers_coexist() -> None:
    """Rate limit headers, security headers, and request ID are all present together."""
    settings = make_settings(
        metrics_enabled=False,
        rate_limit_enabled=True,
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")

    assert response.status_code == 200
    # Rate limit headers
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers
    # Security headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    # Request ID headers
    assert "x-request-id" in response.headers
    assert "x-correlation-id" in response.headers


@pytest.mark.asyncio
async def test_body_size_limit_returns_413() -> None:
    """Oversized requests return 413 through the full stack."""
    settings = make_settings(metrics_enabled=False, max_request_body_bytes=1024)
    app = create_app(settings=settings)

    @app.post("/upload")
    async def upload() -> dict[str, str]:
        return {"status": "ok"}

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/upload", content=b"x" * 2048)

    assert response.status_code == 413
