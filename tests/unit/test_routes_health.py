"""
Unit tests for health check and utility route handlers.

Tests the route handler functions and router factory in isolation,
without exercising the full ASGI stack.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

from typing import Any

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.routing import Route

from app.readiness import ReadinessCheckResult, ReadinessRegistry
from app.routes.health import (
    app_info,
    create_health_router,
    favicon,
    health_check,
    list_endpoints,
    readiness_check,
    root,
)
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


def _make_request(**state_overrides: Any) -> Request:
    """Build a minimal ASGI Request with configurable app state."""
    app = FastAPI(title="Test App", version="0.0.1-test")
    app.docs_url = "/docs"
    app.redoc_url = "/redoc"
    app.openapi_url = "/openapi.json"
    for key, value in state_overrides.items():
        setattr(app.state, key, value)

    # Add a sample route for list_endpoints
    @app.get("/healthcheck")
    async def hc() -> dict[str, str]:
        return {"status": "healthy"}

    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "query_string": b"",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "root_path": "",
            "http_version": "1.1",
            "asgi": {"version": "3.0"},
        }
    )


class TestRoot:
    """Tests for the root landing endpoint."""

    def test_returns_status_ok(self) -> None:
        request = _make_request()
        result = root(request)
        assert result["status"] == "ok"

    def test_returns_app_metadata(self) -> None:
        request = _make_request()
        result = root(request)
        assert result["app"] == "Test App"
        assert result["version"] == "0.0.1-test"
        assert result["docs_url"] == "/docs"
        assert result["redoc_url"] == "/redoc"
        assert result["openapi_url"] == "/openapi.json"


class TestHealthCheck:
    """Tests for the liveness probe endpoint."""

    def test_returns_healthy(self) -> None:
        assert health_check() == {"status": "healthy"}


class TestReadinessCheck:
    """Tests for the readiness probe endpoint."""

    @pytest.mark.asyncio
    async def test_returns_ready_when_all_checks_pass(self) -> None:
        registry = ReadinessRegistry()
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app"))
        settings = make_settings(metrics_enabled=False, readiness_include_details=True)
        request = _make_request(readiness_registry=registry, settings=settings)

        response = await readiness_check(request)
        data = bytes(response.body).decode()

        assert response.status_code == 200
        assert '"ready"' in data

    @pytest.mark.asyncio
    async def test_returns_503_when_any_check_fails(self) -> None:
        registry = ReadinessRegistry()
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app"))
        registry.register("db", lambda _app: ReadinessCheckResult.error("db", "unavailable"))
        settings = make_settings(metrics_enabled=False, readiness_include_details=True)
        request = _make_request(readiness_registry=registry, settings=settings)

        response = await readiness_check(request)

        assert response.status_code == 503
        data = bytes(response.body).decode()
        assert '"not_ready"' in data

    @pytest.mark.asyncio
    async def test_hides_details_when_disabled(self) -> None:
        registry = ReadinessRegistry()
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app", detail="secret"))
        settings = make_settings(metrics_enabled=False, readiness_include_details=False)
        request = _make_request(readiness_registry=registry, settings=settings)

        response = await readiness_check(request)

        assert response.status_code == 200
        data = bytes(response.body).decode()
        assert "secret" not in data

    @pytest.mark.asyncio
    async def test_includes_details_when_enabled(self) -> None:
        registry = ReadinessRegistry()
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app", detail="all good"))
        settings = make_settings(metrics_enabled=False, readiness_include_details=True)
        request = _make_request(readiness_registry=registry, settings=settings)

        response = await readiness_check(request)

        assert response.status_code == 200
        data = bytes(response.body).decode()
        assert "all good" in data


class TestFavicon:
    """Tests for the favicon placeholder endpoint."""

    def test_returns_204(self) -> None:
        response = favicon()
        assert response.status_code == 204


class TestAppInfo:
    """Tests for the application metadata endpoint."""

    def test_returns_settings_metadata(self) -> None:
        settings = make_settings(
            app_name="Info App",
            app_version="2.0.0",
            debug=True,
            metrics_enabled=False,
        )
        request = _make_request(settings=settings)

        result = app_info(request)

        assert result == {"app": "Info App", "version": "2.0.0", "debug": True}

    def test_returns_production_defaults(self) -> None:
        settings = make_settings(metrics_enabled=False)
        request = _make_request(settings=settings)

        result = app_info(request)

        assert result["debug"] is False


class TestListEndpoints:
    """Tests for the endpoint listing route."""

    def test_returns_endpoint_list(self) -> None:
        request = _make_request()

        response = list_endpoints(request)

        assert response.status_code == 200
        import json

        data = json.loads(bytes(response.body).decode())
        assert "endpoints" in data
        paths = [ep["path"] for ep in data["endpoints"]]
        assert "/healthcheck" in paths

    def test_includes_methods(self) -> None:
        request = _make_request()

        response = list_endpoints(request)

        import json

        data = json.loads(bytes(response.body).decode())
        hc = next(ep for ep in data["endpoints"] if ep["path"] == "/healthcheck")
        assert "GET" in hc["methods"]


class TestCreateHealthRouter:
    """Tests for the health router factory."""

    def test_registers_default_paths(self) -> None:
        settings = make_settings(metrics_enabled=False)
        router = create_health_router(settings)
        paths = [r.path for r in router.routes if isinstance(r, Route)]

        assert "/" in paths
        assert "/healthcheck" in paths
        assert "/ready" in paths
        assert "/favicon.ico" in paths

    def test_uses_custom_health_paths(self) -> None:
        settings = make_settings(
            metrics_enabled=False,
            health_check_path="/livez",
            readiness_check_path="/readyz",
        )
        router = create_health_router(settings)
        paths = [r.path for r in router.routes if isinstance(r, Route)]

        assert "/livez" in paths
        assert "/readyz" in paths
        assert "/healthcheck" not in paths
        assert "/ready" not in paths

    def test_includes_info_when_enabled(self) -> None:
        settings = make_settings(metrics_enabled=False, info_endpoint_enabled=True)
        router = create_health_router(settings)
        paths = [r.path for r in router.routes if isinstance(r, Route)]

        assert "/info" in paths

    def test_excludes_info_when_disabled(self) -> None:
        settings = make_settings(metrics_enabled=False, info_endpoint_enabled=False)
        router = create_health_router(settings)
        paths = [r.path for r in router.routes if isinstance(r, Route)]

        assert "/info" not in paths

    def test_includes_endpoints_listing_when_enabled(self) -> None:
        settings = make_settings(metrics_enabled=False, endpoints_listing_enabled=True)
        router = create_health_router(settings)
        paths = [r.path for r in router.routes if isinstance(r, Route)]

        assert "/endpoints" in paths

    def test_excludes_endpoints_listing_when_disabled(self) -> None:
        settings = make_settings(metrics_enabled=False, endpoints_listing_enabled=False)
        router = create_health_router(settings)
        paths = [r.path for r in router.routes if isinstance(r, Route)]

        assert "/endpoints" not in paths
