"""
Integration tests for the FastAPI application.

These tests exercise the full application stack — factory, builder,
middleware, error handlers, and routes — through ASGI HTTP requests.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app import create_app
from app.auth.service import build_test_jwt
from app.settings import Settings
from tests.helpers import make_settings

from .conftest import requires_postgres, requires_redis

pytestmark = pytest.mark.integration


# ──────────────────────────────────────────────
# Health Check Tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Liveness endpoint returns 200 with healthy status."""
    response = await client.get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_readiness_check(client: AsyncClient) -> None:
    """Readiness endpoint returns 200 when all checks pass."""
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["application"]["healthy"] is True
    assert data["checks"]["database"]["healthy"] is True
    assert data["checks"]["auth"]["healthy"] is True


@pytest.mark.asyncio
async def test_favicon_placeholder(client: AsyncClient) -> None:
    """Favicon endpoint returns 204 to avoid browser-triggered 404 noise."""
    response = await client.get("/favicon.ico")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_root_landing_endpoint(client: AsyncClient) -> None:
    """Root endpoint returns API metadata instead of 404."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Test App"
    assert data["version"] == "0.0.1-test"
    assert data["docs_url"] == "/docs"
    assert data["openapi_url"] == "/openapi.json"


# ──────────────────────────────────────────────
# Utility Endpoint Tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_app_info(client: AsyncClient) -> None:
    """Info endpoint returns application metadata from settings."""
    response = await client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "Test App"
    assert data["version"] == "0.0.1-test"
    assert data["debug"] is True


@pytest.mark.asyncio
async def test_list_endpoints(client: AsyncClient) -> None:
    """Endpoints listing includes all registered infrastructure routes."""
    response = await client.get("/endpoints")
    assert response.status_code == 200
    data = response.json()
    assert "endpoints" in data

    paths = [ep["path"] for ep in data["endpoints"]]
    assert "/healthcheck" in paths
    assert "/ready" in paths
    assert "/info" in paths
    assert "/endpoints" in paths
    assert "/api/v1/me" in paths


@pytest.mark.asyncio
async def test_list_endpoints_includes_methods(client: AsyncClient) -> None:
    """Each endpoint entry contains its HTTP methods."""
    response = await client.get("/endpoints")
    data = response.json()
    health_ep = next(ep for ep in data["endpoints"] if ep["path"] == "/healthcheck")
    assert "GET" in health_ep["methods"]


# ──────────────────────────────────────────────
# Middleware Tests — Request ID
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_generated(client: AsyncClient) -> None:
    """A UUID4 request ID is generated when the client sends none."""
    response = await client.get("/healthcheck")
    assert "x-request-id" in response.headers
    assert "x-correlation-id" in response.headers
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 36
    assert request_id.count("-") == 4
    assert response.headers["x-correlation-id"] == request_id


@pytest.mark.asyncio
async def test_request_id_propagated(client: AsyncClient) -> None:
    """A client-provided X-Request-ID seeds correlation, not the local request ID."""
    custom_id = "test-request-id-12345"
    response = await client.get(
        "/healthcheck",
        headers={"X-Request-ID": custom_id},
    )
    assert response.headers["x-request-id"] != custom_id
    assert len(response.headers["x-request-id"]) == 36
    assert response.headers["x-correlation-id"] == custom_id


@pytest.mark.asyncio
async def test_correlation_id_propagated(client: AsyncClient) -> None:
    """A client-provided X-Correlation-ID is preserved across the request."""
    custom_id = "test-correlation-id-12345"
    response = await client.get(
        "/healthcheck",
        headers={"X-Correlation-ID": custom_id},
    )
    assert response.headers["x-request-id"] != custom_id
    assert len(response.headers["x-request-id"]) == 36
    assert response.headers["x-correlation-id"] == custom_id


# ──────────────────────────────────────────────
# Middleware Tests — Timeout
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_returns_504(slow_client: AsyncClient) -> None:
    """Requests exceeding the timeout receive a 504 Gateway Timeout."""
    response = await slow_client.get("/slow")
    assert response.status_code == 504
    data = response.json()
    assert data["error"] == "gateway_timeout"
    assert "exceeded" in data["detail"]


@pytest.mark.asyncio
async def test_fast_request_not_timed_out(slow_client: AsyncClient) -> None:
    """Requests completing within the timeout succeed normally."""
    response = await slow_client.get("/healthcheck")
    assert response.status_code == 200


# ──────────────────────────────────────────────
# Error Handler Tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_404_returns_json(client: AsyncClient) -> None:
    """404 errors return structured JSON, not Starlette's default plain text."""
    response = await client.get("/nonexistent-endpoint")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "http_error"
    assert "path" in data
    assert "detail" in data


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500(test_settings: Settings) -> None:
    """Unhandled exceptions are sanitized by the catch-all error handler."""
    test_settings.debug = False
    app = create_app(settings=test_settings)

    @app.get("/crash")
    async def crash_endpoint() -> None:
        raise RuntimeError("Unexpected failure")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/crash")

    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "internal_error"
    assert "Unexpected failure" not in data["detail"]
    assert "path" in data


@pytest.mark.asyncio
async def test_validation_error_returns_422(test_settings: Settings) -> None:
    """Pydantic validation errors return 422 with field-level detail."""
    from fastapi import Query

    app = create_app(settings=test_settings)

    @app.get("/validated")
    async def validated_endpoint(count: int = Query(..., ge=1)) -> dict[str, int]:
        return {"count": count}

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/validated?count=not_a_number")

    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "validation_error"
    assert isinstance(data["detail"], list)
    assert all("input" not in item for item in data["detail"])
    assert "path" in data


# ──────────────────────────────────────────────
# CORS Tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_preflight_returns_200(client: AsyncClient) -> None:
    """CORS preflight requests return 200 with the correct headers."""
    response = await client.options(
        "/healthcheck",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cors_allows_configured_origin(client: AsyncClient) -> None:
    """Responses include Access-Control-Allow-Origin for matching origins."""
    response = await client.get(
        "/healthcheck",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.headers.get("access-control-allow-origin") is not None


@pytest.mark.asyncio
async def test_cors_expose_headers(client: AsyncClient) -> None:
    """Correlation headers are listed in Access-Control-Expose-Headers."""
    response = await client.get(
        "/healthcheck",
        headers={"Origin": "http://localhost:3000"},
    )
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "x-request-id" in exposed.lower()
    assert "x-correlation-id" in exposed.lower()


# ──────────────────────────────────────────────
# Factory Pattern Tests
# ──────────────────────────────────────────────


def test_create_app_returns_fastapi_instance() -> None:
    """Factory returns a FastAPI instance with the configured title."""
    settings = Settings(app_name="Factory Test", metrics_enabled=False)
    app = create_app(settings=settings)
    assert app.title == "Factory Test"


def test_create_app_with_differentmake_settings() -> None:
    """Different settings yield different app configurations."""
    app_debug = create_app(settings=Settings(debug=True, metrics_enabled=False))
    app_prod = create_app(settings=Settings(debug=False, metrics_enabled=False))

    assert app_debug.debug is True
    assert app_prod.debug is False


def test_create_app_stores_settings_in_state() -> None:
    """Settings are accessible via app.state.settings."""
    settings = Settings(app_name="State Test", metrics_enabled=False)
    app = create_app(settings=settings)
    assert app.state.settings.app_name == "State Test"


@pytest.mark.asyncio
async def test_lifespan_initializes_database_resources(test_settings: Settings) -> None:
    """Lifespan startup populates database resources on app state."""
    app = create_app(settings=test_settings)

    async with app.router.lifespan_context(app):
        assert app.state.db_engine is not None
        assert app.state.db_session_factory is not None


def test_create_app_defaultmake_settings() -> None:
    """Factory works with default settings when none are provided."""
    app = create_app(settings=Settings(metrics_enabled=False))
    assert app.title == "FastAPI Template"


# ──────────────────────────────────────────────
# Metrics Tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_endpoint_available(client_with_metrics: AsyncClient) -> None:
    """The /metrics endpoint is accessible when metrics are enabled."""
    response = await client_with_metrics.get("/metrics")
    assert response.status_code == 200
    assert "http_requests" in response.text or "fastapi_app_info" in response.text


@pytest.mark.asyncio
async def test_metrics_disabled_no_endpoint(client: AsyncClient) -> None:
    """The /metrics endpoint returns 404 when metrics are disabled."""
    response = await client.get("/metrics")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_custom_health_paths_are_registered() -> None:
    """Configured health/readiness paths are reflected in the actual routes."""
    settings = make_settings(
        metrics_enabled=False,
        health_check_path="/livez",
        readiness_check_path="/readyz",
        readiness_include_details=True,
    )
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            live_response = await client.get("/livez")
            ready_response = await client.get("/readyz")
            old_live_response = await client.get("/healthcheck")
            old_ready_response = await client.get("/ready")

    assert live_response.status_code == 200
    assert ready_response.status_code == 200
    assert old_live_response.status_code == 404
    assert old_ready_response.status_code == 404


@pytest.mark.asyncio
async def test_protected_route_requires_bearer_token() -> None:
    """Protected API routes reject anonymous callers."""
    settings = make_settings(
        metrics_enabled=False,
        auth_enabled=True,
        auth_jwt_secret="integration-secret-key-for-hs256-123",
        auth_jwt_audience="fastapi-template",
        auth_jwt_issuer="https://issuer.example.com/",
    )
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_protected_route_accepts_valid_jwt() -> None:
    """Protected API routes return principal data for valid JWTs."""
    settings = make_settings(
        metrics_enabled=False,
        auth_enabled=True,
        auth_jwt_secret="integration-secret-key-for-hs256-123",
        auth_jwt_audience="fastapi-template",
        auth_jwt_issuer="https://issuer.example.com/",
    )
    app = create_app(settings=settings)
    token = build_test_jwt(
        subject="user-123",
        secret=settings.auth_jwt_secret,
        audience=settings.auth_jwt_audience,
        issuer=settings.auth_jwt_issuer,
        scopes=["reports:read"],
        roles=["admin"],
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 200
    assert response.json()["subject"] == "user-123"


@pytest.mark.asyncio
async def test_scope_and_role_guards_enforced() -> None:
    """Scope- and role-protected routes reject insufficient JWT claims."""
    settings = make_settings(
        metrics_enabled=False,
        auth_enabled=True,
        auth_jwt_secret="integration-secret-key-for-hs256-123",
        auth_jwt_audience="fastapi-template",
        auth_jwt_issuer="https://issuer.example.com/",
    )
    app = create_app(settings=settings)
    token = build_test_jwt(
        subject="user-123",
        secret=settings.auth_jwt_secret,
        audience=settings.auth_jwt_audience,
        issuer=settings.auth_jwt_issuer,
        scopes=["profile:read"],
        roles=["user"],
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            reports_response = await client.get(
                "/api/v1/reports",
                headers={"Authorization": f"Bearer {token}"},
            )
            admin_response = await client.get(
                "/api/v1/admin",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert reports_response.status_code == 403
    assert admin_response.status_code == 403


@pytest.mark.asyncio
async def test_rate_limit_returns_429() -> None:
    """Rate limiting rejects requests after the configured threshold."""
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
            first = await client.get("/")
            second = await client.get("/")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["x-ratelimit-limit"] == "1"
    assert "x-request-id" in second.headers
    assert "x-correlation-id" in second.headers


@pytest.mark.asyncio
async def test_security_headers_present_on_responses(client: AsyncClient) -> None:
    """Security headers are present on successful responses."""
    response = await client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_info_endpoint_disabled_by_default() -> None:
    """Diagnostic endpoints stay disabled unless explicitly enabled."""
    app = create_app(settings=make_settings(metrics_enabled=False))

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            info_response = await client.get("/info")
            endpoints_response = await client.get("/endpoints")

    assert info_response.status_code == 404
    assert endpoints_response.status_code == 404


# ──────────────────────────────────────────────
# Postgres Backend Integration Tests
# ──────────────────────────────────────────────


@requires_postgres
@pytest.mark.asyncio
async def test_postgres_health_and_readiness(postgres_client: AsyncClient) -> None:
    """Health and readiness pass when wired to a real Postgres database."""
    health = await postgres_client.get("/healthcheck")
    assert health.status_code == 200

    ready = await postgres_client.get("/ready")
    assert ready.status_code == 200
    data = ready.json()
    assert data["checks"]["database"]["healthy"] is True


@requires_postgres
@pytest.mark.asyncio
async def test_postgres_root_endpoint(postgres_client: AsyncClient) -> None:
    """Root endpoint works with Postgres backend."""
    response = await postgres_client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ──────────────────────────────────────────────
# Redis Rate Limiting Integration Tests
# ──────────────────────────────────────────────


@requires_redis
@pytest.mark.asyncio
async def test_redis_rate_limit_enforced(redis_client: AsyncClient) -> None:
    """Rate limiting works correctly with a real Redis backend."""
    first = await redis_client.get("/")
    second = await redis_client.get("/")
    third = await redis_client.get("/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "x-ratelimit-limit" in third.headers


@requires_redis
@pytest.mark.asyncio
async def test_redis_rate_limit_headers_present(redis_client: AsyncClient) -> None:
    """Rate-limited responses from Redis include standard headers."""
    response = await redis_client.get("/")
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-reset" in response.headers
