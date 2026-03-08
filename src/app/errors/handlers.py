"""
Global error handlers for the FastAPI application.

Provides consistent, structured error responses across all exception types.
In production, this prevents stack traces from leaking to clients while
ensuring every error is properly logged for debugging.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..utils import get_sanitized_request_path


class ErrorHandler:
    """
    Centralized error handler registration for a FastAPI application.

    Registers three layers of exception handling:
    1. RequestValidationError - Pydantic validation failures (422)
    2. HTTPException - Explicit HTTP errors raised by handlers
    3. Exception - Catch-all for unhandled exceptions (500)

    Each handler returns a consistent JSON structure:
    {
        "error": "<error_type>",
        "detail": "<human_readable_detail>",
        "path": "<request_url>"
    }
    """

    def __init__(self, app: FastAPI, logger: logging.Logger) -> None:
        """
        Initialize the error handler and register all exception handlers.

        Args:
            app: The FastAPI application instance.
            logger: Logger for recording error details.
        """
        self.app = app
        self.logger = logger

    def register_default_handlers(self) -> None:
        """Register all default exception handlers on the application."""
        self._register_validation_handler()
        self._register_http_exception_handler()
        self._register_unhandled_exception_handler()

    def _register_validation_handler(self) -> None:
        """Register handler for Pydantic request validation errors."""

        @self.app.exception_handler(RequestValidationError)
        async def validation_exception_handler(
            request: Request, exc: RequestValidationError
        ) -> JSONResponse:
            """
            Handle request validation errors.

            Returns the validation error details so API consumers can
            understand exactly which field failed and why.
            """
            request_path = get_sanitized_request_path(request)
            sanitized_errors = _sanitize_validation_errors(exc.errors())
            self.logger.warning(
                "Validation error on %s: %s",
                request_path,
                sanitized_errors,
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error": "validation_error",
                    "detail": sanitized_errors,
                    "path": request_path,
                },
            )

    def _register_http_exception_handler(self) -> None:
        """Register handler for explicit HTTP exceptions."""

        @self.app.exception_handler(StarletteHTTPException)
        async def http_exception_handler(
            request: Request, exc: StarletteHTTPException
        ) -> JSONResponse:
            """
            Handle HTTP exceptions with consistent JSON formatting.

            Ensures all HTTP errors (404, 403, etc.) return the same
            JSON structure instead of Starlette's default plain text.
            """
            request_path = get_sanitized_request_path(request)
            self.logger.warning(
                "HTTP %d on %s: %s",
                exc.status_code,
                request_path,
                exc.detail,
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": "http_error",
                    "detail": exc.detail,
                    "path": request_path,
                },
                headers=exc.headers,
            )

    def _register_unhandled_exception_handler(self) -> None:
        """Register catch-all handler for unhandled exceptions."""

        @self.app.exception_handler(Exception)
        async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
            """
            Handle any unhandled exception.

            CRITICAL: Never expose stack traces or internal details to clients.
            The full exception is logged for the engineering team, but the
            client receives only a generic error message.
            """
            request_path = get_sanitized_request_path(request)
            self.logger.exception(
                "Unhandled exception on %s: %s",
                request_path,
                exc,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "detail": "An unexpected error occurred",
                    "path": request_path,
                },
            )


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """
    Remove rejected input values from validation errors.

    Pydantic v2 includes the original `input` in error payloads, which can leak
    credentials or signed values if callers send secrets in invalid requests.
    """

    sanitized_errors: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        sanitized_error = {key: value for key, value in error.items() if key != "input"}
        sanitized_errors.append(sanitized_error)
    return sanitized_errors
