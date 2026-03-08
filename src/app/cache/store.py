"""
Pluggable cache store backends.

Provides an abstract base class and two concrete implementations:

- **MemoryCacheStore**: In-process dict-based cache with TTL and max-entry
  eviction.  Suitable for single-process deployments and local development.
- **RedisCacheStore**: Distributed cache backed by Redis with native TTL
  support.  Suitable for multi-process and multi-instance deployments.
"""

import time
from abc import ABC, abstractmethod

from ..settings import Settings


class CacheStore(ABC):
    """Abstract cache store used by the application."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Return the cached value for *key*, or ``None`` if absent/expired."""

    @abstractmethod
    async def set(self, key: str, value: bytes, *, ttl_seconds: int) -> None:
        """Store *value* under *key* with a TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove *key* from the cache."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* is present and not expired."""

    @abstractmethod
    async def clear(self) -> None:
        """Remove all entries from this cache store."""

    @abstractmethod
    async def ping(self) -> bool:
        """Lightweight connectivity check used by the readiness probe."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the store (connections, memory)."""


class MemoryCacheStore(CacheStore):
    """In-process cache with passive TTL expiry and max-entry eviction."""

    def __init__(self, *, max_entries: int = 10_000) -> None:
        self.max_entries = max_entries
        # key → (value, expiry_timestamp)
        self._data: dict[str, tuple[bytes, float]] = {}

    async def get(self, key: str) -> bytes | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.monotonic() >= expiry:
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: bytes, *, ttl_seconds: int) -> None:
        if len(self._data) >= self.max_entries and key not in self._data:
            self._evict_oldest()
        self._data[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def clear(self) -> None:
        self._data.clear()

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._data.clear()

    def _evict_oldest(self) -> None:
        """Remove the entry with the earliest expiry timestamp."""
        if not self._data:
            return
        oldest_key = min(self._data, key=lambda k: self._data[k][1])
        self._data.pop(oldest_key, None)


class RedisCacheStore(CacheStore):
    """Redis-backed distributed cache store."""

    def __init__(self, storage_url: str, *, key_prefix: str = "cache:") -> None:
        try:
            from redis import asyncio as redis_asyncio
        except ImportError:
            raise ImportError(
                "The 'redis' package is required for Redis-backed caching. "
                "Install it with: uv sync --extra redis"
            ) from None
        self._client = redis_asyncio.from_url(storage_url, encoding="utf-8", decode_responses=False)
        self._key_prefix = key_prefix

    def _prefixed(self, key: str) -> str:
        return f"{self._key_prefix}{key}"

    async def get(self, key: str) -> bytes | None:
        value = await self._client.get(self._prefixed(key))
        if value is None:
            return None
        return value if isinstance(value, bytes) else value.encode("utf-8")

    async def set(self, key: str, value: bytes, *, ttl_seconds: int) -> None:
        await self._client.setex(self._prefixed(key), ttl_seconds, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._prefixed(key))

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(self._prefixed(key)))

    async def clear(self) -> None:
        await self._client.flushdb()

    async def ping(self) -> bool:
        return bool(await self._client.ping())  # type: ignore[misc]

    async def close(self) -> None:
        await self._client.aclose()


def create_cache_store(settings: Settings) -> CacheStore:
    """Instantiate a cache store based on the application settings."""
    if settings.cache_backend == "redis":
        return RedisCacheStore(
            settings.cache_storage_url,
            key_prefix=settings.cache_key_prefix,
        )
    return MemoryCacheStore(max_entries=settings.cache_max_entries)
