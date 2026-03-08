# Contributing

## Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** for dependency management

## Development Setup

```bash
git clone <repository-url>
cd fastapi-template
make install
cp .env.sqlite.example .env
make db-upgrade
make run
```

## Code Quality

This project enforces code quality through automated tooling:

- **Linting**: [Ruff](https://docs.astral.sh/ruff/) for fast Python linting
- **Formatting**: Ruff formatter (compatible with Black)
- **Type checking**: [mypy](https://mypy-lang.org/) in strict mode
- **Testing**: [pytest](https://docs.pytest.org/) with async support

Run the full local quality gate:

```bash
make check    # lint + type-check + tests
make ci       # lint + type-check + tests + coverage
```

Individual checks:

```bash
make lint         # ruff check
make lint-fix     # ruff check --fix
make format       # ruff format
make type-check   # mypy src tests
make test         # all tests
make test-unit    # unit tests only
make coverage     # tests with coverage report
```

## Pre-commit Hooks

Install pre-commit hooks to catch issues before they reach CI:

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

This configures:

- **pre-commit**: ruff check, ruff format check
- **pre-push**: mypy type checking, unit tests

## Testing

### Test Organization

- `tests/unit/` -- isolated tests for individual components, marked with `@pytest.mark.unit`
- `tests/integration/` -- full-stack tests through the ASGI transport, marked with `@pytest.mark.integration`

### Running Tests

```bash
make test                # all tests
make test-unit           # unit tests only
make test-integration    # integration tests only
make coverage            # all tests with coverage
```

### Writing Tests

- Place unit tests in `tests/unit/` and mark with `pytestmark = pytest.mark.unit`.
- Place integration tests in `tests/integration/` and mark with `pytestmark = pytest.mark.integration`.
- Use `make_settings(**overrides)` from `tests/helpers.py` to create test settings without `.env` files.
- Use `httpx.AsyncClient` with `ASGITransport` for HTTP-level testing.
- Use `monkeypatch` for environment isolation (the root conftest clears `APP_*` vars automatically).

### Coverage

The project enforces a **90% minimum coverage** threshold.

For the full testing guide (architecture, shared helpers, fixtures, patterns), see [`docs/testing.md`](docs/testing.md).

## Database Migrations

```bash
make db-upgrade                      # apply migrations
make db-downgrade                    # rollback one migration
make db-revision MESSAGE="describe"  # create new revision
```

## Docker

```bash
make docker-build       # build image locally
make docker-up          # SQLite stack
make docker-up-postgres # Postgres stack
make docker-down        # stop stack
```

## Makefile Reference

Run `make help` to see all targets. The full list:

| Target | Description |
| --- | --- |
| `make install` | Install all dependencies (dev + all extras) |
| `make install-prod` | Install production dependencies only |
| `make lock` | Regenerate uv lockfile |
| `make run` | Run development server with hot reload |
| `make run-prod` | Run production server (configurable via HOST/PORT/WORKERS) |
| `make smoke` | Run local startup smoke test on an alternate port |
| `make verify-stack` | Run live stack verification for DB/auth/metrics/tracing |
| `make verify-stack-prodlike` | Run live verification against Postgres, Redis, and JWKS |
| `make db-revision MESSAGE="..."` | Create a new Alembic revision |
| `make db-upgrade` | Apply Alembic migrations up to head |
| `make db-downgrade` | Roll back one Alembic migration |
| `make test` | Run all tests (pass extra args via TEST_ARGS="...") |
| `make test-unit` | Run only unit tests |
| `make test-integration` | Run only integration tests |
| `make coverage` | Run tests with terminal + XML coverage reports |
| `make lint` | Run Ruff lint checks |
| `make lint-fix` | Auto-fix lint issues where possible |
| `make format` | Format code with Ruff formatter |
| `make format-check` | Check code formatting without changes |
| `make type-check` | Run strict MyPy checks |
| `make check` | Run local quality gate (lint + type-check + tests) |
| `make ci` | Run CI quality gate (lint + format-check + type-check + tests + coverage) |
| `make docker-build` | Build the Docker image locally |
| `make docker-push` | Build and push the Docker image |
| `make docker-up` | Start the local SQLite-only Compose stack |
| `make docker-up-sqlite-redis` | Start the local SQLite + Redis Compose stack |
| `make docker-up-postgres` | Start the local Postgres-first Compose stack |
| `make docker-up-prodlike` | Start local Postgres + Redis Compose stack |
| `make docker-down` | Stop the local Docker Compose stack |
| `make docker-deploy-image` | Deploy a published image with docker run |
| `make docker-deploy-compose` | Deploy a published image with docker compose |
| `make docker-refresh-digests` | Refresh pinned Docker base-image digests in Dockerfile |
| `make clean` | Remove local caches and test artifacts |

## Extending The Template

### Adding a New Route

1. Create a new router file in `src/app/routes/` (e.g. `widgets.py`):

  ```python
  from fastapi import APIRouter

  router = APIRouter(prefix="/api/v1/widgets", tags=["Widgets"])

  @router.get("/")
  async def list_widgets() -> dict[str, list]:
      return {"widgets": []}
  ```

2. Register the router in `src/app/app_builder.py` inside `setup_routes()`:

  ```python
  from .routes.widgets import router as widgets_router
  self.app.include_router(widgets_router)
  ```

3. Add tests in `tests/unit/` and `tests/integration/`.

### Adding a New Database Model

1. Define the model in `src/app/db/models.py` (or a new file that imports `Base`):

  ```python
  from sqlalchemy import String
  from sqlalchemy.orm import Mapped, mapped_column
  from .base import Base

  class MyModel(Base):
      __tablename__ = "my_models"
      id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
      name: Mapped[str] = mapped_column(String(120), nullable=False)
  ```

2. Generate a migration: `make db-revision MESSAGE="add my_models table"`
3. Apply it: `make db-upgrade`

### Adding a New Middleware

1. Create a middleware file in `src/app/middleware/`.
2. Follow the raw ASGI middleware pattern (see `timeout.py` or `body_size.py` for examples).
3. Register it in `src/app/app_builder.py` inside `setup_middleware()`. Middleware is registered in reverse execution order.
4. Add unit tests using a minimal ASGI app fixture.

### Adding a New Readiness Check

1. Define a check function that returns a `ReadinessCheckResult`:

  ```python
  from app.readiness.registry import ReadinessCheckResult

  async def check_my_dependency(app) -> ReadinessCheckResult:
      return ReadinessCheckResult(name="my_dep", is_healthy=True)
  ```

2. Register it in `src/app/app_builder.py` inside `setup_routes()` where the readiness registry is populated.

### Adding a New Setting

1. Add the field to `src/app/settings.py` with a default, description, and validation constraints.
2. If the setting requires cross-field validation, add logic in one of the `_validate_*` or `_resolve_*` functions.
3. Add unit tests in `tests/unit/test_settings.py` for both the default value and validation rules.
4. Document the setting in `docs/configuration.md` and `.env.example`.

## Pull Request Guidelines

1. Run `make ci` locally before opening a PR.
2. Write tests for new functionality.
3. Keep commits focused and descriptive.
4. Update documentation if you change configuration, middleware, or API behavior.
5. Ensure new settings are documented in `README.md` and relevant docs.

## Project Structure

```bash
src/app/           # Application package
  app_builder.py   # Builder pattern for app composition
  settings.py      # Pydantic settings with validation
  auth/            # JWT authentication
  db/              # Database engine, session, models
  middleware/       # Request hardening middleware
  routes/          # API and health endpoints
  errors/          # Error handlers
  observability/   # OpenTelemetry tracing
tests/
  unit/            # Isolated component tests
  integration/     # Full-stack HTTP tests
docs/              # Architecture, operations, security, testing docs
  adr/             # Architecture decision records
ops/               # Deployment and operations scripts
```
