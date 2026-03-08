# ADR 0003: Raw ASGI Middleware over Starlette BaseHTTPMiddleware

**Status**: Accepted
**Date**: 2026-01-15

## Context

Starlette provides `BaseHTTPMiddleware` as a convenience class for writing middleware. It wraps the ASGI protocol behind a `request`/`response` interface:

```python
class MyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        return response
```

However, `BaseHTTPMiddleware` has well-documented problems:

1. **Full body buffering**: `call_next()` consumes the entire response body into memory before returning, breaking streaming responses and increasing peak memory usage.
2. **Task group issues**: The middleware spawns an internal `anyio.TaskGroup` for each request, which can mask cancellation and create subtle lifecycle bugs.
3. **No early response**: There is no way to short-circuit before the request body is consumed (relevant for body size limits and rate limiting).
4. **Performance overhead**: The request/response wrapping adds measurable latency per request compared to raw ASGI.

The Starlette maintainers themselves recommend raw ASGI middleware for production use. See [encode/starlette#1012](https://github.com/encode/starlette/issues/1012).

## Decision

All custom middleware in this template uses the raw ASGI interface:

```python
class MyMiddleware:
    def __init__(self, app: ASGIApp, **kwargs):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Custom logic wrapping self.app(scope, receive, send)
```

This applies to: `RequestIDMiddleware`, `RequestLoggingMiddleware`, `SecurityHeadersMiddleware`, `TimeoutMiddleware`, `BodySizeLimitMiddleware`, and `RateLimitMiddleware`.

## Consequences

**Benefits:**

- Streaming responses work correctly — no body buffering
- Early rejection (413, 429) happens before body consumption, saving bandwidth and memory
- No hidden task group machinery — cancellation and timeout behavior is predictable
- Lower per-request overhead
- Header injection (request ID, security headers) works by wrapping `send` — no response copying

**Trade-offs:**

- Raw ASGI requires understanding `scope`, `receive`, and `send` — a steeper learning curve than `BaseHTTPMiddleware`
- Middleware code is more verbose (wrapping `send` callbacks vs. modifying a `Response` object)
- Developers adding new middleware must follow the existing patterns in `src/app/middleware/` rather than using the simpler `BaseHTTPMiddleware` API
