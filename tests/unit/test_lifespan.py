"""
Unit tests for the lifespan manager.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI

from app.lifespan import LifespanManager
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


class TestLifespanManager:
    """Tests for the startup/shutdown lifecycle manager."""

    @pytest.mark.asyncio
    async def test_lifespan_yields(self) -> None:
        """The lifespan context manager completes startup and shutdown without errors."""
        settings = make_settings(metrics_enabled=False)
        logger = logging.getLogger("test-lifespan")
        manager = LifespanManager(settings, logger)
        app = FastAPI()

        async with manager.lifespan(app):
            assert app.state.db_engine is not None
            assert app.state.db_session_factory is not None
            assert app.state.auth_service is not None

    @pytest.mark.asyncio
    async def test_lifespan_logs_startup(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = make_settings(
            app_name="LifeTest",
            app_version="1.0.0",
            metrics_enabled=False,
        )
        logger = logging.getLogger("test-lifespan-log")
        logger.setLevel(logging.DEBUG)
        manager = LifespanManager(settings, logger)
        app = FastAPI()

        with caplog.at_level(logging.INFO, logger="test-lifespan-log"):
            async with manager.lifespan(app):
                assert app.state.db_engine is not None

        messages = [r.message for r in caplog.records]
        assert any("Starting LifeTest" in m for m in messages)
        assert any("startup complete" in m.lower() for m in messages)

    @pytest.mark.asyncio
    async def test_lifespan_logs_shutdown(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = make_settings(metrics_enabled=False)
        logger = logging.getLogger("test-lifespan-shutdown")
        logger.setLevel(logging.DEBUG)
        manager = LifespanManager(settings, logger)
        app = FastAPI()

        with caplog.at_level(logging.INFO, logger="test-lifespan-shutdown"):
            async with manager.lifespan(app):
                assert app.state.db_engine is not None

        messages = [r.message for r in caplog.records]
        assert any("shutdown" in m.lower() for m in messages)

    @pytest.mark.asyncio
    async def test_lifespan_continues_when_auth_warm_up_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["RS256"],
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
            metrics_enabled=False,
        )
        logger = logging.getLogger("test-lifespan-warmup")
        logger.setLevel(logging.INFO)
        manager = LifespanManager(settings, logger)
        app = FastAPI()
        auth_service = Mock()
        auth_service.warm_up = AsyncMock(side_effect=RuntimeError("jwks down"))

        with (
            patch("app.lifespan.JWTAuthService", return_value=auth_service),
            caplog.at_level(logging.WARNING, logger="test-lifespan-warmup"),
        ):
            async with manager.lifespan(app):
                assert app.state.auth_service is auth_service

        assert any("degraded readiness" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_shutdown_disposes_engine_and_closes_client(self) -> None:
        """Shutdown closes the HTTP client and disposes the database engine."""
        settings = make_settings(metrics_enabled=False)
        logger = logging.getLogger("test-lifespan-shutdown-resources")
        manager = LifespanManager(settings, logger)
        app = FastAPI()

        async with manager.lifespan(app):
            http_client = app.state.http_client

        assert http_client.is_closed

    @pytest.mark.asyncio
    async def test_shutdown_runs_even_when_app_raises(self) -> None:
        """Resources are cleaned up even if the app raises during its lifetime."""
        settings = make_settings(metrics_enabled=False)
        logger = logging.getLogger("test-lifespan-error-cleanup")
        manager = LifespanManager(settings, logger)
        app = FastAPI()

        with pytest.raises(RuntimeError, match="app crash"):
            async with manager.lifespan(app):
                http_client = app.state.http_client
                raise RuntimeError("app crash")

        assert http_client.is_closed

    @pytest.mark.asyncio
    async def test_lifespan_creates_http_client_with_auth_timeout(self) -> None:
        """HTTP client uses the configured auth timeout."""
        settings = make_settings(auth_http_timeout_seconds=15, metrics_enabled=False)
        logger = logging.getLogger("test-lifespan-http-timeout")
        manager = LifespanManager(settings, logger)
        app = FastAPI()

        async with manager.lifespan(app):
            assert app.state.http_client.timeout.connect == 15
