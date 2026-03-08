"""
Request logging middleware.

Emits one structured application log per HTTP request with method, path,
status code, latency, client address, request ID, and correlation ID.
"""

import logging
from time import perf_counter
from urllib.parse import parse_qsl, urlencode

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .request_id import RequestIDMiddleware

_REDACTED = "[redacted]"


class RequestLoggingMiddleware:
    """
    Middleware that emits one access-style app log per request.

    This complements (or can replace) Uvicorn access logs while preserving
    both per-hop request IDs and cross-service correlation IDs.
    """

    def __init__(
        self, app: ASGIApp, logger_name: str = "app.request", redact_headers: bool = False
    ) -> None:
        self.app = app
        self.logger = logging.getLogger(logger_name)
        self.redact_headers = redact_headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Emit one structured app log for each HTTP request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = perf_counter()
        status_code = 500
        request_id = "-"
        correlation_id = "-"
        response_bytes: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, request_id, correlation_id, response_bytes
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = {key.lower(): value for key, value in message.get("headers", [])}
                request_id = headers.get(
                    RequestIDMiddleware.HEADER_NAME.lower().encode("latin-1"), b"-"
                ).decode("utf-8")
                correlation_id = headers.get(
                    RequestIDMiddleware.CORRELATION_HEADER_NAME.lower().encode("latin-1"),
                    b"-",
                ).decode("utf-8")
                content_length = headers.get(b"content-length")
                if content_length is not None:
                    try:
                        response_bytes = int(content_length.decode("ascii"))
                    except ValueError:
                        response_bytes = None
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (perf_counter() - start) * 1000
            client = scope.get("client")
            client_host = client[0] if client else "-"
            path = scope.get("path", "-")
            method = scope.get("method", "-")
            query_string_bytes = scope.get("query_string", b"")
            query_string = (
                query_string_bytes.decode("utf-8", errors="replace")
                if isinstance(query_string_bytes, bytes)
                else ""
            )
            headers = self._headers_to_dict(scope)
            user_agent = (
                _REDACTED
                if self.redact_headers
                else self._decode_header(headers.get(b"user-agent"))
            )
            referer = (
                _REDACTED if self.redact_headers else self._decode_header(headers.get(b"referer"))
            )
            request_bytes = self._parse_ascii_int(headers.get(b"content-length"))
            outcome = self._outcome_from_status(status_code)

            self.logger.info(
                "http_request_completed",
                extra={
                    "event": "http.request.completed",
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "http_method": method,
                    "http_path": path,
                    "http_query": self._sanitize_query_string(query_string),
                    "http_status_code": status_code,
                    "http_status_class": f"{status_code // 100}xx",
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": client_host,
                    "user_agent": user_agent,
                    "referer": referer,
                    "request_bytes": request_bytes,
                    "response_bytes": response_bytes,
                    "outcome": outcome,
                },
            )

    @staticmethod
    def _headers_to_dict(scope: Scope) -> dict[bytes, bytes]:
        return {key.lower(): value for key, value in scope.get("headers", [])}

    @staticmethod
    def _decode_header(value: bytes | None) -> str:
        if value is None:
            return "-"
        return value.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_ascii_int(value: bytes | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value.decode("ascii"))
        except ValueError:
            return None

    @staticmethod
    def _outcome_from_status(status_code: int) -> str:
        if status_code >= 500:
            return "server_error"
        if status_code >= 400:
            return "client_error"
        return "success"

    @staticmethod
    def _sanitize_query_string(query_string: str) -> str:
        if not query_string:
            return ""

        pairs = parse_qsl(query_string, keep_blank_values=True)
        return urlencode([(key, "[redacted]") for key, _ in pairs], doseq=True)
