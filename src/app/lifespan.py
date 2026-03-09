"""
Application lifespan management.

Handles startup and shutdown lifecycle events using FastAPI's modern
context manager approach (replacing the deprecated @app.on_event decorators).

The lifespan owns long-lived resources shared across requests: the database
engine/session factory, the shared HTTP client, and the auth service that may
warm its JWKS cache on startup.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .auth import JWTAuthService
from .cache import create_cache_store
from .db import create_database_engine, create_session_factory
from .observability import instrument_database_engine
from .settings import Settings


class LifespanManager:
    """
    Manages the application startup and shutdown lifecycle.

    The lifespan context manager ensures resources are properly initialized
    before the first request and cleaned up when the application shuts down.
    """

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        """Store settings and logger used during startup/shutdown orchestration."""
        self.settings = settings
        self.logger = logger

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None]:
        """
        Application lifespan context manager.

        Everything before `yield` runs on startup.
        Everything after `yield` runs on shutdown.
        """
        self.logger.info(
            "Starting %s v%s",
            self.settings.app_name,
            self.settings.app_version,
        )

        # Database resources are created once at startup and stored on app.state
        # so request dependencies can reuse them without re-initialization.
        app.state.db_engine = create_database_engine(self.settings)
        app.state.db_session_factory = create_session_factory(self.settings, app.state.db_engine)
        instrument_database_engine(app.state.db_engine, self.settings)

        # The shared HTTP client supports JWKS retrieval and future outbound
        # service integrations without recreating clients per request.
        app.state.http_client = httpx.AsyncClient(
            timeout=self.settings.auth_http_timeout_seconds,
            follow_redirects=False,
        )
        app.state.auth_service = JWTAuthService(self.settings, app.state.http_client)
        # Warm the auth service during startup so readiness reflects any remote
        # JWKS dependencies before traffic begins.  When auth_require_warmup is
        # true, a failed warm-up terminates the process so traffic never arrives
        # at an instance that cannot validate tokens.
        try:
            await app.state.auth_service.warm_up()
        except Exception as exc:
            if self.settings.auth_require_warmup:
                self.logger.error(
                    "Auth warm-up failed and APP_AUTH_REQUIRE_WARMUP=true; aborting startup: %s",
                    exc,
                )
                raise
            self.logger.warning(
                "Auth warm-up failed during startup; continuing with degraded readiness: %s",
                exc,
            )

        # Initialise the cache store when caching is enabled so the
        # readiness probe can report its availability before traffic arrives.
        if self.settings.cache_enabled:
            app.state.cache_store = create_cache_store(self.settings)
            try:
                await app.state.cache_store.ping()
            except Exception as exc:
                self.logger.warning(
                    "Cache warm-up failed during startup; continuing with degraded readiness: %s",
                    exc,
                )

        self.logger.info("Application startup complete")

        try:
            yield
        finally:
            self.logger.info("Initiating graceful shutdown...")
            # Close the cache store before the database engine so pending
            # cache writes complete while the DB is still available.
            if getattr(app.state, "cache_store", None) is not None:
                await app.state.cache_store.close()
            # Shutdown mirrors startup order: close network clients first, then
            # dispose the database engine after outstanding work has finished.
            await app.state.http_client.aclose()
            await app.state.db_engine.dispose()
            self.logger.info("Shutdown complete")
