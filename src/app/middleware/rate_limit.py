"""
Configurable request rate limiting middleware.
"""

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..utils import TrustedProxyNetwork, get_forwarded_client_ip, parse_trusted_proxies


@dataclass(slots=True)
class RateLimitDecision:
    """Result of a rate-limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at_epoch: int


class RateLimitStore(ABC):
    """Abstract store used by the rate limiting middleware."""

    @abstractmethod
    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        """Record a hit and return whether the request is allowed."""


class MemoryRateLimitStore(RateLimitStore):
    """In-memory fixed-window rate limiting store."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, int]] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = int(time.time())
        bucket = now // window_seconds
        self._prune_expired_buckets(bucket)
        bucket_key = f"{key}:{bucket}"
        current_bucket, current_count = self._buckets.get(bucket_key, (bucket, 0))
        if current_bucket != bucket:
            current_count = 0

        current_count += 1
        self._buckets[bucket_key] = (bucket, current_count)
        allowed = current_count <= limit
        remaining = max(limit - current_count, 0)
        reset_at = (bucket + 1) * window_seconds
        return RateLimitDecision(allowed, limit, remaining, reset_at)

    def _prune_expired_buckets(self, current_bucket: int) -> None:
        expired_keys = [
            bucket_key
            for bucket_key, (bucket, _) in self._buckets.items()
            if bucket < current_bucket
        ]
        for bucket_key in expired_keys:
            self._buckets.pop(bucket_key, None)


class RedisRateLimitStore(RateLimitStore):
    """Redis-backed fixed-window rate limiting store."""

    def __init__(self, storage_url: str) -> None:
        try:
            from redis import asyncio as redis_asyncio
        except ImportError:
            raise ImportError(
                "The 'redis' package is required for Redis-backed rate limiting. "
                "Install it with: uv sync --extra redis"
            ) from None
        self._redis_asyncio = redis_asyncio
        self._client = redis_asyncio.from_url(storage_url, encoding="utf-8", decode_responses=True)

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = int(time.time())
        bucket = now // window_seconds
        reset_at = (bucket + 1) * window_seconds
        redis_key = f"rate_limit:{bucket}:{key}"

        count = await self._client.incr(redis_key)
        if count == 1:
            await self._client.expire(redis_key, window_seconds)

        remaining = max(limit - count, 0)
        return RateLimitDecision(count <= limit, limit, remaining, reset_at)


class RateLimitMiddleware:
    """Apply request rate limiting before the route handler executes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window_seconds: int,
        key_strategy: str,
        storage_url: str,
        trust_proxy_headers: bool,
        proxy_headers: list[str],
        trusted_proxies: list[str],
        exempt_paths: list[str],
    ) -> None:
        self.app = app
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_strategy = key_strategy
        self.trust_proxy_headers = trust_proxy_headers
        self.proxy_headers = [header.lower() for header in proxy_headers]
        self.trusted_proxies = parse_trusted_proxies(trusted_proxies)
        self.exempt_paths = set(exempt_paths)
        self.store: RateLimitStore
        if storage_url:
            self.store = RedisRateLimitStore(storage_url)
        else:
            self.store = MemoryRateLimitStore()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        key = _build_rate_limit_key(
            scope,
            self.key_strategy,
            trust_proxy_headers=self.trust_proxy_headers,
            proxy_headers=self.proxy_headers,
            trusted_proxies=self.trusted_proxies,
        )
        decision = await self.store.hit(key, self.limit, self.window_seconds)
        if not decision.allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "detail": "Request rate limit exceeded",
                    "retry_after_seconds": max(decision.reset_at_epoch - int(time.time()), 0),
                },
                headers=_decision_headers(decision),
            )
            await response(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                for key_name, value in _decision_headers(decision).items():
                    headers[key_name] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _build_rate_limit_key(
    scope: Scope,
    key_strategy: str,
    *,
    trust_proxy_headers: bool,
    proxy_headers: list[str],
    trusted_proxies: tuple[TrustedProxyNetwork, ...],
) -> str:
    headers = Headers(raw=scope.get("headers", []))
    if key_strategy == "authorization":
        authorization = headers.get("authorization")
        if authorization:
            # Normalize: strip the Bearer scheme prefix so casing/whitespace
            # differences in the scheme do not produce distinct rate-limit keys.
            token = authorization
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            return f"authorization:{digest}"

    client = scope.get("client")
    client_host = client[0] if client else "unknown"

    if trust_proxy_headers and _is_trusted_proxy(client_host, trusted_proxies):
        forwarded_ip = get_forwarded_client_ip(headers, proxy_headers, trusted_proxies)
        if forwarded_ip:
            return f"ip:{forwarded_ip}"

    return f"ip:{client_host}"


def _decision_headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_at_epoch),
        "Retry-After": str(max(decision.reset_at_epoch - int(time.time()), 0)),
    }


def _is_trusted_proxy(client_host: str, trusted_proxies: tuple[TrustedProxyNetwork, ...]) -> bool:
    from ..utils import is_trusted_proxy

    return is_trusted_proxy(client_host, trusted_proxies)
