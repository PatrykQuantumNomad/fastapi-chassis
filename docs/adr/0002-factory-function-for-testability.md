# ADR 0002: Factory Function for Testability

**Status**: Accepted
**Date**: 2026-01-15

## Context

FastAPI examples commonly create an `app` instance at module level:

```python
# main.py
app = FastAPI()
```

This is convenient for small projects but creates problems as the application grows:

1. **Test pollution**: Every test that imports `app` shares the same instance. Middleware state, `app.state` values, and lifespan side effects bleed across tests.
2. **Configuration inflexibility**: Switching between test settings, staging settings, or metrics-enabled/disabled requires monkeypatching or environment manipulation before import.
3. **Single instance constraint**: Running two differently-configured app instances in the same process (e.g., one with auth enabled and one without) is impossible with a module-level singleton.

## Decision

Expose a `create_app(settings=None)` factory function as the single public entry point for application creation. The factory accepts an optional `Settings` override and delegates to `FastAPIAppBuilder` (see ADR 0001).

```python
from app import create_app
from tests.helpers import make_settings

# Test with metrics disabled
app = create_app(settings=make_settings(metrics_enabled=False))

# Test with auth enabled
app = create_app(settings=make_settings(auth_enabled=True, auth_jwt_secret="..."))
```

`main.py` calls `create_app()` with no arguments so it loads settings from the environment.

## Consequences

**Benefits:**

- Each test creates a fresh app instance with exactly the settings it needs — no shared mutable state
- Integration tests can run multiple app configurations in parallel without interference
- The test helper `make_settings(**overrides)` makes it trivial to tweak one setting while keeping safe defaults
- No monkeypatching or environment variable manipulation required in tests
- The factory pattern is explicit about what happens at startup — no hidden initialization on import

**Trade-offs:**

- `main.py` must call `create_app()` rather than just importing `app`
- Developers must understand that importing `app` from anywhere other than `main.py` is incorrect
- A small amount of app creation overhead per test (negligible in practice — tests run in ~3 seconds)
