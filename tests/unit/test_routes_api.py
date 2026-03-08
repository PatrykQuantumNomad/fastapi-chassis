"""Unit tests for example API route handlers."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.service import JWTAuthService
from app.routes.api import get_admin_dashboard, get_me, get_reports, router
from tests.helpers import (
    TEST_AUDIENCE,
    TEST_ISSUER,
    TEST_SECRET,
    make_jwt,
    make_principal,
    make_settings,
)

pytestmark = pytest.mark.unit


def _auth_app() -> FastAPI:
    """Minimal FastAPI app with auth-protected API routes."""
    import httpx

    settings = make_settings(
        metrics_enabled=False,
        auth_enabled=True,
        auth_jwt_secret=TEST_SECRET,
        auth_jwt_audience=TEST_AUDIENCE,
        auth_jwt_issuer=TEST_ISSUER,
    )
    app = FastAPI()
    app.state.auth_service = JWTAuthService(settings, httpx.AsyncClient())
    app.include_router(router)
    return app


class TestApiRouteHandlers:
    """Tests direct route handler payloads (no HTTP)."""

    @pytest.mark.asyncio
    async def test_get_me_returns_principal_payload(self) -> None:
        principal = make_principal(subject="user-123", roles=["admin"])
        payload = await get_me(principal)

        assert payload["subject"] == "user-123"
        assert payload["roles"] == ["admin"]

    @pytest.mark.asyncio
    async def test_get_reports_returns_report_access_payload(self) -> None:
        principal = make_principal(subject="user-123", scopes=["reports:read"])
        payload = await get_reports(principal)

        assert payload == {
            "status": "ok",
            "subject": "user-123",
            "report_access": True,
        }

    @pytest.mark.asyncio
    async def test_get_admin_dashboard_returns_admin_payload(self) -> None:
        principal = make_principal(subject="user-123", roles=["admin"])
        payload = await get_admin_dashboard(principal)

        assert payload == {
            "status": "ok",
            "subject": "user-123",
            "admin": True,
        }


class TestApiRoutesHTTP:
    """Tests API routes through HTTP with auth dependency resolution."""

    @pytest.fixture
    def app(self) -> FastAPI:
        return _auth_app()

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/me",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_returns_principal(self, client: AsyncClient) -> None:
        token = make_jwt(subject="user-42", scopes=["reports:read"], roles=["admin"])
        response = await client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["subject"] == "user-42"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("scopes", "expected_status"),
        [
            (["reports:read"], 200),
            (["profile:read"], 403),
            ([], 403),
        ],
    )
    async def test_reports_scope_enforcement(
        self, client: AsyncClient, scopes: list[str], expected_status: int
    ) -> None:
        token = make_jwt(scopes=scopes, roles=["admin"])
        response = await client.get(
            "/api/v1/reports",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == expected_status

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("roles", "expected_status"),
        [
            (["admin"], 200),
            (["user"], 403),
            ([], 403),
        ],
    )
    async def test_admin_role_enforcement(
        self, client: AsyncClient, roles: list[str], expected_status: int
    ) -> None:
        token = make_jwt(scopes=["reports:read"], roles=roles)
        response = await client.get(
            "/api/v1/admin",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == expected_status
