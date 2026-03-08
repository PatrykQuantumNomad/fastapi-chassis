"""
Unit tests for the pluggable cache store backends.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import importlib.util
import sys
import time
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from app.cache.store import (
    CacheStore,
    MemoryCacheStore,
    RedisCacheStore,
    create_cache_store,
)
from tests.helpers import make_settings

_redis_available = importlib.util.find_spec("redis") is not None

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────
# MemoryCacheStore
# ──────────────────────────────────────────────


class TestMemoryCacheStore:
    """Tests for the in-process dict-based cache store."""

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(self) -> None:
        store = MemoryCacheStore()
        assert await store.get("missing") is None

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self) -> None:
        store = MemoryCacheStore()
        await store.set("key", b"value", ttl_seconds=60)
        assert await store.get("key") == b"value"

    @pytest.mark.asyncio
    async def test_get_returns_none_after_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MemoryCacheStore()
        # Use a deterministic monotonic clock.
        times = [100.0, 100.0, 200.0]
        call_count = 0
        real_monotonic = time.monotonic

        def fake_monotonic() -> float:
            nonlocal call_count
            if call_count < len(times):
                val = times[call_count]
                call_count += 1
                return val
            return real_monotonic()

        monkeypatch.setattr(time, "monotonic", fake_monotonic)

        await store.set("key", b"value", ttl_seconds=10)
        # First get at t=100 is within TTL (set at 100, expires at 110).
        assert await store.get("key") == b"value"
        # Second get at t=200 is past expiry.
        assert await store.get("key") is None

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self) -> None:
        store = MemoryCacheStore()
        await store.set("key", b"value", ttl_seconds=60)
        await store.delete("key")
        assert await store.get("key") is None

    @pytest.mark.asyncio
    async def test_delete_missing_key_does_not_raise(self) -> None:
        store = MemoryCacheStore()
        await store.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_exists_true_for_present_key(self) -> None:
        store = MemoryCacheStore()
        await store.set("key", b"value", ttl_seconds=60)
        assert await store.exists("key") is True

    @pytest.mark.asyncio
    async def test_exists_false_for_missing_key(self) -> None:
        store = MemoryCacheStore()
        assert await store.exists("missing") is False

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self) -> None:
        store = MemoryCacheStore()
        await store.set("a", b"1", ttl_seconds=60)
        await store.set("b", b"2", ttl_seconds=60)
        await store.clear()
        assert await store.get("a") is None
        assert await store.get("b") is None

    @pytest.mark.asyncio
    async def test_ping_returns_true(self) -> None:
        store = MemoryCacheStore()
        assert await store.ping() is True

    @pytest.mark.asyncio
    async def test_close_clears_data(self) -> None:
        store = MemoryCacheStore()
        await store.set("key", b"value", ttl_seconds=60)
        await store.close()
        assert await store.get("key") is None

    @pytest.mark.asyncio
    async def test_evicts_oldest_when_max_entries_reached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0

        def advancing_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            return float(call_count)

        monkeypatch.setattr(time, "monotonic", advancing_monotonic)

        store = MemoryCacheStore(max_entries=2)
        await store.set("first", b"1", ttl_seconds=1000)
        await store.set("second", b"2", ttl_seconds=1000)
        # This should evict "first" (earliest expiry).
        await store.set("third", b"3", ttl_seconds=1000)

        assert await store.get("first") is None
        assert await store.get("second") == b"2"
        assert await store.get("third") == b"3"

    @pytest.mark.asyncio
    async def test_overwrite_existing_key_does_not_evict(self) -> None:
        store = MemoryCacheStore(max_entries=2)
        await store.set("a", b"1", ttl_seconds=60)
        await store.set("b", b"2", ttl_seconds=60)
        # Overwriting "a" should not trigger eviction.
        await store.set("a", b"updated", ttl_seconds=60)
        assert await store.get("a") == b"updated"
        assert await store.get("b") == b"2"


# ──────────────────────────────────────────────
# RedisCacheStore
# ──────────────────────────────────────────────


@pytest.mark.skipif(not _redis_available, reason="redis package not installed")
class TestRedisCacheStore:
    """Tests for the Redis-backed cache store with a mocked client."""

    @pytest.fixture
    def fake_redis(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        client = AsyncMock()
        from_url = Mock(return_value=client)
        monkeypatch.setattr("redis.asyncio.from_url", from_url)
        return client

    @pytest.mark.asyncio
    async def test_get_returns_cached_value(self, fake_redis: AsyncMock) -> None:
        fake_redis.get = AsyncMock(return_value=b"hello")
        store = RedisCacheStore("redis://localhost:6379/1")
        assert await store.get("key") == b"hello"
        fake_redis.get.assert_awaited_once_with("cache:key")

    @pytest.mark.asyncio
    async def test_get_encodes_string_response_as_bytes(self, fake_redis: AsyncMock) -> None:
        fake_redis.get = AsyncMock(return_value="string-value")
        store = RedisCacheStore("redis://localhost:6379/1")
        result = await store.get("key")
        assert result == b"string-value"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(self, fake_redis: AsyncMock) -> None:
        fake_redis.get = AsyncMock(return_value=None)
        store = RedisCacheStore("redis://localhost:6379/1")
        assert await store.get("missing") is None

    @pytest.mark.asyncio
    async def test_set_calls_setex(self, fake_redis: AsyncMock) -> None:
        fake_redis.setex = AsyncMock()
        store = RedisCacheStore("redis://localhost:6379/1")
        await store.set("key", b"value", ttl_seconds=300)
        fake_redis.setex.assert_awaited_once_with("cache:key", 300, b"value")

    @pytest.mark.asyncio
    async def test_delete_calls_redis_delete(self, fake_redis: AsyncMock) -> None:
        fake_redis.delete = AsyncMock()
        store = RedisCacheStore("redis://localhost:6379/1")
        await store.delete("key")
        fake_redis.delete.assert_awaited_once_with("cache:key")

    @pytest.mark.asyncio
    async def test_exists_returns_true_when_key_present(self, fake_redis: AsyncMock) -> None:
        fake_redis.exists = AsyncMock(return_value=1)
        store = RedisCacheStore("redis://localhost:6379/1")
        assert await store.exists("key") is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_when_key_absent(self, fake_redis: AsyncMock) -> None:
        fake_redis.exists = AsyncMock(return_value=0)
        store = RedisCacheStore("redis://localhost:6379/1")
        assert await store.exists("absent") is False

    @pytest.mark.asyncio
    async def test_clear_calls_flushdb(self, fake_redis: AsyncMock) -> None:
        fake_redis.flushdb = AsyncMock()
        store = RedisCacheStore("redis://localhost:6379/1")
        await store.clear()
        fake_redis.flushdb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ping_calls_redis_ping(self, fake_redis: AsyncMock) -> None:
        fake_redis.ping = AsyncMock(return_value=True)
        store = RedisCacheStore("redis://localhost:6379/1")
        assert await store.ping() is True

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self, fake_redis: AsyncMock) -> None:
        fake_redis.aclose = AsyncMock()
        store = RedisCacheStore("redis://localhost:6379/1")
        await store.close()
        fake_redis.aclose.assert_awaited_once()

    def test_custom_key_prefix(self, fake_redis: AsyncMock) -> None:
        store = RedisCacheStore("redis://localhost:6379/1", key_prefix="myapp:")
        assert store._prefixed("test") == "myapp:test"

    def test_raises_import_error_when_redis_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saved = sys.modules.pop("redis", None)
        saved_asyncio = sys.modules.pop("redis.asyncio", None)
        monkeypatch.setitem(sys.modules, "redis", None)

        try:
            with pytest.raises(ImportError, match="redis"):
                RedisCacheStore("redis://localhost:6379/1")
        finally:
            sys.modules.pop("redis", None)
            if saved is not None:
                sys.modules["redis"] = saved
            if saved_asyncio is not None:
                sys.modules["redis.asyncio"] = saved_asyncio


# ──────────────────────────────────────────────
# create_cache_store factory
# ──────────────────────────────────────────────


class TestCreateCacheStore:
    """Tests for the cache store factory function."""

    def test_memory_backend_returns_memory_store(self) -> None:
        settings = make_settings(cache_enabled=True, cache_backend="memory")
        store = create_cache_store(settings)
        assert isinstance(store, MemoryCacheStore)

    def test_memory_store_respects_max_entries(self) -> None:
        settings = make_settings(cache_enabled=True, cache_backend="memory", cache_max_entries=500)
        store = create_cache_store(settings)
        assert isinstance(store, MemoryCacheStore)
        assert store.max_entries == 500

    @pytest.mark.skipif(not _redis_available, reason="redis package not installed")
    def test_redis_backend_returns_redis_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = AsyncMock()
        from_url = Mock(return_value=fake_client)
        monkeypatch.setattr("redis.asyncio.from_url", from_url)

        settings = make_settings(
            cache_enabled=True,
            cache_backend="redis",
            cache_storage_url="redis://localhost:6379/1",
        )
        store = create_cache_store(settings)
        assert isinstance(store, RedisCacheStore)

    def test_abstract_base_class_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            CacheStore()  # type: ignore[abstract]


# ──────────────────────────────────────────────
# check_cache_readiness
# ──────────────────────────────────────────────


class TestCheckCacheReadiness:
    """Tests for the cache readiness health check."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_ping_succeeds(self) -> None:
        from app.cache.health import check_cache_readiness

        app = FastAPI()
        app.state.settings = make_settings(cache_enabled=True, cache_health_timeout_seconds=2)
        store = MemoryCacheStore()
        app.state.cache_store = store

        result = await check_cache_readiness(app)
        assert result.is_healthy is True
        assert result.name == "cache"

    @pytest.mark.asyncio
    async def test_returns_error_when_store_is_none(self) -> None:
        from app.cache.health import check_cache_readiness

        app = FastAPI()
        app.state.settings = make_settings(cache_enabled=True, cache_health_timeout_seconds=2)
        app.state.cache_store = None

        result = await check_cache_readiness(app)
        assert result.is_healthy is False
        assert "not initialized" in result.detail

    @pytest.mark.asyncio
    async def test_returns_error_on_ping_timeout(self) -> None:
        from app.cache.health import check_cache_readiness

        app = FastAPI()
        app.state.settings = make_settings(cache_enabled=True, cache_health_timeout_seconds=1)

        store = AsyncMock(spec=MemoryCacheStore)
        store.ping = AsyncMock(side_effect=TimeoutError)
        app.state.cache_store = store

        result = await check_cache_readiness(app)
        assert result.is_healthy is False
        assert "Timed out" in result.detail

    @pytest.mark.asyncio
    async def test_returns_error_on_ping_exception(self) -> None:
        from app.cache.health import check_cache_readiness

        app = FastAPI()
        app.state.settings = make_settings(cache_enabled=True, cache_health_timeout_seconds=2)

        store = AsyncMock(spec=MemoryCacheStore)
        store.ping = AsyncMock(side_effect=ConnectionError("refused"))
        app.state.cache_store = store

        result = await check_cache_readiness(app)
        assert result.is_healthy is False
        assert "refused" in result.detail
