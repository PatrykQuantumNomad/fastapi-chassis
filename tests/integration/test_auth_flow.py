"""
Integration tests for the full authentication and authorization flow.

Exercises the complete ASGI stack — middleware, error handlers, and auth
dependencies — to verify end-to-end behavior for JWT-based access control.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app import create_app
from app.settings import Settings
from tests.helpers import TEST_AUDIENCE, TEST_ISSUER, TEST_SECRET, make_jwt, make_settings

pytestmark = pytest.mark.integration


def _auth_settings(**overrides: object) -> Settings:
    """Settings with auth enabled and HS256 configured."""
    defaults: dict[str, object] = {
        "metrics_enabled": False,
        "auth_enabled": True,
        "auth_jwt_secret": TEST_SECRET,
        "auth_jwt_audience": TEST_AUDIENCE,
        "auth_jwt_issuer": TEST_ISSUER,
    }
    defaults.update(overrides)
    return make_settings(**defaults)


@pytest.mark.asyncio
async def test_expired_token_returns_401() -> None:
    """Tokens with a past expiry time are rejected."""
    settings = _auth_settings()
    app = create_app(settings=settings)
    token = make_jwt(expires_in_seconds=-60)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience_returns_401() -> None:
    """Tokens with a mismatched audience are rejected."""
    settings = _auth_settings()
    app = create_app(settings=settings)
    token = make_jwt(audience="wrong-audience")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_issuer_returns_401() -> None:
    """Tokens with a mismatched issuer are rejected."""
    settings = _auth_settings()
    app = create_app(settings=settings)
    token = make_jwt(issuer="https://wrong-issuer.example.com/")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_error_includes_request_id() -> None:
    """401 responses include X-Request-ID for correlation."""
    settings = _auth_settings()
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36


@pytest.mark.asyncio
async def test_auth_error_includes_security_headers() -> None:
    """401 responses include security headers."""
    settings = _auth_settings()
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_scope_guard_rejects_partial_scopes() -> None:
    """Reports endpoint requires reports:read scope; profile:read is insufficient."""
    settings = _auth_settings()
    app = create_app(settings=settings)
    token = make_jwt(scopes=["profile:read"])

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/reports",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 403
    assert "Missing required scopes" in response.json()["detail"]


@pytest.mark.asyncio
async def test_role_guard_rejects_wrong_role() -> None:
    """Admin endpoint requires admin role; user role is insufficient."""
    settings = _auth_settings()
    app = create_app(settings=settings)
    token = make_jwt(roles=["user"])

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/admin",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 403
    assert "Missing required roles" in response.json()["detail"]


@pytest.mark.asyncio
async def test_valid_token_with_all_privileges_succeeds() -> None:
    """Token with correct scope and role can access all endpoints."""
    settings = _auth_settings()
    app = create_app(settings=settings)
    token = make_jwt(scopes=["reports:read"], roles=["admin"])

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            me = await client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            reports = await client.get(
                "/api/v1/reports",
                headers={"Authorization": f"Bearer {token}"},
            )
            admin = await client.get(
                "/api/v1/admin",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert me.status_code == 200
    assert reports.status_code == 200
    assert admin.status_code == 200
