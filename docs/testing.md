# Testing Guide

This guide covers the pytest-based test suite, how to run it, and how to add tests for new features. For the live stack verification harness (`ops/test_stack.py`), see [`testing-stack.md`](testing-stack.md).

## Test Architecture

```bash
                  ┌──────────────────────────────┐
                  │  Stack Verification           │  ops/test_stack.py
                  │  (real HTTP, real services)    │  make verify-stack
                  └──────────────────────────────┘
                  ┌──────────────────────────────┐
                  │  Integration Tests            │  tests/integration/
                  │  (full ASGI transport)         │  make test-integration
                  └──────────────────────────────┘
    ┌────────────────────────────────────────────────────┐
    │  Unit Tests                                        │  tests/unit/
    │  (isolated components, no network)                 │  make test-unit
    └────────────────────────────────────────────────────┘
```

- **Unit tests** (`tests/unit/`): Fast, isolated tests for individual functions, classes, and middleware. Use mocks and minimal ASGI apps. Marked with `@pytest.mark.unit`.
- **Integration tests** (`tests/integration/`): Exercise the full `create_app()` factory and ASGI stack via `httpx.AsyncClient`. Marked with `@pytest.mark.integration`.
- **Stack verification** (`ops/test_stack.py`): End-to-end tests against a running server with real HTTP. Used for pre-deployment validation.

## Running Tests

```bash
make test                # all tests
make test-unit           # unit tests only
make test-integration    # integration tests only
make coverage            # all tests with coverage report
make ci                  # full CI gate (lint + format + type-check + tests + coverage)
```

### Running Specific Tests

```bash
# Run a single test file
uv run pytest tests/unit/test_auth.py

# Run a single test by name
uv run pytest tests/unit/test_auth.py -k "test_authenticates_valid"

# Run tests matching a keyword
uv run pytest -k "readiness"

# Run with verbose output
uv run pytest tests/unit/test_auth.py -v
```

## Writing Unit Tests

### Pattern

```python
"""Unit tests for my_module."""

import pytest
from tests.helpers import make_settings, make_jwt, make_principal

pytestmark = pytest.mark.unit


class TestMyFeature:
    """Tests for the feature under test."""

    def test_basic_behavior(self) -> None:
        settings = make_settings(metrics_enabled=False, my_setting=True)
        # test code...

    @pytest.mark.asyncio
    async def test_async_behavior(self) -> None:
        # async test code...
```

### Shared Test Utilities (`tests/helpers.py`)

| Function | Purpose |
| --- | --- |
| `make_settings(**overrides)` | Build `Settings` isolated from `.env` files |
| `make_jwt(subject, scopes, roles, ...)` | Mint an HS256 test JWT with sensible defaults |
| `make_principal(subject, scopes, roles, ...)` | Build a `Principal` with sensible defaults |

Constants: `TEST_SECRET`, `TEST_AUDIENCE`, `TEST_ISSUER` match the default test auth config.

### Minimal ASGI App Pattern

For middleware tests, use a minimal FastAPI app instead of the full builder:

```python
def _minimal_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"ok": "true"}

    return app
```

## Writing Integration Tests

Integration tests exercise the full `create_app()` pipeline and use `httpx.AsyncClient` with `ASGITransport` (no real network):

```python
"""Integration tests for my feature."""

import pytest
from httpx import ASGITransport, AsyncClient
from app import create_app
from tests.helpers import make_settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_my_feature() -> None:
    settings = make_settings(metrics_enabled=False)
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/my-endpoint")

    assert response.status_code == 200
```

### Available Fixtures (`tests/integration/conftest.py`)

| Fixture | Description |
| --- | --- |
| `test_settings` | Base settings tuned for fast test runs |
| `app` | Fully-configured FastAPI instance |
| `client` | AsyncClient wired to the app (no network) |
| `app_with_metrics` / `client_with_metrics` | App with Prometheus metrics enabled |
| `slow_app` / `slow_client` | App with 1-second timeout |
| `postgres_app` / `postgres_client` | Real Postgres (skipped if unavailable) |
| `redis_rate_limit_app` / `redis_client` | Real Redis (skipped if unavailable) |

## Testing Against Postgres / Redis

Integration tests for Postgres and Redis are skipped by default. To run them locally:

```bash
# Start services
docker compose -f docker-compose.postgres.yml -f docker-compose.redis.yml up -d

# Set environment variables
export TEST_POSTGRES_URL="postgresql+asyncpg://app:app@localhost:5432/fastapi_template"
export TEST_POSTGRES_ALEMBIC_URL="postgresql+psycopg://app:app@localhost:5432/fastapi_template"
export TEST_REDIS_URL="redis://localhost:6379/0"

# Run integration tests
make test-integration
```

In CI, these run automatically via GitHub Actions service containers.

## Test Isolation

- The root `conftest.py` auto-clears all `APP_*` environment variables and changes the working directory to `tmp_path` for every test.
- Use `make_settings(_env_file=None, ...)` (via `tests/helpers.py`) to prevent `.env` files from influencing results.
- Each test gets a fresh `Settings` instance — no shared state between tests.

## Coverage

The project enforces a **90% minimum coverage** threshold (currently 98%+).

```bash
make coverage                    # terminal report + XML
uv run pytest --cov=src/app --cov-report=html   # HTML report in htmlcov/
```

Coverage configuration is in `pyproject.toml` under `[tool.coverage.*]`.

## Checklist for New Features

When adding a new feature, ensure:

1. **Unit tests** exist for the core logic (functions, classes, validators)
2. **Integration tests** verify the feature works through the full ASGI stack
3. **Edge cases** are covered (invalid input, error paths, boundary conditions)
4. **Settings validation** is tested if you add new `APP_*` config variables
5. **Middleware composition** is verified if the feature interacts with the middleware chain
6. **Coverage** remains above 90% (`make coverage`)
7. **Types** pass strict mypy (`make type-check`)
8. **Lint** is clean (`make lint`)
