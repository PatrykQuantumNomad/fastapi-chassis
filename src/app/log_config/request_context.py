"""
Request-scoped logging context helpers.

Stores both the current request ID and correlation ID in ContextVars so log
records emitted from request-handling code can include per-request and
cross-service tracing identifiers.
"""

from contextvars import ContextVar, Token

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

type RequestContextTokens = tuple[Token[str], Token[str]]


def get_request_id() -> str:
    """Return the request ID for the current context, or '-' when absent."""
    return _request_id.get()


def get_correlation_id() -> str:
    """Return the correlation ID for the current context, or '-' when absent."""
    return _correlation_id.get()


def set_request_context(request_id: str, correlation_id: str) -> RequestContextTokens:
    """Set request-scoped tracing IDs and return reset tokens."""
    return _request_id.set(request_id), _correlation_id.set(correlation_id)


def reset_request_context(tokens: RequestContextTokens) -> None:
    """Reset tracing context to the previous values."""
    request_id_token, correlation_id_token = tokens
    _request_id.reset(request_id_token)
    _correlation_id.reset(correlation_id_token)
