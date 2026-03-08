# Live Stack Verification

This repository already has broad automated coverage through `pytest`. The live
verification harness is a separate confidence check for the running stack: it
boots the app, drives real HTTP traffic, and verifies the main subsystems work
together with realistic configuration.

## When To Use It

Use this flow when you want a quick end-to-end sanity check for:

- database wiring and readiness,
- JWT auth and authorization,
- Prometheus metrics exposure,
- OpenTelemetry trace export,
- structured error handlers,
- and the example API routes.

Keep using `make test`, `make test-unit`, and `make test-integration` as the
main regression suite. `make verify-stack` is a live-system check, not a
replacement for automated tests.

## Command

```bash
make verify-stack
make verify-stack-prodlike
```

Equivalent raw command:

```bash
uv run python ops/test_stack.py
```

Production-like mode:

```bash
VERIFY_STACK_DATABASE_URL=postgresql+asyncpg://fastapi:fastapi@127.0.0.1:5432/fastapi_template \
VERIFY_STACK_ALEMBIC_DATABASE_URL=postgresql+psycopg://fastapi:fastapi@127.0.0.1:5432/fastapi_template \
VERIFY_STACK_REDIS_URL=redis://127.0.0.1:6379/0 \
VERIFY_STACK_AUTH_MODE=jwks \
uv run python ops/test_stack.py
```

## What The Script Does

The harness is intentionally hermetic and does not depend on your local
`APP_*` environment variables or an external tracing backend.

On each run it:

1. creates a temporary SQLite database file, or uses externally supplied DB
   URLs when `VERIFY_STACK_DATABASE_URL` and
   `VERIFY_STACK_ALEMBIC_DATABASE_URL` are set,
2. applies Alembic migrations to the selected database,
3. starts a local OTLP HTTP capture endpoint,
4. boots the FastAPI app on a temporary localhost port with:
   - auth enabled,
   - metrics enabled,
   - tracing enabled,
   - readiness details enabled,
   - optional Redis-backed rate limiting when `VERIFY_STACK_REDIS_URL` is set,
   - optional JWKS validation when `VERIFY_STACK_AUTH_MODE=jwks`,
5. adds temporary verification-only routes used to exercise database and error
   paths,
6. sends live HTTP requests to the running app,
7. exits non-zero if any check fails.

## Checks Performed

The script verifies the following behavior:

- `GET /`, `GET /healthcheck`, and `GET /ready` return healthy responses.
- readiness reports healthy `database` and `auth` dependencies.
- a temporary verification route can write and read `ExampleWidget` rows using
  the app's configured async session factory.
- `GET /api/v1/me` rejects missing credentials with `401`.
- valid JWTs can access `GET /api/v1/me`, `GET /api/v1/reports`, and
  `GET /api/v1/admin`.
- a non-admin JWT is rejected from `GET /api/v1/admin` with `403`.
- when Redis verification is enabled, repeated requests are throttled through
  the configured Redis-backed rate-limit store.
- `GET /metrics` is exposed and returns Prometheus output.
- a validation failure returns the normalized `422` error payload without
  echoing rejected input values.
- an unhandled exception returns the sanitized `500` error payload.
- the OpenTelemetry exporter sends at least one OTLP trace batch to the local
  capture endpoint.

## Expected Output

On success, the script prints each verification step and finishes with:

```text
[verify-stack] All live verification checks passed
```

If a step fails, it prints an `ERROR:` line and exits with status `1`.

## Notes

- The verification routes exist only inside the harness-created app instance.
  They are not added to the normal application code path.
- The run is localhost-only and uses temporary ports, so it should not conflict
  with your normal `make run` workflow.
- Because the script starts its own OTLP capture endpoint, you do not need
  Prometheus, Jaeger, Tempo, or an OpenTelemetry Collector running locally.
- `make verify-stack-prodlike` assumes local Postgres and Redis listeners on
  `127.0.0.1`. The repository's `docker-compose.postgres.yml` plus
  `docker-compose.redis.yml` provide the Postgres + Redis local stack for that
  workflow.
