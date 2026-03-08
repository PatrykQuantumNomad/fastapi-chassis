"""
FastAPI cache dependency helpers.
"""

from typing import cast

from fastapi import Request

from .store import CacheStore


def get_cache(request: Request) -> CacheStore:
    """Return the configured cache store from application state."""
    return cast("CacheStore", request.app.state.cache_store)
