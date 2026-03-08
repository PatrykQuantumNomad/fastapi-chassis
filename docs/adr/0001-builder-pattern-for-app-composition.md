# ADR 0001: Builder Pattern for App Composition

**Status**: Accepted
**Date**: 2026-01-15

## Context

A production FastAPI application requires many configuration concerns: logging, database, auth, tracing, metrics, error handlers, routes, middleware (CORS, trusted hosts, security headers, rate limiting, timeout, body size, request ID, request logging). These concerns have ordering constraints (e.g., middleware registration order matters in Starlette) and conditional branches (e.g., rate limiting only when enabled, metrics only when the dependency is installed).

Approaches considered:

1. **Module-level instantiation**: Create and configure `app` at import time. Simple, but untestable — every import triggers initialization and there is no way to swap settings without monkeypatching.
2. **Plain factory function**: A single `create_app()` function containing all setup logic. Testable, but becomes a 300+ line function that is hard to read and difficult to test one concern at a time.
3. **Builder pattern**: A class with one method per concern, each returning `self` for chaining. The factory function orchestrates the chain.

## Decision

Use the Builder pattern (`FastAPIAppBuilder`) in `src/app/app_builder.py` with a thin factory function (`create_app()`) in `src/app/__init__.py`.

Each `setup_*()` method owns exactly one concern:

```python
app = (
    FastAPIAppBuilder(settings=settings, logger=logger)
    .setup_settings()
    .setup_logging()
    .setup_database()
    .setup_auth()
    .setup_tracing()
    .setup_metrics()
    .setup_error_handlers()
    .setup_routes()
    .setup_middleware()
    .build()
)
```

## Consequences

**Benefits:**

- The bootstrap path reads like a deployment checklist — changes to app wiring are easy to review
- Each `setup_*()` method can be unit-tested in isolation by constructing a builder and calling only that method
- Adding a new concern means adding one method and one line in the chain, not modifying a monolithic function
- Conditional wiring (e.g., skip metrics when disabled) stays inside the method that owns it
- The fluent interface makes the initialization order explicit and visible

**Trade-offs:**

- Slightly more indirection than a plain factory function
- The builder must be instantiated with `Settings` and a logger, which adds a small coordination layer
- Middleware registration order (reverse in Starlette) must still be understood by the developer adding new middleware
