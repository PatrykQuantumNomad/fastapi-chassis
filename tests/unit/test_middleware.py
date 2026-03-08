"""
Unit tests for custom middleware components.

Tests middleware logic in isolation — constructor behaviour and dispatch
semantics — using minimal ASGI apps instead of the full application stack.
Full-stack middleware tests live in tests/integration/test_app.py.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from ipaddress import ip_network
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers
from starlette.types import Message, Receive, Scope, Send

from app.log_config.request_context import get_correlation_id, get_request_id
from app.middleware.body_size import BodySizeLimitMiddleware
from app.middleware.rate_limit import (
    MemoryRateLimitStore,
    RateLimitDecision,
    RateLimitMiddleware,
    RedisRateLimitStore,
    _build_rate_limit_key,
    _decision_headers,
    _is_trusted_proxy,
)
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.timeout import TimeoutMiddleware
from app.utils import get_forwarded_client_ip

if TYPE_CHECKING:
    from starlette.types import ASGIApp

pytestmark = pytest.mark.unit


def _minimal_app() -> FastAPI:
    """Bare FastAPI with a single endpoint — no builder, no settings."""
    app = FastAPI()

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"ok": "true"}

    return app


class TestRequestIDMiddleware:
    """Tests for the request ID injection middleware."""

    @pytest.fixture
    def app(self) -> FastAPI:
        app = _minimal_app()
        app.add_middleware(RequestIDMiddleware)
        return app

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_generates_uuid_when_absent(self, client: AsyncClient) -> None:
        response = await client.get("/")
        rid = response.headers["x-request-id"]
        assert len(rid) == 36
        assert rid.count("-") == 4

    @pytest.mark.asyncio
    async def test_generates_new_request_id_when_request_id_provided(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/", headers={"X-Request-ID": "my-trace-id"})
        assert response.headers["x-request-id"] != "my-trace-id"
        assert len(response.headers["x-request-id"]) == 36
        assert response.headers["x-correlation-id"] == "my-trace-id"

    @pytest.mark.asyncio
    async def test_uses_correlation_id_header_when_request_id_absent(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/", headers={"X-Correlation-ID": "corr-123"})
        assert response.headers["x-request-id"] != "corr-123"
        assert len(response.headers["x-request-id"]) == 36
        assert response.headers["x-correlation-id"] == "corr-123"

    @pytest.mark.asyncio
    async def test_unique_ids_per_request(self, client: AsyncClient) -> None:
        r1 = await client.get("/")
        r2 = await client.get("/")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]

    @pytest.mark.asyncio
    async def test_tracing_ids_available_in_context(self) -> None:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/rid")
        async def rid() -> dict[str, str]:
            return {
                "request_id": get_request_id(),
                "correlation_id": get_correlation_id(),
            }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/rid", headers={"X-Request-ID": "ctx-id"})

        assert response.status_code == 200
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert response.json()["request_id"] != "ctx-id"
        assert response.json()["correlation_id"] == "ctx-id"

    @pytest.mark.asyncio
    async def test_request_context_resets_after_request(self, client: AsyncClient) -> None:
        await client.get("/", headers={"X-Request-ID": "cleanup-test"})
        assert get_request_id() == "-"
        assert get_correlation_id() == "-"

    def test_header_name_constant(self) -> None:
        assert RequestIDMiddleware.HEADER_NAME == "X-Request-ID"
        assert RequestIDMiddleware.CORRELATION_HEADER_NAME == "X-Correlation-ID"

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        called = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal called
            called = True
            await receive()

        middleware = RequestIDMiddleware(app)

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "websocket.connect"}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware({"type": "websocket"}, receive, send)

        assert called is True

    @pytest.mark.asyncio
    async def test_sets_span_attributes_when_recording(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attributes: dict[str, str] = {}

        class RecordingSpan:
            def is_recording(self) -> bool:
                return True

            def set_attribute(self, key: str, value: str) -> None:
                attributes[key] = value

        monkeypatch.setattr("app.middleware.request_id.get_current_span", lambda: RecordingSpan())
        app = _minimal_app()
        app.add_middleware(RequestIDMiddleware)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/", headers={"X-Correlation-ID": "corr-123"})

        assert attributes["app.request_id"] == response.headers["x-request-id"]
        assert attributes["app.correlation_id"] == "corr-123"

    def test_upsert_header_replaces_and_appends(self) -> None:
        headers = [(b"x-request-id", b"old")]
        RequestIDMiddleware._upsert_header(headers, b"x-request-id", b"new")
        RequestIDMiddleware._upsert_header(headers, b"x-correlation-id", b"corr")

        assert headers == [(b"x-request-id", b"new"), (b"x-correlation-id", b"corr")]


class TestTimeoutMiddleware:
    """Tests for the request timeout middleware."""

    def test_default_timeout(self) -> None:
        mw = TimeoutMiddleware(_minimal_app(), timeout=30)
        assert mw.timeout == 30

    def test_custom_timeout(self) -> None:
        mw = TimeoutMiddleware(_minimal_app(), timeout=60)
        assert mw.timeout == 60

    def test_stores_app_reference(self) -> None:
        app: ASGIApp = _minimal_app()
        mw = TimeoutMiddleware(app, timeout=10)
        assert mw.app is not None

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        called = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal called
            called = True
            await receive()

        middleware = TimeoutMiddleware(app, timeout=30)

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "websocket.connect"}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware({"type": "websocket"}, receive, send)

        assert called is True

    @pytest.mark.asyncio
    async def test_fast_request_succeeds(self) -> None:
        app = _minimal_app()
        app.add_middleware(TimeoutMiddleware, timeout=2)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_slow_request_returns_504(self) -> None:
        app = FastAPI()
        app.add_middleware(TimeoutMiddleware, timeout=0.1)

        @app.get("/slow")
        async def slow() -> JSONResponse:
            await asyncio.sleep(0.3)
            return JSONResponse(content={"done": True})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/slow")

        assert response.status_code == 504
        data = response.json()
        assert data["error"] == "gateway_timeout"
        assert "0.1s" in data["detail"]
        assert "/slow" in data["path"]
        assert "?" not in data["path"]

    @pytest.mark.asyncio
    async def test_timeout_after_response_start_does_not_emit_second_response(self) -> None:
        messages: list[Message] = []

        async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await asyncio.sleep(0.3)

        middleware = TimeoutMiddleware(streaming_app, timeout=0.1)
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/stream",
            "raw_path": b"/stream",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)
            messages.append(message)

        await middleware(scope, receive, send)

        assert [message["type"] for message in messages] == [
            "http.response.start",
            "http.response.body",
        ]
        assert messages[-1]["more_body"] is False


class TestRequestLoggingMiddleware:
    """Tests for access-style request logging middleware."""

    @pytest.mark.asyncio
    async def test_logs_request_with_request_id(self, caplog: pytest.LogCaptureFixture) -> None:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/ok")
        async def ok() -> dict[str, str]:
            return {"ok": "true"}

        caplog.set_level(logging.INFO, logger="app.request")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ok", headers={"X-Request-ID": "rid-123"})

        assert response.status_code == 200
        assert any(
            (
                record.name == "app.request"
                and record.getMessage() == "http_request_completed"
                and getattr(record, "request_id", None) == response.headers["x-request-id"]
                and getattr(record, "correlation_id", None) == "rid-123"
                and getattr(record, "event", None) == "http.request.completed"
                and getattr(record, "http_method", None) == "GET"
                and getattr(record, "http_path", None) == "/ok"
                and getattr(record, "http_status_code", None) == 200
            )
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_logs_not_found_status(self, caplog: pytest.LogCaptureFixture) -> None:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(RequestLoggingMiddleware)

        caplog.set_level(logging.INFO, logger="app.request")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/missing")

        assert response.status_code == 404
        assert any(
            record.name == "app.request"
            and record.getMessage() == "http_request_completed"
            and getattr(record, "http_path", None) == "/missing"
            and getattr(record, "http_status_code", None) == 404
            and getattr(record, "outcome", None) == "client_error"
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_redacts_query_string_values(self, caplog: pytest.LogCaptureFixture) -> None:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/search")
        async def search() -> dict[str, str]:
            return {"ok": "true"}

        caplog.set_level(logging.INFO, logger="app.request")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/search?token=secret&page=2")

        assert response.status_code == 200
        assert any(
            getattr(record, "http_query", None) == "token=%5Bredacted%5D&page=%5Bredacted%5D"
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        called = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal called
            called = True
            await receive()

        middleware = RequestLoggingMiddleware(app)

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "websocket.connect"}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware({"type": "websocket"}, receive, send)

        assert called is True

    @pytest.mark.asyncio
    async def test_redacts_user_agent_and_referer_when_configured(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(RequestLoggingMiddleware, redact_headers=True)

        @app.get("/ok")
        async def ok() -> dict[str, str]:
            return {"ok": "true"}

        caplog.set_level(logging.INFO, logger="app.request")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get(
                "/ok",
                headers={"User-Agent": "secret-agent/1.0", "Referer": "https://private.site"},
            )

        log_records = [r for r in caplog.records if r.name == "app.request"]
        assert len(log_records) >= 1
        record = log_records[0]
        assert getattr(record, "user_agent", None) == "[redacted]"
        assert getattr(record, "referer", None) == "[redacted]"

    def test_request_logging_helpers_cover_invalid_values(self) -> None:
        assert RequestLoggingMiddleware._decode_header(None) == "-"
        assert RequestLoggingMiddleware._parse_ascii_int(None) is None
        assert RequestLoggingMiddleware._parse_ascii_int(b"not-a-number") is None
        assert RequestLoggingMiddleware._sanitize_query_string("") == ""

    @pytest.mark.asyncio
    async def test_ignores_invalid_response_content_length(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"x-request-id", b"rid-123"),
                        (b"x-correlation-id", b"corr-123"),
                        (b"content-length", b"invalid"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = RequestLoggingMiddleware(app)
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/invalid",
            "raw_path": b"/invalid",
            "query_string": b"",
            "headers": [(b"content-length", b"invalid")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }
        caplog.set_level(logging.INFO, logger="app.request")

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware(scope, receive, send)

        assert any(getattr(record, "response_bytes", None) is None for record in caplog.records)


class TestBodySizeLimitMiddleware:
    """Tests for request body size limiting."""

    @pytest.mark.asyncio
    async def test_rejects_large_request_via_content_length(self) -> None:
        app = _minimal_app()
        app.add_middleware(BodySizeLimitMiddleware, max_request_body_bytes=5)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/", content=b"123456")

        assert response.status_code == 413
        assert response.json()["error"] == "request_too_large"

    @pytest.mark.asyncio
    async def test_rejects_streamed_request_without_content_length(self) -> None:
        messages: list[Message] = []

        async def body_consuming_app(scope: Scope, receive: Receive, send: Send) -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                if not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = BodySizeLimitMiddleware(body_consuming_app, max_request_body_bytes=5)
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/upload",
            "raw_path": b"/upload",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request_messages = iter(
            [
                {"type": "http.request", "body": b"1234", "more_body": True},
                {"type": "http.request", "body": b"56", "more_body": False},
            ]
        )

        async def receive() -> Message:
            await asyncio.sleep(0)
            return next(request_messages)

        async def send(message: Message) -> None:
            await asyncio.sleep(0)
            messages.append(message)

        await middleware(scope, receive, send)
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 413

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        called = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal called
            called = True
            await receive()

        middleware = BodySizeLimitMiddleware(app, max_request_body_bytes=100)

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "websocket.connect"}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware({"type": "websocket"}, receive, send)

        assert called is True

    @pytest.mark.asyncio
    async def test_rejects_invalid_content_length_header(self) -> None:
        messages: list[Message] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = BodySizeLimitMiddleware(app, max_request_body_bytes=5)
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/upload",
            "raw_path": b"/upload",
            "query_string": b"",
            "headers": [(b"content-length", b"nope")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)
            messages.append(message)

        await middleware(scope, receive, send)

        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 400


class TestRateLimitMiddleware:
    """Tests for fixed-window rate limiting."""

    @pytest.mark.asyncio
    async def test_memory_store_limits_after_threshold(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            RateLimitMiddleware,
            limit=1,
            window_seconds=60,
            key_strategy="ip",
            storage_url="",
            trust_proxy_headers=False,
            proxy_headers=["X-Forwarded-For", "X-Real-IP"],
            trusted_proxies=[],
            exempt_paths=[],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/")
            second = await client.get("/")

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.headers["x-ratelimit-limit"] == "1"

    @pytest.mark.asyncio
    async def test_exempt_path_skips_rate_limit(self) -> None:
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            limit=1,
            window_seconds=60,
            key_strategy="ip",
            storage_url="",
            trust_proxy_headers=False,
            proxy_headers=["X-Forwarded-For", "X-Real-IP"],
            trusted_proxies=[],
            exempt_paths=["/healthcheck"],
        )

        @app.get("/healthcheck")
        async def healthcheck() -> dict[str, str]:
            return {"status": "ok"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/healthcheck")
            second = await client.get("/healthcheck")

        assert first.status_code == 200
        assert second.status_code == 200

    @pytest.mark.asyncio
    async def test_proxy_header_can_supply_rate_limit_ip(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            RateLimitMiddleware,
            limit=1,
            window_seconds=60,
            key_strategy="ip",
            storage_url="",
            trust_proxy_headers=True,
            proxy_headers=["X-Forwarded-For"],
            trusted_proxies=["127.0.0.1/32"],
            exempt_paths=[],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/", headers={"X-Forwarded-For": "203.0.113.1, 10.0.0.1"})
            second = await client.get("/", headers={"X-Forwarded-For": "203.0.113.1, 10.0.0.1"})

        assert first.status_code == 200
        assert second.status_code == 429

    @pytest.mark.asyncio
    async def test_untrusted_client_cannot_spoof_proxy_headers(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            RateLimitMiddleware,
            limit=1,
            window_seconds=60,
            key_strategy="ip",
            storage_url="",
            trust_proxy_headers=True,
            proxy_headers=["X-Forwarded-For"],
            trusted_proxies=["10.0.0.0/8"],
            exempt_paths=[],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/", headers={"X-Forwarded-For": "203.0.113.1"})
            second = await client.get("/", headers={"X-Forwarded-For": "198.51.100.2"})

        assert first.status_code == 200
        assert second.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limited_response_still_has_request_ids_and_logs(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app = _minimal_app()
        app.add_middleware(
            RateLimitMiddleware,
            limit=1,
            window_seconds=60,
            key_strategy="ip",
            storage_url="",
            trust_proxy_headers=False,
            proxy_headers=["X-Forwarded-For"],
            trusted_proxies=[],
            exempt_paths=[],
        )
        app.add_middleware(RequestIDMiddleware)
        app.add_middleware(RequestLoggingMiddleware)
        caplog.set_level(logging.INFO, logger="app.request")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/")
            response = await client.get("/")

        assert response.status_code == 429
        assert "x-request-id" in response.headers
        assert any(
            record.name == "app.request" and getattr(record, "http_status_code", None) == 429
            for record in caplog.records
        )


class TestRateLimitHelpers:
    """Tests for rate limit stores and helper functions."""

    @pytest.mark.asyncio
    async def test_memory_store_prunes_expired_buckets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        times = iter([60, 120])
        monkeypatch.setattr("app.middleware.rate_limit.time.time", lambda: next(times))
        store = MemoryRateLimitStore()

        await store.hit("ip:127.0.0.1", limit=1, window_seconds=60)
        await store.hit("ip:127.0.0.1", limit=1, window_seconds=60)

        assert len(store._buckets) == 1

    @pytest.mark.asyncio
    async def test_redis_store_sets_expiry_on_first_hit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_client = AsyncMock()
        fake_client.incr = AsyncMock(side_effect=[1, 2])
        fake_client.expire = AsyncMock()
        from_url = Mock(return_value=fake_client)
        monkeypatch.setattr("redis.asyncio.from_url", from_url)

        store = RedisRateLimitStore("redis://localhost:6379/0")
        first = await store.hit("ip:127.0.0.1", limit=2, window_seconds=60)
        second = await store.hit("ip:127.0.0.1", limit=2, window_seconds=60)

        assert first.allowed is True
        assert second.allowed is True
        fake_client.expire.assert_awaited_once()

    def test_build_rate_limit_key_uses_authorization_hash(self) -> None:
        scope: Scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer abc")],
            "client": ("127.0.0.1", 1234),
        }

        key = _build_rate_limit_key(
            scope,
            "authorization",
            trust_proxy_headers=False,
            proxy_headers=["x-forwarded-for"],
            trusted_proxies=(),
        )

        assert key.startswith("authorization:")

    def test_build_rate_limit_key_falls_back_to_ip_for_unsupported_strategy(self) -> None:
        scope: Scope = {
            "type": "http",
            "headers": [(b"x-request-id", b"rid-123")],
            "client": ("127.0.0.1", 1234),
        }

        key = _build_rate_limit_key(
            scope,
            "request_id",
            trust_proxy_headers=False,
            proxy_headers=["x-forwarded-for"],
            trusted_proxies=(),
        )

        assert key == "ip:127.0.0.1"

    def test_build_rate_limit_key_falls_back_to_client_ip(self) -> None:
        scope: Scope = {
            "type": "http",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }

        key = _build_rate_limit_key(
            scope,
            "authorization",
            trust_proxy_headers=False,
            proxy_headers=["x-forwarded-for"],
            trusted_proxies=(),
        )

        assert key == "ip:127.0.0.1"

    def test_get_forwarded_client_ip_supports_x_real_ip(self) -> None:
        headers = Headers({"X-Real-IP": "203.0.113.10"})
        assert get_forwarded_client_ip(headers, ["x-real-ip"], ()) == "203.0.113.10"

    def test_get_forwarded_client_ip_rejects_invalid_values(self) -> None:
        headers = Headers({"X-Forwarded-For": "not-an-ip"})
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], ()) is None

    def test_get_forwarded_client_ip_uses_rightmost_untrusted_hop(self) -> None:
        headers = Headers({"X-Forwarded-For": "198.51.100.10, 203.0.113.5, 10.0.0.2"})
        trusted = (ip_network("10.0.0.0/8"), ip_network("203.0.113.0/24"))
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], trusted) == "198.51.100.10"

    def test_get_forwarded_client_ip_ignores_spoofed_leftmost_hop_when_proxy_appends(self) -> None:
        headers = Headers({"X-Forwarded-For": "192.0.2.99, 198.51.100.10"})
        trusted = (ip_network("10.0.0.0/8"),)
        assert get_forwarded_client_ip(headers, ["x-forwarded-for"], trusted) == "198.51.100.10"

    def test_is_trusted_proxy_matches_ip_against_allowlist(self) -> None:
        trusted = (ip_network("127.0.0.1/32"), ip_network("10.0.0.0/8"))
        assert _is_trusted_proxy("127.0.0.1", trusted) is True
        assert _is_trusted_proxy("192.0.2.5", trusted) is False

    def test_redis_store_raises_import_error_when_redis_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        # Temporarily hide the redis package from the import system.
        saved = sys.modules.pop("redis", None)
        saved_asyncio = sys.modules.pop("redis.asyncio", None)
        monkeypatch.setitem(sys.modules, "redis", None)

        try:
            with pytest.raises(ImportError, match="redis"):
                RedisRateLimitStore("redis://localhost:6379/0")
        finally:
            # Restore original modules so other tests are unaffected.
            sys.modules.pop("redis", None)
            if saved is not None:
                sys.modules["redis"] = saved
            if saved_asyncio is not None:
                sys.modules["redis.asyncio"] = saved_asyncio

    def test_decision_headers_include_retry_after(self) -> None:
        headers = _decision_headers(
            RateLimitDecision(
                allowed=False,
                limit=10,
                remaining=0,
                reset_at_epoch=9999999999,
            )
        )
        assert headers["X-RateLimit-Limit"] == "10"
        assert "Retry-After" in headers

    @pytest.mark.asyncio
    async def test_memory_store_concurrent_access(self) -> None:
        """Concurrent hits against the same key produce consistent counts."""
        store = MemoryRateLimitStore()
        limit = 50

        async def do_hit() -> RateLimitDecision:
            return await store.hit("ip:concurrent", limit=limit, window_seconds=60)

        results = await asyncio.gather(*[do_hit() for _ in range(limit + 10)])
        allowed = [r for r in results if r.allowed]
        rejected = [r for r in results if not r.allowed]
        assert len(allowed) == limit
        assert len(rejected) == 10

    @pytest.mark.asyncio
    async def test_memory_store_different_keys_independent(self) -> None:
        """Different keys have independent rate limits."""
        store = MemoryRateLimitStore()

        await store.hit("ip:a", limit=1, window_seconds=60)
        result_b = await store.hit("ip:b", limit=1, window_seconds=60)
        assert result_b.allowed is True

    @pytest.mark.asyncio
    async def test_rate_limit_middleware_passthrough_for_non_http(self) -> None:
        called = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal called
            called = True
            await receive()

        middleware = RateLimitMiddleware(
            app,
            limit=1,
            window_seconds=60,
            key_strategy="ip",
            storage_url="",
            trust_proxy_headers=False,
            proxy_headers=["X-Forwarded-For"],
            trusted_proxies=[],
            exempt_paths=[],
        )

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "websocket.connect"}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware({"type": "websocket"}, receive, send)

        assert called is True


class TestSecurityHeadersMiddleware:
    """Tests for security header injection."""

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        called = False

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal called
            called = True
            await receive()

        middleware = SecurityHeadersMiddleware(
            app,
            hsts_enabled=False,
            hsts_max_age_seconds=60,
            referrer_policy="no-referrer",
            permissions_policy="geolocation=()",
            content_security_policy="",
            trust_proxy_proto_header=False,
            trusted_proxies=[],
        )

        async def receive() -> Message:
            await asyncio.sleep(0)
            return {"type": "websocket.connect"}

        async def send(message: Message) -> None:
            await asyncio.sleep(0)

        await middleware({"type": "websocket"}, receive, send)

        assert called is True

    @pytest.mark.asyncio
    async def test_adds_default_security_headers(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            SecurityHeadersMiddleware,
            hsts_enabled=False,
            hsts_max_age_seconds=60,
            referrer_policy="no-referrer",
            permissions_policy="geolocation=()",
            content_security_policy="default-src 'none'; frame-ancestors 'none'",
            trust_proxy_proto_header=False,
            trusted_proxies=[],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")

        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["permissions-policy"] == "geolocation=()"
        assert (
            response.headers["content-security-policy"]
            == "default-src 'none'; frame-ancestors 'none'"
        )

    @pytest.mark.asyncio
    async def test_csp_omitted_when_empty_string(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            SecurityHeadersMiddleware,
            hsts_enabled=False,
            hsts_max_age_seconds=60,
            referrer_policy="no-referrer",
            permissions_policy="geolocation=()",
            content_security_policy="",
            trust_proxy_proto_header=False,
            trusted_proxies=[],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")

        assert "content-security-policy" not in response.headers

    @pytest.mark.asyncio
    async def test_hsts_uses_forwarded_proto_only_when_trusted(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            SecurityHeadersMiddleware,
            hsts_enabled=True,
            hsts_max_age_seconds=60,
            referrer_policy="no-referrer",
            permissions_policy="geolocation=()",
            content_security_policy="",
            trust_proxy_proto_header=True,
            trusted_proxies=["127.0.0.1/32"],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/", headers={"X-Forwarded-Proto": "https"})

        assert response.headers["strict-transport-security"] == "max-age=60; includeSubDomains"

    @pytest.mark.asyncio
    async def test_hsts_ignores_forwarded_proto_from_untrusted_source(self) -> None:
        app = _minimal_app()
        app.add_middleware(
            SecurityHeadersMiddleware,
            hsts_enabled=True,
            hsts_max_age_seconds=60,
            referrer_policy="no-referrer",
            permissions_policy="geolocation=()",
            content_security_policy="",
            trust_proxy_proto_header=True,
            trusted_proxies=["10.0.0.0/8"],
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/", headers={"X-Forwarded-Proto": "https"})

        assert "strict-transport-security" not in response.headers
