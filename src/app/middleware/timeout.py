"""
Request timeout middleware.

Prevents runaway requests from consuming request-processing capacity
indefinitely. Without a timeout, a single slow database query or external
API call can tie up the request path long enough to degrade the service.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import asyncio
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..utils import get_sanitized_request_path

logger = logging.getLogger(__name__)


class TimeoutMiddleware:
    """
    Middleware that enforces a maximum duration for request processing.

    If a request exceeds the configured timeout, the middleware returns
    a 504 Gateway Timeout response and frees the worker thread.

    This is a critical production safeguard. In Kubernetes deployments,
    it should be set below the ingress controller's timeout to ensure
    the application returns a meaningful error before the infrastructure
    terminates the connection.
    """

    def __init__(self, app: ASGIApp, timeout: float = 30) -> None:
        """
        Initialize the timeout middleware.

        Args:
            app: The ASGI application.
            timeout: Maximum request duration in seconds. Defaults to 30.
        """
        self.app = app
        self.timeout = timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process each request with timeout enforcement."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False
        response_completed = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, response_completed
            if message["type"] == "http.response.start":
                response_started = True
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_completed = True
            await send(message)

        try:
            await asyncio.wait_for(self.app(scope, receive, send_wrapper), timeout=self.timeout)
        except TimeoutError:
            if response_started:
                request = Request(scope, receive=receive)
                request_path = get_sanitized_request_path(request)
                logger.warning(
                    "Request timed out after response started; closing partial response for %s",
                    request_path,
                )
                if not response_completed:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                return

            request = Request(scope, receive=receive)
            request_path = get_sanitized_request_path(request)
            response = JSONResponse(
                status_code=504,
                content={
                    "error": "gateway_timeout",
                    "detail": f"Request processing exceeded {self.timeout}s limit",
                    "path": request_path,
                },
            )
            await response(scope, receive, send)
