"""
Tracing ID middleware for distributed request correlation.

Each inbound HTTP request receives a fresh request ID for this service hop.
The correlation ID is propagated across hops when the caller supplies
``X-Correlation-ID``. If only ``X-Request-ID`` is supplied, it is treated as
the upstream trace identifier and reused as the correlation ID.

The identifiers are:
  - Attached to ``request.state`` for handler access
  - Stored in logging context for downstream log records
  - Returned in both response headers

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import uuid

from opentelemetry.trace import get_current_span
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..log_config.request_context import reset_request_context, set_request_context


class RequestIDMiddleware:
    """
    Middleware that assigns per-request and cross-request tracing IDs.

    ``request_id`` is always generated locally so each service hop has its own
    unique identifier. ``correlation_id`` is propagated from upstream when
    available so related requests across services can still be tied together.
    """

    HEADER_NAME = "X-Request-ID"
    CORRELATION_HEADER_NAME = "X-Correlation-ID"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Inject tracing IDs into request state, context, and response headers."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        request_id = str(uuid.uuid4())
        correlation_id = (
            headers.get(self.CORRELATION_HEADER_NAME.lower().encode("latin-1"))
            or headers.get(self.HEADER_NAME.lower().encode("latin-1"))
            or request_id.encode("utf-8")
        ).decode("utf-8")
        tokens = set_request_context(request_id, correlation_id)
        span = get_current_span()
        if span.is_recording():
            span.set_attribute("app.request_id", request_id)
            span.set_attribute("app.correlation_id", correlation_id)

        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["correlation_id"] = correlation_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable_headers = list(message.get("headers", []))
                self._upsert_header(
                    mutable_headers, self.HEADER_NAME.encode("latin-1"), request_id.encode("utf-8")
                )
                self._upsert_header(
                    mutable_headers,
                    self.CORRELATION_HEADER_NAME.encode("latin-1"),
                    correlation_id.encode("utf-8"),
                )
                message["headers"] = mutable_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_request_context(tokens)

    @staticmethod
    def _upsert_header(headers: list[tuple[bytes, bytes]], key: bytes, value: bytes) -> None:
        for idx, (header_key, _) in enumerate(headers):
            if header_key.lower() == key.lower():
                headers[idx] = (header_key, value)
                return
        headers.append((key, value))
