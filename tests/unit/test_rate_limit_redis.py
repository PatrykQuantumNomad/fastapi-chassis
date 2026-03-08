"""Unit tests for the Redis-backed rate limit store.

These tests mock the Redis client to validate the store's logic for key
management, expiry, and decision semantics without requiring a running Redis
instance.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from app.middleware.rate_limit import RedisRateLimitStore

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Provide a mocked Redis client that RedisRateLimitStore will use."""
    client = AsyncMock()
    client.incr = AsyncMock(side_effect=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    client.expire = AsyncMock()
    from_url = Mock(return_value=client)
    monkeypatch.setattr("redis.asyncio.from_url", from_url)
    return client


class TestRedisRateLimitStore:
    """Tests for RedisRateLimitStore logic."""

    @pytest.mark.asyncio
    async def test_first_hit_sets_expiry(self, fake_redis: AsyncMock) -> None:
        store = RedisRateLimitStore("redis://localhost:6379/0")
        decision = await store.hit("ip:127.0.0.1", limit=10, window_seconds=60)

        assert decision.allowed is True
        assert decision.remaining == 9
        fake_redis.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subsequent_hit_does_not_set_expiry_again(self, fake_redis: AsyncMock) -> None:
        store = RedisRateLimitStore("redis://localhost:6379/0")
        await store.hit("ip:127.0.0.1", limit=10, window_seconds=60)
        await store.hit("ip:127.0.0.1", limit=10, window_seconds=60)

        assert fake_redis.expire.await_count == 1

    @pytest.mark.asyncio
    async def test_exceeding_limit_returns_not_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncMock()
        client.incr = AsyncMock(side_effect=[1, 2, 3])
        client.expire = AsyncMock()
        from_url = Mock(return_value=client)
        monkeypatch.setattr("redis.asyncio.from_url", from_url)

        store = RedisRateLimitStore("redis://localhost:6379/0")
        d1 = await store.hit("ip:10.0.0.1", limit=2, window_seconds=60)
        d2 = await store.hit("ip:10.0.0.1", limit=2, window_seconds=60)
        d3 = await store.hit("ip:10.0.0.1", limit=2, window_seconds=60)

        assert d1.allowed is True
        assert d2.allowed is True
        assert d3.allowed is False
        assert d3.remaining == 0

    @pytest.mark.asyncio
    async def test_decision_includes_correct_limit(self, fake_redis: AsyncMock) -> None:
        store = RedisRateLimitStore("redis://localhost:6379/0")
        decision = await store.hit("ip:10.0.0.1", limit=100, window_seconds=30)

        assert decision.limit == 100

    @pytest.mark.asyncio
    async def test_reset_at_is_end_of_window(
        self, fake_redis: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: 120)
        store = RedisRateLimitStore("redis://localhost:6379/0")
        decision = await store.hit("ip:10.0.0.1", limit=10, window_seconds=60)

        assert decision.reset_at_epoch == 180
