"""
Configurable cache layer with pluggable backends.

Reexports the public API so consumers can write::

    from app.cache import CacheStore, get_cache
"""

from .dependencies import get_cache
from .health import check_cache_readiness
from .store import CacheStore, MemoryCacheStore, RedisCacheStore, create_cache_store

__all__ = [
    "CacheStore",
    "MemoryCacheStore",
    "RedisCacheStore",
    "check_cache_readiness",
    "create_cache_store",
    "get_cache",
]
