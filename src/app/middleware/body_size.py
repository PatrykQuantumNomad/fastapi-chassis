"""
Request body size limiting middleware.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestTooLargeError(RuntimeError):
    """Raised when a request body exceeds the configured limit."""


class InvalidContentLengthError(RuntimeError):
    """Raised when Content-Length is present but not a valid integer."""


class BodySizeLimitMiddleware:
    """Reject requests whose body exceeds the configured byte limit."""

    def __init__(self, app: ASGIApp, *, max_request_body_bytes: int) -> None:
        self.app = app
        self.max_request_body_bytes = max_request_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        total_received = 0

        async def receive_wrapper() -> Message:
            nonlocal total_received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                total_received += len(body)
                if total_received > self.max_request_body_bytes:
                    raise RequestTooLargeError
            return message

        content_length = dict(scope.get("headers", [])).get(b"content-length")
        if content_length is not None:
            try:
                parsed_content_length = int(content_length)
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={
                        "error": "invalid_request",
                        "detail": "Content-Length header must be a valid integer",
                    },
                )
                await response(scope, receive, send)
                return

            if parsed_content_length > self.max_request_body_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": "request_too_large",
                        "detail": (
                            f"Request body exceeds {self.max_request_body_bytes} byte limit"
                        ),
                    },
                )
                await response(scope, receive, send)
                return

        try:
            await self.app(scope, receive_wrapper, send)
        except RequestTooLargeError:
            response = JSONResponse(
                status_code=413,
                content={
                    "error": "request_too_large",
                    "detail": (f"Request body exceeds {self.max_request_body_bytes} byte limit"),
                },
            )
            await response(scope, receive, send)
