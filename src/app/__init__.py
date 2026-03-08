"""
FastAPI Application Factory.

Provides the `create_app()` factory function — the single entry point
for creating a fully configured FastAPI application.

Why a factory function instead of module-level instantiation?

1. **Testability**: Tests can call `create_app()` with different settings
   (test config, staging config, metrics disabled) without monkeypatching.

2. **Explicit lifecycle**: The creation order is visible and intentional.
   Settings first, then logging, then everything else. No hidden
   initialization on import.

3. **Multiple instances**: Need two instances with different configs in
   the same process for integration testing? Factory makes it trivial.
   Module-level singletons make it impossible.

Usage:
    from app import create_app
    app = create_app()

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging

from fastapi import FastAPI

from .logging_setup import configure_root_logging
from .settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Factory method to create and configure the FastAPI application.

    Orchestrates the builder chain to produce a fully configured,
    production-ready FastAPI instance.

    Args:
        settings: Optional settings override. Loads from environment
                  variables and .env file if None.

    Returns:
        A fully configured FastAPI application ready to serve requests.
    """
    settings = settings or Settings()
    from .app_builder import FastAPIAppBuilder

    configure_root_logging(settings)
    logger = logging.getLogger(settings.app_name)

    # Keep the bootstrap path explicit so changes to app wiring stay easy to
    # review, test, and reason about.
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

    return app
