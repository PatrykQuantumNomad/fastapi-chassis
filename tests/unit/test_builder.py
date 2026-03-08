"""
Unit tests for the FastAPIAppBuilder.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from app.app_builder import FastAPIAppBuilder
from app.settings import Settings

pytestmark = pytest.mark.unit


class TestFastAPIAppBuilder:
    """Tests for the builder pattern configuration."""

    @pytest.fixture
    def settings(self) -> Settings:
        return Settings(
            app_name="Builder Test",
            app_version="1.0.0",
            metrics_enabled=False,
            log_level="WARNING",
        )

    @pytest.fixture
    def logger(self) -> logging.Logger:
        return logging.getLogger("test-builder")

    def test_build_returns_fastapi_instance(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        app = FastAPIAppBuilder(settings=settings, logger=logger).build()
        assert isinstance(app, FastAPI)

    def test_app_title_from_settings(self, settings: Settings, logger: logging.Logger) -> None:
        app = FastAPIAppBuilder(settings=settings, logger=logger).build()
        assert app.title == "Builder Test"

    def test_app_version_from_settings(self, settings: Settings, logger: logging.Logger) -> None:
        app = FastAPIAppBuilder(settings=settings, logger=logger).build()
        assert app.version == "1.0.0"

    def test_setup_settings_attaches_to_state(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        app = FastAPIAppBuilder(settings=settings, logger=logger).setup_settings().build()
        assert app.state.settings is settings

    def test_setup_routes_registers_health(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        app = FastAPIAppBuilder(settings=settings, logger=logger).setup_routes().build()
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/healthcheck" in paths
        assert "/ready" in paths
        assert "/info" not in paths
        assert "/endpoints" not in paths

    def test_setup_routes_uses_configured_health_paths(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        settings.health_check_path = "/livez"
        settings.readiness_check_path = "/readyz"
        app = FastAPIAppBuilder(settings=settings, logger=logger).setup_routes().build()
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/livez" in paths
        assert "/readyz" in paths
        assert "/healthcheck" not in paths
        assert "/ready" not in paths

    def test_setup_routes_can_enable_diagnostic_routes(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        settings.info_endpoint_enabled = True
        settings.endpoints_listing_enabled = True
        app = FastAPIAppBuilder(settings=settings, logger=logger).setup_routes().build()
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/info" in paths
        assert "/endpoints" in paths

    def test_full_chain(self, settings: Settings, logger: logging.Logger) -> None:
        """The complete builder chain executes without errors."""
        app = (
            FastAPIAppBuilder(settings=settings, logger=logger)
            .setup_settings()
            .setup_logging()
            .setup_database()
            .setup_auth()
            .setup_cache()
            .setup_tracing()
            .setup_metrics()
            .setup_error_handlers()
            .setup_routes()
            .setup_middleware()
            .build()
        )
        assert isinstance(app, FastAPI)

    def test_builder_without_metrics(self, settings: Settings, logger: logging.Logger) -> None:
        """Skipping metrics doesn't break the builder chain."""
        settings.metrics_enabled = False
        app = (
            FastAPIAppBuilder(settings=settings, logger=logger)
            .setup_settings()
            .setup_logging()
            .setup_database()
            .setup_auth()
            .setup_cache()
            .setup_tracing()
            .setup_metrics()
            .setup_routes()
            .build()
        )
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/metrics" not in paths

    def test_builder_default_settings(self) -> None:
        """Builder uses default settings when none are provided."""
        builder = FastAPIAppBuilder()
        assert builder.settings.app_name == "FastAPI Template"

    def test_builder_default_logger(self) -> None:
        """Builder creates a logger when none is provided."""
        builder = FastAPIAppBuilder()
        assert builder.logger is not None
        assert builder.logger.name == "FastAPI Template"

    def test_setup_methods_return_self(self, settings: Settings, logger: logging.Logger) -> None:
        """Every setup method returns the builder for chaining."""
        builder = FastAPIAppBuilder(settings=settings, logger=logger)
        assert builder.setup_settings() is builder
        assert builder.setup_logging() is builder
        assert builder.setup_database() is builder
        assert builder.setup_auth() is builder
        assert builder.setup_cache() is builder
        assert builder.setup_tracing() is builder
        assert builder.setup_metrics() is builder
        assert builder.setup_error_handlers() is builder
        assert builder.setup_routes() is builder
        assert builder.setup_middleware() is builder

    def test_setup_database_registers_state_and_readiness(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        builder = (
            FastAPIAppBuilder(settings=settings, logger=logger).setup_settings().setup_database()
        )
        assert builder.app.state.db_engine is None
        assert builder.app.state.db_session_factory is None

    def test_setup_auth_registers_state(self, settings: Settings, logger: logging.Logger) -> None:
        builder = FastAPIAppBuilder(settings=settings, logger=logger).setup_settings().setup_auth()
        assert builder.app.state.auth_service is None

    def test_setup_cache_registers_state(self, settings: Settings, logger: logging.Logger) -> None:
        builder = FastAPIAppBuilder(settings=settings, logger=logger).setup_settings().setup_cache()
        assert builder.app.state.cache_store is None

    def test_setup_cache_registers_readiness_when_enabled(self, logger: logging.Logger) -> None:
        settings = Settings(metrics_enabled=False, cache_enabled=True)
        builder = FastAPIAppBuilder(settings=settings, logger=logger).setup_settings().setup_cache()
        assert "cache" in builder.app.state.readiness_registry._checks

    def test_setup_cache_skips_readiness_when_disabled(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        settings.cache_enabled = False
        builder = FastAPIAppBuilder(settings=settings, logger=logger).setup_settings().setup_cache()
        assert "cache" not in builder.app.state.readiness_registry._checks


class TestBuilderErrorPaths:
    """Tests for the error-handling branches in the builder."""

    def test_setup_logging_bad_config_path_raises(self) -> None:
        settings = Settings(
            logging_config_path="/nonexistent/config.json",
            metrics_enabled=False,
        )
        builder = FastAPIAppBuilder(settings=settings)
        with pytest.raises(FileNotFoundError):
            builder.setup_logging()

    def test_setup_error_handlers_failure_raises(self) -> None:
        settings = Settings(metrics_enabled=False)
        builder = FastAPIAppBuilder(settings=settings)
        with (
            patch.object(
                builder.app, "exception_handler", side_effect=RuntimeError("handler fail")
            ),
            pytest.raises(RuntimeError, match="handler fail"),
        ):
            builder.setup_error_handlers()

    def test_setup_middleware_failure_raises(self) -> None:
        settings = Settings(metrics_enabled=False)
        builder = FastAPIAppBuilder(settings=settings)
        with (
            patch.object(builder.app, "add_middleware", side_effect=RuntimeError("mw fail")),
            pytest.raises(RuntimeError, match="mw fail"),
        ):
            builder.setup_middleware()

    def test_setup_logging_applies_handler_level(self) -> None:
        """Covers the for-loop that sets level on each handler."""
        settings = Settings(log_level="DEBUG", metrics_enabled=False)
        logger = logging.getLogger("test-handler-level")
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)
        try:
            builder = FastAPIAppBuilder(settings=settings, logger=logger)
            builder.setup_logging()
            assert handler.level == logging.DEBUG
        finally:
            logger.removeHandler(handler)

    def test_setup_logging_json_format(self) -> None:
        """The JSON branch injects JsonFormatter into the dictConfig."""
        from pythonjsonlogger.json import JsonFormatter

        settings = Settings(log_format="json", metrics_enabled=False)
        builder = FastAPIAppBuilder(settings=settings)
        builder.setup_logging()

        console_handler = logging.getLogger("uvicorn").handlers[0]
        assert isinstance(console_handler.formatter, JsonFormatter)

    def test_setup_metrics_import_error(self) -> None:
        """Missing Prometheus packages log a warning instead of crashing."""
        import builtins

        settings = Settings(metrics_enabled=True)
        logger = logging.getLogger("test-metrics-import")
        builder = FastAPIAppBuilder(settings=settings, logger=logger)

        real_import = builtins.__import__

        def _import_with_failure(name: str, *args: object, **kwargs: object) -> object:
            if name in {
                "prometheus_client",
                "starlette_exporter",
                "starlette_exporter.optional_metrics",
            }:
                raise ImportError("no prometheus")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        with patch("builtins.__import__", side_effect=_import_with_failure):
            result = builder.setup_metrics()

        assert result is builder

    def test_setup_metrics_generic_exception(self) -> None:
        """Unexpected errors in setup_metrics propagate."""
        from prometheus_client import Info

        settings = Settings(metrics_enabled=True)
        logger = logging.getLogger("test-metrics-exc")
        builder = FastAPIAppBuilder(settings=settings, logger=logger)

        with (
            patch.object(Info, "info", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            builder.setup_metrics()
