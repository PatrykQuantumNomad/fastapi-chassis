"""
FastAPI Application Builder.

Implements the Builder Pattern to configure a production-ready FastAPI
application through a fluent interface. Each configuration concern is
isolated into a named method that returns `self` for chaining.

The template keeps the setup stages explicit so the bootstrap path reads
like a deployment checklist rather than a collection of hidden side effects.
"""

import contextlib
import json
import logging
import logging.config
import platform
from typing import TYPE_CHECKING, Any, Self, cast

import fastapi
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .cache.health import check_cache_readiness
from .db.health import check_database_readiness
from .errors import ErrorHandler
from .lifespan import LifespanManager
from .middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
)
from .observability import configure_tracing, instrument_fastapi_app
from .readiness import ReadinessCheckResult, ReadinessRegistry
from .routes import api_router, create_health_router
from .settings import Settings

if TYPE_CHECKING:
    from .auth import JWTAuthService

METRICS_PATH = "/metrics"


class FastAPIAppBuilder:
    """
    Builder class for constructing a production-ready FastAPI application.

    Each `setup_*()` method owns one concern and can be tested in isolation,
    while `build()` returns the final configured application instance.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the builder with settings, logger, and base FastAPI app."""
        self.settings = settings or Settings()
        self.logger = logger or logging.getLogger(self.settings.app_name)

        lifespan_manager = LifespanManager(self.settings, self.logger)
        self.app = FastAPI(
            title=self.settings.app_name,
            description=self.settings.app_description,
            version=self.settings.app_version,
            debug=self.settings.debug,
            docs_url="/docs" if self.settings.docs_enabled else None,
            redoc_url="/redoc" if self.settings.redoc_enabled else None,
            openapi_url="/openapi.json" if self.settings.openapi_enabled else None,
            lifespan=lifespan_manager.lifespan,
        )

    def setup_settings(self) -> Self:
        """Attach configuration settings and shared registries to application state."""
        self.app.state.settings = self.settings
        self.app.state.readiness_registry = ReadinessRegistry()
        self.app.state.readiness_registry.register(
            "application",
            _ready,
        )
        self.logger.info("Application settings loaded into app state")
        return self

    def setup_logging(self) -> Self:
        """Configure structured logging from a JSON configuration file."""
        try:
            with open(self.settings.logging_config_path) as file_obj:
                logging_config: dict[str, Any] = json.load(file_obj)

            if self.settings.log_format == "json":
                logging_config["formatters"] = {
                    "default": {
                        "()": "pythonjsonlogger.json.JsonFormatter",
                        "format": (
                            "%(asctime)s %(levelname)s %(name)s"
                            " %(request_id)s %(correlation_id)s %(module)s %(funcName)s"
                            " %(lineno)d %(message)s"
                        ),
                        "datefmt": "%Y-%m-%dT%H:%M:%S",
                        "rename_fields": {
                            "asctime": "timestamp",
                            "levelname": "level",
                            "name": "logger",
                            "funcName": "function",
                            "lineno": "line",
                        },
                    }
                }
            else:
                logging_config["formatters"] = {
                    "default": {
                        "format": self.settings.log_text_template,
                        "datefmt": self.settings.log_date_format,
                    }
                }

            for handler in logging_config.get("handlers", {}).values():
                handler["formatter"] = "default"

            logging.config.dictConfig(logging_config)

            log_level = self.settings.log_level.upper()
            self.logger.setLevel(log_level)
            for handler in self.logger.handlers:
                handler.setLevel(log_level)

            self.logger.info("Logging configured successfully (level=%s)", log_level)
        except Exception as exc:
            self.logger.exception("Failed to configure logging: %s", exc)
            raise

        return self

    def setup_database(self) -> Self:
        """Register database state placeholders and readiness expectations."""
        self.app.state.db_engine = None
        self.app.state.db_session_factory = None
        self.app.state.readiness_registry.register("database", check_database_readiness)
        self.logger.info("Database integration configured successfully")
        return self

    def setup_auth(self) -> Self:
        """Register auth state placeholders and readiness hooks."""
        self.app.state.auth_service = None

        async def auth_readiness_check(app: FastAPI) -> ReadinessCheckResult:
            auth_service = cast("JWTAuthService", app.state.auth_service)
            return await auth_service.readiness_check(app)

        self.app.state.readiness_registry.register("auth", auth_readiness_check)
        self.logger.info("Authentication integration configured successfully")
        return self

    def setup_cache(self) -> Self:
        """Register cache state placeholders and readiness hooks."""
        self.app.state.cache_store = None

        if self.settings.cache_enabled:
            self.app.state.readiness_registry.register("cache", check_cache_readiness)
            self.logger.info(
                "Cache integration configured (backend=%s)", self.settings.cache_backend
            )
        else:
            self.logger.info("Cache disabled by configuration")
        return self

    def setup_tracing(self) -> Self:
        """Configure OpenTelemetry tracing for the application."""
        configure_tracing(self.settings)
        instrument_fastapi_app(self.app, self.settings)
        self.logger.info(
            "Tracing %s",
            (
                "configured successfully"
                if self.settings.otel_enabled
                else "disabled by configuration"
            ),
        )
        return self

    def setup_metrics(self) -> Self:
        """Configure Prometheus metrics collection."""
        if not self.settings.metrics_enabled:
            self.logger.info("Metrics collection disabled by configuration")
            return self

        try:
            from prometheus_client import REGISTRY, Info
            from starlette_exporter import PrometheusMiddleware, handle_metrics
            from starlette_exporter.optional_metrics import request_body_size, response_body_size

            with contextlib.suppress(KeyError):
                REGISTRY.unregister(REGISTRY._names_to_collectors["fastapi_app_info_info"])

            app_info = Info("fastapi_app_info", "FastAPI application information")
            app_info.info(
                {
                    "app_name": self.settings.app_name,
                    "app_version": self.settings.app_version,
                    "python_version": platform.python_version(),
                    "fastapi_version": fastapi.__version__,
                }
            )

            self.app.add_middleware(
                PrometheusMiddleware,
                app_name=self.settings.app_name,
                prefix=self.settings.metrics_prefix,
                group_paths=False,
                optional_metrics=[response_body_size, request_body_size],
                skip_paths=[
                    self.settings.health_check_path,
                    self.settings.readiness_check_path,
                    METRICS_PATH,
                ],
                skip_methods=["OPTIONS"],
            )
            self.app.add_route(METRICS_PATH, handle_metrics)
            self.logger.info("Prometheus metrics configured successfully")
        except ImportError:
            self.logger.warning(
                "Prometheus dependencies not installed. "
                "Install with: pip install prometheus-client starlette-exporter"
            )
        except Exception as exc:
            self.logger.exception("Failed to configure metrics: %s", exc)
            raise

        return self

    def setup_error_handlers(self) -> Self:
        """Register global exception handlers."""
        try:
            ErrorHandler(self.app, self.logger).register_default_handlers()
            self.logger.info("Error handlers registered successfully")
        except Exception as exc:
            self.logger.exception("Failed to register error handlers: %s", exc)
            raise
        return self

    def setup_routes(self) -> Self:
        """Register infrastructure and example API routes."""
        self.app.include_router(create_health_router(self.settings))
        self.app.include_router(api_router)
        self.logger.info("Application routes registered successfully")
        return self

    def setup_middleware(self) -> Self:
        """
        Configure the middleware stack.

        Starlette applies middleware in reverse registration order, so the
        last middleware added here will be the first one to process requests.
        """
        try:
            # Timeout stays closest to the handler so outer middleware can still
            # observe and annotate timeout responses consistently.
            self.app.add_middleware(
                TimeoutMiddleware,
                timeout=self.settings.request_timeout,
            )
            # Body limits run before auth/handler logic to reject oversized
            # requests as early as possible.
            self.app.add_middleware(
                BodySizeLimitMiddleware,
                max_request_body_bytes=self.settings.max_request_body_bytes,
            )
            if self.settings.rate_limit_enabled:
                # Rate limiting remains inside request ID/logging wrappers so
                # rejected requests still receive correlation headers and
                # access-style request logs.
                self.app.add_middleware(
                    RateLimitMiddleware,
                    limit=self.settings.rate_limit_requests,
                    window_seconds=self.settings.rate_limit_window_seconds,
                    key_strategy=self.settings.rate_limit_key_strategy,
                    storage_url=self.settings.rate_limit_storage_url,
                    trust_proxy_headers=self.settings.rate_limit_trust_proxy_headers,
                    proxy_headers=self.settings.rate_limit_proxy_headers,
                    trusted_proxies=self.settings.rate_limit_trusted_proxies,
                    exempt_paths=[
                        self.settings.health_check_path,
                        self.settings.readiness_check_path,
                        METRICS_PATH,
                        "/favicon.ico",
                    ],
                )
            # Request identity and request logging stay outside the rate limiter
            # so 429s still get correlation headers and one structured log.
            self.app.add_middleware(RequestIDMiddleware)
            self.app.add_middleware(
                RequestLoggingMiddleware, redact_headers=self.settings.log_redact_headers
            )
            if self.settings.security_headers_enabled:
                # Security headers are added late so they are applied to both
                # success and error responses.
                self.app.add_middleware(
                    SecurityHeadersMiddleware,
                    hsts_enabled=self.settings.security_hsts_enabled,
                    hsts_max_age_seconds=self.settings.security_hsts_max_age_seconds,
                    referrer_policy=self.settings.security_referrer_policy,
                    permissions_policy=self.settings.security_permissions_policy,
                    content_security_policy=self.settings.security_content_security_policy,
                    trust_proxy_proto_header=self.settings.security_trust_proxy_proto_header,
                    trusted_proxies=self.settings.security_trusted_proxies,
                )
            # Host validation stays on by default; local/test hosts are part of
            # the default settings so development still works without widening
            # the acceptance policy to "*".
            self.app.add_middleware(
                TrustedHostMiddleware,
                allowed_hosts=self.settings.trusted_hosts,
            )
            # CORS is outermost so preflight requests are handled before auth,
            # rate limiting, or route logic.
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=self.settings.cors_allowed_origins,
                allow_credentials=self.settings.cors_allow_credentials,
                allow_methods=self.settings.cors_allowed_methods,
                allow_headers=self.settings.cors_allowed_headers,
                expose_headers=self.settings.cors_expose_headers,
            )
            self.logger.info("Middleware stack configured successfully")
        except Exception as exc:
            self.logger.exception("Failed to configure middleware: %s", exc)
            raise
        return self

    def build(self) -> FastAPI:
        """Finalize the configuration and return the FastAPI instance."""
        self.logger.info(
            "%s v%s built successfully",
            self.settings.app_name,
            self.settings.app_version,
        )
        return self.app


def _ready(app: FastAPI) -> ReadinessCheckResult:
    """Return the always-on application readiness check."""
    _ = app
    return ReadinessCheckResult.ok("application")
