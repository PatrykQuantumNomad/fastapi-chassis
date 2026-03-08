"""
Database readiness checks.

The default path is a lightweight SQLite ping so the template stays
workable without extra infrastructure.
"""

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from sqlalchemy import text

from ..readiness import ReadinessCheckResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


async def check_database_readiness(app: FastAPI) -> ReadinessCheckResult:
    """Run a lightweight readiness ping against the configured database."""
    engine = cast("AsyncEngine | None", getattr(app.state, "db_engine", None))
    settings = app.state.settings

    if engine is None:
        return ReadinessCheckResult.error("database", "Database engine not initialized")

    start = perf_counter()
    try:
        async with asyncio.timeout(settings.database_health_timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except TimeoutError:
        latency_ms = (perf_counter() - start) * 1000
        return ReadinessCheckResult.error(
            "database",
            "Timed out while checking database connectivity",
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (perf_counter() - start) * 1000
        return ReadinessCheckResult.error(
            "database",
            f"Database check failed: {exc!s}",
            latency_ms=latency_ms,
        )

    latency_ms = (perf_counter() - start) * 1000
    return ReadinessCheckResult.ok("database", latency_ms=latency_ms)
