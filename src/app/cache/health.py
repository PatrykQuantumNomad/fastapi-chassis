"""
Cache readiness check.
"""

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI

from ..readiness import ReadinessCheckResult

if TYPE_CHECKING:
    from .store import CacheStore


async def check_cache_readiness(app: FastAPI) -> ReadinessCheckResult:
    """Run a lightweight readiness ping against the configured cache store."""
    store = cast("CacheStore | None", getattr(app.state, "cache_store", None))
    settings = app.state.settings

    if store is None:
        return ReadinessCheckResult.error("cache", "Cache store not initialized")

    start = perf_counter()
    try:
        async with asyncio.timeout(settings.cache_health_timeout_seconds):
            await store.ping()
    except TimeoutError:
        latency_ms = (perf_counter() - start) * 1000
        return ReadinessCheckResult.error(
            "cache",
            "Timed out while checking cache connectivity",
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (perf_counter() - start) * 1000
        return ReadinessCheckResult.error(
            "cache",
            f"Cache check failed: {exc!s}",
            latency_ms=latency_ms,
        )

    latency_ms = (perf_counter() - start) * 1000
    return ReadinessCheckResult.ok("cache", latency_ms=latency_ms)
