"""
Unit tests for error handlers.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Query
from httpx import ASGITransport, AsyncClient

from app.errors.handlers import ErrorHandler

pytestmark = pytest.mark.unit


class TestErrorHandler:
    """Tests for the centralized error handler."""

    @pytest.fixture
    def error_app(self) -> FastAPI:
        app = FastAPI()
        logger = logging.getLogger("test-error-handler")
        handler = ErrorHandler(app, logger)
        handler.register_default_handlers()

        @app.get("/ok")
        async def ok() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/crash")
        async def crash() -> None:
            raise RuntimeError("boom")

        @app.get("/validated")
        async def validated(count: int = Query(..., ge=1)) -> dict[str, int]:
            return {"count": count}

        return app

    @pytest.fixture
    async def error_client(self, error_app: FastAPI) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=error_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_normal_request_unaffected(self, error_client: AsyncClient) -> None:
        response = await error_client.get("/ok")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_404_json_structure(self, error_client: AsyncClient) -> None:
        response = await error_client.get("/nope")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "http_error"
        assert "Not Found" in data["detail"]
        assert "path" in data

    @pytest.mark.asyncio
    async def test_500_hides_internal_details(self) -> None:
        """500 handler catches exceptions and returns a generic JSON response."""
        app = FastAPI()
        logger = logging.getLogger("test-500")
        handler = ErrorHandler(app, logger)
        handler.register_default_handlers()

        @app.get("/crash")
        async def crash() -> None:
            raise RuntimeError("boom")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/crash")

        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "internal_error"
        assert "boom" not in data["detail"]

    @pytest.mark.asyncio
    async def test_422_includes_field_errors(self, error_client: AsyncClient) -> None:
        response = await error_client.get("/validated?count=abc")
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "validation_error"
        assert isinstance(data["detail"], list)
        assert len(data["detail"]) > 0
        assert all("input" not in item for item in data["detail"])

    @pytest.mark.asyncio
    async def test_422_missing_required_param(self, error_client: AsyncClient) -> None:
        response = await error_client.get("/validated")
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "validation_error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["/nope", "/validated?count=abc"])
    async def test_error_response_has_path(self, error_client: AsyncClient, url: str) -> None:
        """All error responses include the request path for correlation."""
        response = await error_client.get(url)
        data = response.json()
        assert "path" in data
        assert "?" not in data["path"]

    @pytest.mark.asyncio
    async def test_error_response_redacts_query_string(self, error_client: AsyncClient) -> None:
        response = await error_client.get("/validated?token=secret&count=abc")
        data = response.json()
        assert data["path"] == "/validated"
        assert "secret" not in str(data["detail"])

    @pytest.mark.asyncio
    async def test_validation_logs_do_not_include_rejected_input(
        self,
        error_client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="test-error-handler")
        response = await error_client.get("/validated?token=secret&count=abc")

        assert response.status_code == 422
        assert not any("secret" in record.getMessage() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_http_exception_preserves_custom_headers(self) -> None:
        """HTTP exceptions with custom headers pass those headers through."""
        from fastapi import HTTPException

        app = FastAPI()
        logger = logging.getLogger("test-custom-headers")
        handler = ErrorHandler(app, logger)
        handler.register_default_handlers()

        @app.get("/limited")
        async def limited() -> None:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": "60"},
            )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/limited")

        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        data = response.json()
        assert data["error"] == "http_error"

    @pytest.mark.asyncio
    async def test_500_logs_full_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Unhandled exceptions log the full traceback server-side."""
        app = FastAPI()
        logger = logging.getLogger("test-500-log")
        handler = ErrorHandler(app, logger)
        handler.register_default_handlers()

        @app.get("/crash")
        async def crash() -> None:
            raise ValueError("sensitive-traceback-info")

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        caplog.set_level(logging.ERROR, logger="test-500-log")

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/crash")

        assert response.status_code == 500
        data = response.json()
        assert "sensitive-traceback-info" not in data["detail"]
        assert any("sensitive-traceback-info" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_sanitize_validation_errors_skips_non_dict_entries(self) -> None:
        """Non-dict entries in validation errors are filtered out."""
        from app.errors.handlers import _sanitize_validation_errors

        errors: list[object] = [
            {"type": "value_error", "msg": "bad value", "input": "secret"},
            "not-a-dict",
            42,
        ]
        result = _sanitize_validation_errors(errors)
        assert len(result) == 1
        assert "input" not in result[0]
        assert result[0]["msg"] == "bad value"
