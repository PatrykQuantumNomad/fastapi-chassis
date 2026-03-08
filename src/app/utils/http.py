"""
HTTP utility helpers shared across middleware and error handlers.
"""

from starlette.requests import Request
from starlette.types import Scope


def get_sanitized_scope_path(scope: Scope) -> str:
    """
    Return the request path without query-string data.

    Error payloads and operational logs should never echo the full URL because
    callers sometimes place bearer tokens, signed URLs, or other secrets in the
    query string.
    """

    root_path = str(scope.get("root_path") or "")
    path = str(scope.get("path") or "/")
    return f"{root_path}{path}"


def get_sanitized_request_path(request: Request) -> str:
    """Return a path-only representation of the current request."""
    return get_sanitized_scope_path(request.scope)
