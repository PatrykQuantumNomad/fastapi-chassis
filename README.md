# FastAPI Chassis

Production-ready FastAPI template with an explicit app factory, SQLite-first async SQLAlchemy setup, Alembic migrations, stateless JWT validation, dependency-aware readiness checks, OpenTelemetry tracing, optional Prometheus metrics, rate limiting, and secure-by-default hardening.

## Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** for dependency management and virtual environments

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Quick Start

Pick the env file that matches your runtime mode. Each preset includes every
setting with sensible defaults — just copy and adjust what you need:

- `cp .env.sqlite.example .env` — SQLite + in-memory rate limiting (no extra infrastructure)
- `cp .env.sqlite-redis.example .env` — SQLite + Redis rate limiting
- `cp .env.postgres-redis.example .env` — Postgres + Redis (production-like)

```bash
make install
make db-upgrade
make run
```

The API will be available at [http://localhost:8000](http://localhost:8000). If you choose the SQLite preset, this starts with the local SQLite database under `./data/app.db`.

By default, the template keeps docs, diagnostic routes, and metrics off, exposes only local trusted hosts, and returns a minimal readiness payload. Enable extra observability endpoints explicitly when your deployment model needs them.

Additional operator-facing documentation:

- [`docs/architecture.md`](docs/architecture.md): application structure, request flow, runtime resources, auth, and readiness model
- [`docs/configuration.md`](docs/configuration.md): complete reference for all `APP_*` environment variables
- [`docs/operations.md`](docs/operations.md): deployment guidance, production configuration, verification, rollback, and troubleshooting
- [`docs/helm-chart.md`](docs/helm-chart.md): Kubernetes deployment with the included Helm chart
- [`docs/monitoring.md`](docs/monitoring.md): Prometheus metrics, alert rules, and `APP_METRICS_PREFIX` adaptation
- [`docs/security.md`](docs/security.md): authentication, authorization, security headers, proxy trust, and production checklist
- [`docs/api-usage.md`](docs/api-usage.md): endpoint examples with curl commands, error codes, and JWT token generation
- [`docs/testing.md`](docs/testing.md): test architecture, writing tests, shared helpers, fixtures, and coverage
- [`docs/adr/`](docs/adr/): architecture decision records for key design choices

Equivalent raw commands:

```bash
uv sync                                     # SQLite-only (default)
uv sync --extra postgres                    # add Postgres drivers
uv run alembic -c alembic.ini upgrade head
uv run python main.py
```

## Dependency Management

Project metadata, runtime dependencies, development tooling, and quality settings all live in `pyproject.toml`.

- `[project]` defines package metadata plus the core production dependency set installed by `uv sync`
- `[project.optional-dependencies]` contains runtime extras for backend-specific drivers (see below)
- `[dependency-groups]` contains local-only tooling such as `pytest`, `ruff`, and `mypy`
- `[build-system]` and `tool.hatch...` control packaging/build behavior
- `tool.ruff`, `tool.mypy`, `tool.pytest`, and `tool.coverage` configure linting, typing, tests, and coverage

### Optional extras

| Extra      | Packages                     | When to install                        |
|------------|------------------------------|----------------------------------------|
| `postgres` | `asyncpg`, `psycopg[binary]` | `APP_DATABASE_BACKEND=postgres`        |
| `redis`    | `redis`                      | `APP_RATE_LIMIT_STORAGE_BACKEND=redis` |

Install extras selectively or all at once:

```bash
uv sync --extra postgres     # just Postgres drivers
uv sync --extra redis        # just Redis client
uv sync --all-extras         # every optional extra
make install                 # dev shortcut (installs dev + all extras)
```

The Dockerfile defaults to `--extra postgres --extra redis` via the `UV_EXTRAS` build arg. Override it to build a lighter image for specific backends:

```bash
docker build --build-arg UV_EXTRAS="" .                     # SQLite + memory rate limiter only
docker build --build-arg UV_EXTRAS="--extra postgres" .     # Postgres without Redis
```

### Dependencies worth calling out

- `greenlet` is not imported directly by application code. It is included as an implicit runtime dependency for SQLAlchemy's async stack, which the template uses for `AsyncEngine` and `AsyncSession`.

## What The Template Includes

- App factory and fluent builder in `src/app/__init__.py` and `src/app/app_builder.py`
- SQLite-first async SQLAlchemy engine/session wiring stored on `app.state`
- Alembic configuration plus a first migration and example model
- Stateless JWT resource-server flow with bearer auth dependencies
- Dependency-aware readiness checks for application, database, and auth
- Optional Prometheus metrics plus OpenTelemetry trace export
- Request ID propagation, structured logging, timeout handling, body size limits, security headers, trusted hosts, and rate limiting
- Opt-in docs and diagnostic endpoints for local development or internal environments

## Running The App

```bash
# Development
make run

# Production process model
make run-prod
```

Before using `make run-prod`, set explicit production values for at least:

- `APP_DATABASE_URL` and `APP_ALEMBIC_DATABASE_URL`
- `APP_TRUSTED_HOSTS`
- `APP_CORS_ALLOWED_ORIGINS`
- `APP_AUTH_*` if protected routes are enabled
- `APP_METRICS_ENABLED=true` only when `/metrics` is intentionally exposed

Equivalent raw commands:

```bash
uv run python main.py
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 --no-access-log
```

## Docker And Docker Compose

Build and run the template locally with Docker Compose:

```bash
docker compose up --build
```

Compose entry points:

- `docker-compose.yml`: SQLite-first app stack
- `docker-compose.postgres.yml`: Postgres-first app stack
- `docker-compose.redis.yml`: optional Redis overlay for either stack

Choose `.env.sqlite.example` for the default SQLite-only flow,
`.env.sqlite-redis.example` for SQLite + Redis, or
`.env.postgres-redis.example` when you plan to run the Postgres-first compose
file and optionally enable Redis.

The local Compose stack:

- Builds from the repository `Dockerfile`
- Runs Alembic migrations on container startup
- Uses a single Uvicorn worker so the default in-memory rate limiter remains safe for local use
- Publishes the API on `APP_PORT` from `.env`
- Persists the default SQLite database in `./data`

For the SQLite + Redis local stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.redis.yml up --build
```

For the Postgres-first local stack:

```bash
docker compose -f docker-compose.postgres.yml up --build
docker compose -f docker-compose.postgres.yml -f docker-compose.redis.yml up --build
```

The image itself exposes a native Docker liveness health check that follows `APP_HEALTH_CHECK_PATH`. Remote deployment helpers wait for container health and then require a successful readiness probe on `APP_READINESS_CHECK_PATH` before reporting success.

The Docker image also publishes standard OCI metadata labels such as version, revision, source repository, and build timestamp for easier registry inspection and traceability.

The Dockerfile pins both base images by digest so CI builds, local builds, and registry rebuilds all resolve to the same upstream image contents until you intentionally refresh them.

The image is built in two stages:

- `builder`: installs pinned `tini`, resolves dependencies with `uv`, and builds the application virtualenv
- `runtime`: copies only the virtualenv, app files, and `tini`, then runs as an unprivileged user with fixed UID/GID `10001`

When you want to roll those pins forward, run:

```bash
make docker-refresh-digests
```

For preview-only output without editing the Dockerfile:

```bash
DRY_RUN=true ./ops/refresh-docker-base-digests.sh
```

Useful commands:

```bash
make docker-build
make docker-up
make docker-down
make docker-refresh-digests
```

To build and optionally push a registry image directly:

```bash
IMAGE_NAME=ghcr.io/your-org/fastapi-chassis IMAGE_TAG=latest make docker-push
```

For remote hosts that should pull a prebuilt image, use `docker-compose.deploy.yml` together with:

```bash
IMAGE_NAME=ghcr.io/your-org/fastapi-chassis IMAGE_TAG=latest make docker-deploy-compose
```

Production-oriented deploys default `RUN_DB_MIGRATIONS=false` so migrations remain an explicit choice instead of running on every container restart. Set `RUN_DB_MIGRATIONS=true` in the target environment only when that startup behavior is intentional.

`docker-compose.deploy.yml` is intentionally separate from the local Compose file. It assumes a published image and adds runtime hardening such as `read_only`, `tmpfs`, `cap_drop: ALL`, and `no-new-privileges`.

## Database And Migrations

The template uses SQLite by default and is intended to work out of the box without any extra infrastructure:

```bash
APP_DATABASE_URL=sqlite+aiosqlite:///./data/app.db
APP_ALEMBIC_DATABASE_URL=sqlite:///./data/app.db
```

The default runtime path and migration path both point at the same SQLite database file under `./data/`, so local development, tests, and first-run setup all start from the same baseline.

If you later move to Postgres or another database, set both `APP_DATABASE_URL` and `APP_ALEMBIC_DATABASE_URL` explicitly.

Common migration commands:

```bash
uv run alembic -c alembic.ini upgrade head
uv run alembic -c alembic.ini downgrade -1
uv run alembic -c alembic.ini revision --autogenerate -m "describe change"
```

Equivalent `make` targets are available:

```bash
make db-upgrade
make db-downgrade
make db-revision MESSAGE="describe change"
```

## Stateless JWT Auth

This template treats the API as a resource server. It validates externally-issued bearer tokens and does not manage login sessions.

Supported validation modes:

- Shared secret via `APP_AUTH_JWT_SECRET` for local/dev/test use
- Static public key via `APP_AUTH_JWT_PUBLIC_KEY`
- Rotating keys via `APP_AUTH_JWKS_URL`

Use exactly one JWT signing-key family per deployment. Do not mix `HS*` algorithms with `RS*`/`ES*`/`PS*` algorithms or combine shared secrets with JWKS/public-key validation material. `APP_AUTH_JWKS_URL` must use `https://`.

When `APP_AUTH_ENABLED=true`, you must provide explicit verification material. The template fails closed if you enable auth without a 32+ character HS secret, a static public key, or a JWKS URL. By default it also requires `iss`, `aud`, and `exp` validation so the resource server does not accept non-expiring or ambiguously scoped tokens.

When JWKS is configured, the auth service refreshes once on `kid` cache misses so key rotation does not wait for cache expiry. If a refresh fails but an earlier JWKS cache exists, the service can keep validating tokens signed by already-cached keys and surfaces that degraded state in readiness details. Tokens signed with brand new keys still require a successful refresh.

Example auth settings:

```bash
APP_AUTH_ENABLED=true
APP_AUTH_JWT_ISSUER=https://issuer.example.com/
APP_AUTH_JWT_AUDIENCE=fastapi-chassis
APP_AUTH_JWT_ALGORITHMS=["RS256"]
APP_AUTH_JWKS_URL=https://issuer.example.com/.well-known/jwks.json
```

Example protected routes are available under:

- `GET /api/v1/me`
- `GET /api/v1/reports`
- `GET /api/v1/admin`

## Health, Readiness, Metrics, And Tracing

- `GET /healthcheck`: liveness only
- `GET /ready`: aggregates readiness checks for app, database, and auth dependencies
- `GET /metrics`: optional Prometheus scrape target when metrics are enabled

`/healthcheck` answers whether the process is up. `/ready` answers whether the process is actually ready to serve traffic with its configured dependencies.

Readiness responses hide dependency error details by default. Set `APP_READINESS_INCLUDE_DETAILS=true` only for trusted internal environments where that extra diagnostic detail is useful.

Metrics are disabled by default. Enable them only when the scrape endpoint is intentionally reachable from your monitoring plane:

```bash
APP_METRICS_ENABLED=true
```

To enable tracing:

```bash
APP_OTEL_ENABLED=true
APP_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
APP_OTEL_ENVIRONMENT=production
```

Prometheus alert examples live in `ops/monitoring/prometheus-alerts.yml`.

## Security Hardening

The template includes:

- Fixed-window rate limiting with in-memory or Redis-backed storage
- Security headers middleware
- Trusted-host enforcement
- Request body size limits
- Configurable CORS with production-safe defaults
- Opt-in OpenAPI/docs exposure for local development
- Optional diagnostic endpoints (`/info`, `/endpoints`) that stay disabled unless explicitly enabled

Recommended production settings:

```bash
APP_TRUSTED_HOSTS=["api.example.com"]
APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_STORAGE_URL=redis://redis:6379/0
APP_RATE_LIMIT_TRUST_PROXY_HEADERS=true
APP_RATE_LIMIT_TRUSTED_PROXIES=["10.0.0.0/8","192.168.0.0/16"]
APP_SECURITY_HSTS_ENABLED=true
APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true
APP_SECURITY_TRUSTED_PROXIES=["10.0.0.0/8","192.168.0.0/16"]
APP_CORS_ALLOWED_ORIGINS=["https://app.example.com"]
```

The in-memory rate limit store is suitable for local development and single-process deployments. For multi-worker or multi-instance production environments, configure `APP_RATE_LIMIT_STORAGE_URL` so limits are enforced consistently through Redis. The template no longer supports request-ID-based rate-limit keys because callers control those values. If the app sits behind a trusted reverse proxy, opt in to proxy-aware rate limiting and HTTPS header handling with the dedicated `*_TRUST_PROXY_*` settings instead of relying on forwarded headers implicitly. Proxy-aware rate limiting now requires `APP_RATE_LIMIT_TRUSTED_PROXIES`, and proxy-aware HTTPS handling now requires `APP_SECURITY_TRUSTED_PROXIES`, so arbitrary callers cannot spoof forwarded headers.

## Testing And Code Quality

```bash
make test                # all tests
make test-unit           # unit tests only
make test-integration    # integration tests only
make coverage            # tests with coverage report
make ci                  # full CI gate (lint + format + type-check + tests + coverage)
```

The project enforces a 90% minimum coverage threshold (currently 98%+). Tests are hermetic — local `.env` values do not leak into test runs.

For the full testing guide covering test architecture, writing tests, shared helpers, fixtures, and the checklist for new features, see [`docs/testing.md`](docs/testing.md).

For a quick local runtime smoke test, `make smoke` applies migrations, starts the app on an alternate port, verifies `/`, `/healthcheck`, and `/ready`, and then shuts the process down automatically.

For a broader live-stack verification, `make verify-stack` boots an isolated app instance with a temporary SQLite database, local JWT auth, Prometheus metrics, and a lightweight OTLP capture endpoint, then checks database, auth, tracing, metrics, error handlers, and API behavior over real HTTP. See [`docs/testing-stack.md`](docs/testing-stack.md) for the full workflow and coverage details.

For production-like dependency coverage, `make verify-stack-prodlike` points the same harness at Postgres, Redis, and a real JWKS flow. The default target values assume Postgres on `127.0.0.1:5432` and Redis on `127.0.0.1:6379`, which pairs with `docker compose -f docker-compose.postgres.yml -f docker-compose.redis.yml up -d`.

## Runtime Modes

Use one of these three configuration shapes:

```bash
# 1. Local default: SQLite + in-memory rate limiting
APP_DATABASE_BACKEND=sqlite
APP_DATABASE_SQLITE_PATH=./data/app.db
APP_RATE_LIMIT_STORAGE_BACKEND=memory
```

```bash
# 2. Production-like: Postgres + Redis
APP_DATABASE_BACKEND=postgres
APP_DATABASE_POSTGRES_HOST=postgres
APP_DATABASE_POSTGRES_PORT=5432
APP_DATABASE_POSTGRES_NAME=fastapi_chassis
APP_DATABASE_POSTGRES_USER=fastapi
APP_DATABASE_POSTGRES_PASSWORD=change-me
APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_STORAGE_BACKEND=redis
APP_REDIS_HOST=redis
APP_REDIS_PORT=6379
APP_REDIS_DB=0
```

```bash
# 3. Fully custom: explicit URLs
APP_DATABASE_BACKEND=custom
APP_DATABASE_URL=postgresql+asyncpg://user:pass@db.internal:5432/app
APP_ALEMBIC_DATABASE_URL=postgresql+psycopg://user:pass@db.internal:5432/app
APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_STORAGE_URL=redis://cache.internal:6379/0
```

For production operations guidance, deployment notes, and troubleshooting, see [`docs/operations.md`](docs/operations.md).

Git hook automation is also available through `pre-commit`:

```bash
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pre-commit run --all-files
```

The included hook config runs Ruff lint checks before commits, then MyPy and unit tests before pushes.

The repository ships with a GitHub Actions workflow at `.github/workflows/ci.yml` that runs the same `make ci` quality gate in CI and then boots the built image until `/ready` succeeds.

Container workflows are included too:

- `.github/workflows/ci.yml`: runs Python checks, builds the Docker image, and smoke-tests container startup/readiness
- `.github/workflows/docker-image.yml`: reruns the quality gate, then builds and pushes the app image to GHCR
- `.github/workflows/deploy-image.yml`: deploys the published image with `docker run`
- `.github/workflows/deploy-compose.yml`: deploys the published image with `docker compose`

The deploy helpers now verify both container-local readiness and host-level
reachability. The workflow-dispatch deploy jobs accept verification inputs such
as `verify_host`, `verify_scheme`, and optional `verify_host_header` so the
post-deploy check can exercise the same hostname/path combination operators and
reverse proxies use.

The Docker build workflows use the GitHub Actions cache backend for BuildKit layers and publish a small image-size benchmark summary in CI so container regressions are easier to spot.

The deploy workflows expect these GitHub secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PORT` (optional; defaults to `22`)
- `DEPLOY_PATH` (remote directory where deployment assets should live)
- `DEPLOY_ENV_FILE` (full `.env` file contents for the target environment)
- `GHCR_USERNAME` and `GHCR_TOKEN` when the registry image is private

Or use the Makefile:

```bash
make check
make ci
```

## Helm Chart (Kubernetes)

The repository includes a production-ready Helm chart in `chart/` for deploying to Kubernetes. The chart automatically selects Deployment (Postgres/custom) or StatefulSet (SQLite) based on the database backend, includes security hardening, and supports optional LiteFS/Litestream replication for SQLite.

```bash
# Postgres backend (default)
helm install my-app ./chart \
  --set image.tag=1.0.0 \
  --set database.postgres.host=postgres.default \
  --set database.postgres.password=changeme

# SQLite backend
helm install my-app ./chart \
  --set image.tag=1.0.0 \
  --set database.backend=sqlite \
  --set replicaCount=1
```

The chart includes Ingress, HPA, PDB, NetworkPolicy, ServiceMonitor, migration Jobs, and per-component `existingSecret` support. For the full guide see [`docs/helm-chart.md`](docs/helm-chart.md). For the values reference see [`chart/README.md`](chart/README.md).

## Project Structure

```bash
├── alembic/                  # Alembic environment and revisions
├── main.py                   # Application entry point
├── .github/workflows/        # CI and deployment workflows
├── Makefile                  # Common dev and CI commands
├── Dockerfile                # Multi-stage production image build
├── docker-compose.yml        # Local SQLite-first runtime
├── docker-compose.postgres.yml # Local Postgres-first runtime
├── docker-compose.redis.yml  # Optional Redis overlay for local stacks
├── docker-compose.deploy.yml # Remote compose deployment using a pushed image
├── ops/monitoring/           # Example alerting rules
├── chart/                    # Helm chart for Kubernetes deployment
├── docs/architecture.md      # Application structure and request flow
├── docs/helm-chart.md        # Helm chart deployment guide
├── docs/operations.md        # Deployment and runtime operations guide
├── docs/testing.md           # Developer testing guide
├── docs/testing-stack.md     # Live stack verification guide
├── docs/adr/                 # Architecture decision records
├── ops/docker-*.sh           # Docker build and deployment helper scripts
├── ops/test_stack.py         # Live DB/auth/tracing/metrics/API verification harness
├── pyproject.toml            # Project config & dependencies
├── src/
│   └── app/
│       ├── auth/             # JWT validation and authorization dependencies
│       ├── db/               # SQLAlchemy engine, models, sessions, readiness
│       ├── middleware/       # Request/response hardening
│       ├── observability/    # OpenTelemetry tracing setup
│       ├── readiness/        # Dependency-aware readiness registry
│       ├── routes/           # Health and API routes
│       ├── app_builder.py    # Builder pattern configuration
│       ├── lifespan.py       # Startup/shutdown lifecycle
│       └── settings.py       # Pydantic settings
└── tests/                    # Unit and integration coverage
```

## Key Environment Variables

See [`.env.example`](.env.example) for the complete set. The most important ones are:

| Variable | Default | Description |
| --- | --- | --- |
| `APP_DATABASE_BACKEND` | `sqlite` | Select `sqlite`, `postgres`, or `custom` database wiring |
| `APP_DATABASE_SQLITE_PATH` | `./data/app.db` | SQLite file path used when `APP_DATABASE_BACKEND=sqlite` |
| `APP_DATABASE_SQLITE_JOURNAL_MODE` | `wal` | SQLite journal mode (WAL enables concurrent readers) |
| `APP_DATABASE_SQLITE_SYNCHRONOUS` | `normal` | SQLite synchronous setting (safe with WAL) |
| `APP_DATABASE_SQLITE_BUSY_TIMEOUT` | `5000` | Milliseconds to wait on a locked database |
| `APP_DATABASE_SQLITE_CACHE_SIZE` | `-64000` | Page cache size in KiB (negative = KiB, −64000 = 64 MB) |
| `APP_DATABASE_SQLITE_MMAP_SIZE` | `0` | Memory-mapped I/O size in bytes (0 = disabled) |
| `APP_DATABASE_SQLITE_FOREIGN_KEYS` | `true` | Enforce foreign key constraints |
| `APP_DATABASE_URL` | derived from backend | Explicit async SQLAlchemy URL override |
| `APP_ALEMBIC_DATABASE_URL` | derived from backend | Explicit sync Alembic URL override |
| `APP_DOCS_ENABLED` | `false` | Expose Swagger UI at `/docs` |
| `APP_OPENAPI_ENABLED` | `false` | Expose the OpenAPI schema |
| `APP_AUTH_ENABLED` | `false` | Enable JWT validation for protected routes |
| `APP_AUTH_REQUIRE_EXP` | `true` | Require `exp` on validated JWTs |
| `APP_AUTH_JWKS_URL` | empty | Remote JWKS endpoint for public key discovery |
| `APP_AUTH_JWKS_MAX_STALE_SECONDS` | `3600` | Max time a stale JWKS cache is accepted after refresh failure (0 = never) |
| `APP_AUTH_REQUIRE_WARMUP` | `false` | Require JWKS to be reachable at startup; abort if unreachable |
| `APP_OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing |
| `APP_METRICS_ENABLED` | `false` | Enable the Prometheus `/metrics` endpoint |
| `APP_RATE_LIMIT_ENABLED` | `false` | Enable fixed-window request rate limiting |
| `APP_RATE_LIMIT_STORAGE_BACKEND` | `memory` | Select `memory` or `redis` storage for rate limiting |
| `APP_RATE_LIMIT_STORAGE_URL` | derived from backend | Explicit Redis URL override |
| `APP_RATE_LIMIT_TRUSTED_PROXIES` | `[]` | Proxy IPs/CIDRs allowed to supply forwarded client IP headers |
| `APP_SECURITY_TRUSTED_PROXIES` | `[]` | Proxy IPs/CIDRs allowed to supply forwarded protocol headers |
| `APP_TRUSTED_HOSTS` | local-only defaults | Allowed `Host` headers accepted by the app |
| `APP_MAX_REQUEST_BODY_BYTES` | `5242880` | Maximum allowed request body size |
| `APP_HEALTH_CHECK_PATH` | `/healthcheck` | Liveness endpoint path |
| `APP_READINESS_CHECK_PATH` | `/ready` | Readiness endpoint path |
| `APP_READINESS_INCLUDE_DETAILS` | `false` | Include dependency error details in readiness responses |
| `APP_INFO_ENDPOINT_ENABLED` | `false` | Expose the `/info` diagnostic endpoint |
| `APP_ENDPOINTS_LISTING_ENABLED` | `false` | Expose the `/endpoints` route inventory |

SQLite remains the default so the template starts locally without extra infrastructure. For multi-worker or higher-write production deployments, switch to `APP_DATABASE_BACKEND=postgres` or provide custom URLs instead of relying on the default file-backed SQLite configuration. Validation errors redact rejected input values by default so malformed requests do not echo secrets back to callers or logs.

For local production-like runs, the repository also exposes optional Postgres and Redis Compose profiles. Enable only the backing services you need, then select them in `.env` with `APP_DATABASE_BACKEND=postgres` and `APP_RATE_LIMIT_STORAGE_BACKEND=redis`. Explicit `APP_DATABASE_URL`, `APP_ALEMBIC_DATABASE_URL`, and `APP_RATE_LIMIT_STORAGE_URL` values still work when you need fully custom wiring.
