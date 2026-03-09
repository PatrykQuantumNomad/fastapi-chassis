# Operations Guide

This document collects the deployment and runtime expectations for the
FastAPI template so operators do not need to reverse-engineer workflows and
shell scripts before putting the service in front of users.

## Supported Deployment Modes

### Local Development

Use this for feature work and routine development:

```bash
make install
cp .env.sqlite.example .env
make db-upgrade
make run
```

### Local Container Runtime

Use this when validating the Docker image and local container behavior:

```bash
docker compose up --build
```

This default file is the SQLite-first local stack. Add Redis only when you want
to validate Redis-backed rate limiting:

```bash
docker compose -f docker-compose.yml -f docker-compose.redis.yml up --build
```

That gives you two SQLite-first day-to-day options:

- `.env.sqlite.example` with `docker compose up --build`
- `.env.sqlite-redis.example` with
  `docker compose -f docker-compose.yml -f docker-compose.redis.yml up --build`

Use the Postgres-first local stack when you want the app and database wiring to
match a server-style backend more closely:

```bash
docker compose -f docker-compose.postgres.yml up --build
docker compose -f docker-compose.postgres.yml -f docker-compose.redis.yml up --build
```

### Remote Image Deployment

Use `ops/docker-deploy-image.sh` or `.github/workflows/deploy-image.yml` when
the host should run a published image with `docker run`.

### Remote Compose Deployment

Use `ops/docker-deploy-compose.sh` or `.github/workflows/deploy-compose.yml`
when the host should deploy the published image through `docker compose`.
The checked-in deployment compose file is intentionally app-only; it does not
automatically provision Postgres or Redis for production.

See [`docs/vm-deployment.md`](vm-deployment.md) for the full VM deployment
guide covering both paths, GitHub Actions configuration, rollback behavior,
reverse proxy setup, and production checklist.

### Kubernetes (Helm)

Use the included Helm chart in `chart/` when deploying to Kubernetes:

```bash
helm install my-app ./chart -f my-values.yaml
```

The chart handles workload type selection (Deployment vs StatefulSet), ConfigMap
and Secret generation, Ingress, HPA, PDB, NetworkPolicy, ServiceMonitor, and
migration Jobs. See [`docs/helm-chart.md`](helm-chart.md) for the full
deployment guide and [`chart/README.md`](../chart/README.md) for the values
reference.

## Runtime Modes

Use one of these four runtime shapes and keep the `.env` values aligned with
the infrastructure you actually provide:

```bash
# 1. Local default: SQLite + in-memory rate limiting
APP_DATABASE_BACKEND=sqlite
APP_DATABASE_SQLITE_PATH=./data/app.db
APP_RATE_LIMIT_STORAGE_BACKEND=memory
```

```bash
# 2. Local validation: SQLite + Redis
APP_DATABASE_BACKEND=sqlite
APP_DATABASE_SQLITE_PATH=./data/app.db
APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_STORAGE_BACKEND=redis
APP_REDIS_HOST=redis
APP_REDIS_PORT=6379
APP_REDIS_DB=0
```

```bash
# 3. Production-like or small deployment: Postgres + Redis
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
# 4. Fully custom wiring: explicit URLs
APP_DATABASE_BACKEND=custom
APP_DATABASE_URL=postgresql+asyncpg://user:pass@db.internal:5432/app
APP_ALEMBIC_DATABASE_URL=postgresql+psycopg://user:pass@db.internal:5432/app
APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_STORAGE_URL=redis://cache.internal:6379/0
```

The repository includes small starter presets for the first three modes:

- `.env.sqlite.example`
- `.env.sqlite-redis.example`
- `.env.postgres-redis.example`

## Host Prerequisites

- Docker installed and usable by the deploy user.
- SSH access for GitHub Actions based deployment workflows.
- Writable persistence for `/app/data` if SQLite is still in use.
- An `.env` file with production values for all required `APP_*` settings.
- A reverse proxy or load balancer if TLS termination, host routing, or
  internet exposure is required.

## Production Configuration Minimums

Before putting the service in production, set at least:

- `APP_DATABASE_BACKEND`
- either the backend-specific DB fields or explicit `APP_DATABASE_URL` and
  `APP_ALEMBIC_DATABASE_URL`
- `APP_TRUSTED_HOSTS`
- `APP_CORS_ALLOWED_ORIGINS`
- `APP_AUTH_*` values if protected routes are enabled
- `APP_RATE_LIMIT_STORAGE_BACKEND=redis` or explicit
  `APP_RATE_LIMIT_STORAGE_URL` for multi-worker or multi-instance deployments
- `APP_RATE_LIMIT_TRUSTED_PROXIES` when
  `APP_RATE_LIMIT_TRUST_PROXY_HEADERS=true`
- `APP_SECURITY_TRUSTED_PROXIES` when
  `APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true`

Recommended additional settings:

- `APP_SECURITY_HSTS_ENABLED=true` when HTTPS is terminated before the app
- `APP_METRICS_ENABLED=true` only when `/metrics` is intentionally reachable
- `APP_OTEL_ENABLED=true` plus an OTLP endpoint when trace export is desired

## Database Guidance

The repository ships with SQLite defaults to make local startup trivial. That
is not the same as a general production recommendation.

Database selection model:

- `APP_DATABASE_BACKEND=sqlite`: derive SQLite URLs from `APP_DATABASE_SQLITE_PATH`
- `APP_DATABASE_BACKEND=postgres`: derive URLs from the
  `APP_DATABASE_POSTGRES_*` fields
- `APP_DATABASE_BACKEND=custom`: use explicit `APP_DATABASE_URL` and
  `APP_ALEMBIC_DATABASE_URL`

SQLite is viable for production when properly configured:

- WAL journal mode enables concurrent readers alongside a single writer,
- production pragmas (synchronous, busy_timeout, cache_size, foreign_keys) are
  applied automatically on every new connection via SQLAlchemy event listeners,
- persistent storage (Kubernetes StatefulSet with PVC, Docker volume) keeps the
  database file durable across restarts,
- Litestream provides continuous disaster recovery via WAL shipping to S3/GCS,
- LiteFS provides horizontal scaling with FUSE-based distributed replication.

Use SQLite when:

- writes follow a single-writer pattern (one process, or LiteFS primary routing),
- read-heavy workloads dominate,
- operational simplicity is valued over multi-writer concurrency,
- backup and restore of the DB file are understood by the operator.

Move to Postgres or another server database when:

- multiple independent writers are required without LiteFS,
- sustained high-concurrency write traffic exceeds SQLite's single-writer throughput,
- managed production hosting where local container filesystem state is brittle
  and replication tooling (LiteFS/Litestream) is not desired.

SQLite production pragmas are configured via environment variables and applied
automatically at engine startup:

| Variable | Default | Effect |
| --- | --- | --- |
| `APP_DATABASE_SQLITE_JOURNAL_MODE` | `wal` | WAL enables concurrent readers with a single writer |
| `APP_DATABASE_SQLITE_SYNCHRONOUS` | `normal` | Safe with WAL; avoids full fsync per commit |
| `APP_DATABASE_SQLITE_BUSY_TIMEOUT` | `5000` | Milliseconds to wait on a locked database |
| `APP_DATABASE_SQLITE_CACHE_SIZE` | `-64000` | Page cache size in KiB (negative = KiB) |
| `APP_DATABASE_SQLITE_MMAP_SIZE` | `0` | Memory-mapped I/O size in bytes (0 = disabled) |
| `APP_DATABASE_SQLITE_FOREIGN_KEYS` | `true` | Enforce foreign key constraints |

See [`docs/configuration.md`](configuration.md) for the full database variable reference.

Rate-limit storage selection model:

- `APP_RATE_LIMIT_STORAGE_BACKEND=memory`: no Redis dependency
- `APP_RATE_LIMIT_STORAGE_BACKEND=redis`: derive Redis URL from `APP_REDIS_*`
- explicit `APP_RATE_LIMIT_STORAGE_URL`: override either selector when needed

## Worker Processes

The container entrypoint defaults to a single Uvicorn worker (`UVICORN_WORKERS=1`).
This follows the official FastAPI recommendation: in orchestrated environments
(Kubernetes, Docker Swarm, ECS) let the platform manage replication by running
one process per container and scaling the number of container replicas instead.

For single-server or Docker Compose deployments that need to utilise multiple
CPU cores, increase the worker count explicitly:

```bash
UVICORN_WORKERS=4
```

Keep in mind:

- Each worker is an independent OS process with its own memory. Total RAM
  usage equals per-worker footprint multiplied by the number of workers.
- In-memory rate limiting and in-memory caching are per-process. Use
  Redis-backed storage when running more than one worker.
- SQLite does not support concurrent writes from multiple processes. Move to
  Postgres before using multiple workers.

### Kubernetes and Similar Orchestrators

When deploying to Kubernetes, Docker Swarm, or cloud container services:

- Keep `UVICORN_WORKERS=1` (the default).
- Scale horizontally by increasing the replica count at the orchestrator level.
- Use the readiness endpoint (`/ready`) as the readiness probe so new replicas
  only receive traffic once they are fully initialised.
- Use the liveness endpoint (`/healthcheck`) as the liveness probe.
- Set `terminationGracePeriodSeconds` to at least Uvicorn's graceful shutdown
  timeout plus a small buffer.
- Resource limits (`resources.limits.memory`) become predictable with a single
  worker because there is no intra-container process multiplication.

This approach gives the orchestrator full visibility into per-instance health,
simplifies memory budgeting, and avoids duplicating scaling logic inside the
container.

## Proxy Headers

The container entrypoint passes `--proxy-headers` to Uvicorn so that
`X-Forwarded-For`, `X-Forwarded-Proto`, and related headers are honoured at
the ASGI level. This is required when the app sits behind a reverse proxy or
load balancer (Nginx, Traefik, ALB, etc.).

By default Uvicorn only trusts these headers from `127.0.0.1`. In container
networks the proxy typically reaches the app from a different IP. Set
`UVICORN_FORWARDED_ALLOW_IPS` to the proxy's address or CIDR:

```bash
# Trust a specific proxy
UVICORN_FORWARDED_ALLOW_IPS=10.0.0.1

# Trust an entire subnet
UVICORN_FORWARDED_ALLOW_IPS=10.0.0.0/8

# Trust any source (only when the app is truly unreachable except through proxies)
UVICORN_FORWARDED_ALLOW_IPS=*
```

This is separate from the application-level proxy trust settings
(`APP_SECURITY_TRUSTED_PROXIES`, `APP_RATE_LIMIT_TRUSTED_PROXIES`). Both
layers must be configured for proxy-aware features to work correctly:

- **Uvicorn level** (`UVICORN_FORWARDED_ALLOW_IPS`): populates `request.client`
  and `request.url.scheme` in the ASGI scope.
- **Application level** (`APP_SECURITY_TRUSTED_PROXIES`,
  `APP_RATE_LIMIT_TRUSTED_PROXIES`): controls which middleware features honour
  forwarded headers for HSTS decisions and client IP extraction.

## Reverse Proxy And Header Trust

If the app sits behind a trusted reverse proxy:

- keep `APP_TRUSTED_HOSTS` aligned with public hostnames,
- enable `APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true` only when the proxy is
  the sole ingress path,
- configure `APP_SECURITY_TRUSTED_PROXIES` to the exact proxy IPs/CIDRs that
  are allowed to supply `X-Forwarded-Proto`,
- enable `APP_RATE_LIMIT_TRUST_PROXY_HEADERS=true` only when the app is
  reachable exclusively through proxies listed in
  `APP_RATE_LIMIT_TRUSTED_PROXIES`.

Do not trust forwarded headers from arbitrary callers. The template now
requires explicit trusted-proxy allowlists before proxy-aware rate limiting or
proxy-aware HTTPS semantics are accepted.

## Deployment Steps

### Image Deploy Rollback

1. Build and publish the image.
2. Copy the deploy script and environment file to the host.
3. Run the image deploy helper.
4. Wait for container health, container-local readiness, and host-level
   readiness verification to report success.
5. Verify `/healthcheck` and `/ready` through the same path operators will use.

### Compose Deploy Rollback

1. Publish the image.
2. Copy `docker-compose.deploy.yml`, the deploy helper, and `.env` to the host.
3. Run the compose deploy helper.
4. Verify the app becomes healthy, ready, and reachable through the published
   host port.
5. Confirm logs, exposed ports, and proxy behavior match expectations.

## Deployment Verification Inputs

The deploy workflows and helper scripts support explicit host-level
verification parameters:

- `VERIFY_HOST`: target host used for post-deploy probing
- `VERIFY_SCHEME`: `http` or `https`
- `VERIFY_HOST_HEADER`: optional `Host` header override for trusted-host or
  reverse-proxy validation

Use these when the deploy host must verify more than container-local readiness,
for example when:

- trusted hosts reject `127.0.0.1`,
- the app is exposed through a reverse proxy,
- the deployment path should verify the externally expected hostname.

## Migrations

For local development, migrations can run automatically at startup.

For production, treat migrations as an explicit rollout step unless you have
intentionally decided to couple them to container startup.

Common commands:

```bash
make db-upgrade
make db-downgrade
make db-revision MESSAGE="describe change"
```

For image-based production deploys, prefer:

1. run migrations explicitly,
2. deploy the new version,
3. verify readiness and smoke behavior,
4. then shift traffic if applicable.

## Verification

Use these layers of verification:

- `make check`: lint, type-check, and tests
- `make ci`: full local quality gate including coverage
- `make smoke`: local process smoke test
- `make verify-stack`: live DB/auth/metrics/tracing/API verification

`make verify-stack` is the closest thing to an end-to-end runtime check in this
repository and should be run before releases that change infrastructure wiring,
middleware behavior, auth configuration, or observability setup.

## Monitoring Expectations

At minimum, monitor:

- service health and readiness,
- container restarts,
- error rate,
- request latency,
- authentication failures,
- database connectivity,
- rate-limit rejects if the feature is enabled.

### Prometheus Metrics

When `APP_METRICS_ENABLED=true`, the app exposes a Prometheus scrape target at
`/metrics`. The `starlette-exporter` middleware emits these core metrics using
the prefix configured by `APP_METRICS_PREFIX` (default `http`):

| Metric | Type | Description |
| --- | --- | --- |
| `<prefix>_requests_total` | Counter | Total request count by method, path, and status |
| `<prefix>_request_duration_seconds` | Histogram | Request latency distribution |

If you change `APP_METRICS_PREFIX`, update all alert rules, dashboards, and
recording rules that reference these metric names.

### Prometheus Alert Rules

Example alert rules live in `ops/monitoring/prometheus-alerts.yml`. These
are starting points; tune thresholds and `for` durations to your SLOs.

| Alert | Severity | Fires When |
| --- | --- | --- |
| `FastAPIHigh5xxRate` | critical | >5% of requests return 5xx for 10 minutes |
| `FastAPIHighLatencyP95` | warning | p95 latency exceeds 1 second for 10 minutes |
| `FastAPIReadinessFailures` | critical | `/ready` returns 503 for 5 minutes |
| `FastAPIRateLimitSpike` | warning | >1 rate-limit rejection per second for 10 minutes |

To adapt the alerts to a custom metrics prefix, replace `http_requests_total`
and `http_request_duration_seconds_bucket` in the alert expressions with your
prefixed equivalents (e.g. `myapp_requests_total`).

## Rollback Guidance

### Image Deploy

The image deploy helper now preserves the previous container under a rollback
name until the replacement passes:

- Docker health checks,
- in-container readiness,
- host-level readiness verification.

If the replacement fails any of those checks, the helper restores the preserved
container instead of reconstructing rollback state from image coordinates alone.

### Compose Deploy

The compose deploy helper now tags the currently running app image as a local
rollback candidate before replacing it. If the new release fails Docker health,
in-container readiness, or host-level verification, the helper automatically
re-runs the Compose deployment against that preserved rollback tag.

Operators should still:

1. review deploy logs to confirm whether automatic rollback ran,
2. confirm the restored revision is healthy and serving traffic,
3. retag or redeploy the last known-good release explicitly once the incident is understood,
4. evaluate whether schema rollback is needed before downgrading code.

Do not assume database schema downgrades are always safe. Review the migration
before rolling back code across schema changes.

## Troubleshooting

### `/healthcheck` is healthy but `/ready` fails

- inspect DB connectivity and credentials,
- inspect auth/JWKS configuration,
- enable readiness details temporarily in a trusted environment if needed.

### Authenticated requests start failing after an IdP issue

- inspect readiness details for stale JWKS cache usage,
- confirm the issuer JWKS endpoint is reachable,
- confirm the token `kid` exists in the issuer key set,
- remember that a stale cache only helps for already-known signing keys; brand
  new keys still require a successful JWKS refresh,
- check `APP_AUTH_JWKS_MAX_STALE_SECONDS` (default 3600) — once the stale
  cache exceeds this age, it is discarded and all JWKS-dependent validation
  fails until the endpoint recovers. Set to `0` to never accept stale keys,
- if `APP_AUTH_REQUIRE_WARMUP=true`, the app will not start when JWKS is
  unreachable at boot; check startup logs for "aborting startup" messages.

### Rate limiting behaves unexpectedly behind a proxy

- verify the app is only reachable through trusted proxies,
- confirm `APP_RATE_LIMIT_TRUSTED_PROXIES` matches the proxy source IP/CIDR,
- confirm proxies append client IPs consistently and that every internal proxy
  in the chain is represented in the trusted-proxy allowlist,
- confirm Redis is configured if limits must be shared across workers/instances.

### Docker Compose resource limits appear ignored

`deploy.resources` is not a strong isolation mechanism in plain
`docker compose up`. If hard CPU or memory enforcement is required, use a
platform that actually enforces those controls or apply host/runtime-specific
limits outside the compose file.

### Deploy script says healthy but traffic still fails

- verify `VERIFY_HOST`, `VERIFY_SCHEME`, and `VERIFY_HOST_HEADER`,
- confirm the post-deploy probe is checking the same hostname/path operators
  and load balancers use,
- confirm the reverse proxy forwards to the published app port you expect.

## Graceful Shutdown

The application handles SIGTERM/SIGINT signals through its lifespan
manager. When shutdown is initiated:

1. The process stops accepting new connections.
2. In-flight requests are allowed to complete up to Uvicorn's shutdown
   timeout (default 10 seconds, configurable via `--timeout-graceful-shutdown`).
3. The lifespan shutdown hook runs:
   - closes the shared `httpx.AsyncClient`,
   - disposes the SQLAlchemy async engine (closing pooled connections).
4. The process exits.

The Docker image uses `tini` as PID 1 to ensure signals are forwarded
correctly to the Uvicorn process.

### Tuning Graceful Shutdown

For production deployments with long-running requests, increase the
Uvicorn graceful shutdown timeout:

```bash
uvicorn main:app --timeout-graceful-shutdown 30
```

When using multiple workers, each worker receives the shutdown signal
independently. Ensure your load balancer or reverse proxy stops routing
new traffic to the instance before or at the same time as the shutdown
signal.

### Kubernetes / Orchestrator Integration

If deployed behind a Kubernetes Service or similar orchestrator:

- Set `terminationGracePeriodSeconds` to at least
  `--timeout-graceful-shutdown` + a small buffer.
- Use the readiness endpoint (`/ready`) as the readiness probe so traffic
  stops routing before shutdown begins.
- Use the liveness endpoint (`/healthcheck`) as the liveness probe.

## Before Production Checklist

- Use a server database for multi-worker or higher-write deployments.
- Set explicit trusted hosts and CORS origins.
- Use Redis-backed rate limiting for shared production limits.
- Restrict proxy-header trust to explicit proxy IPs/CIDRs.
- Configure auth verification material and validate readiness.
- Consider `APP_AUTH_REQUIRE_WARMUP=true` to fail fast on JWKS issues at boot.
- Review `APP_AUTH_JWKS_MAX_STALE_SECONDS` for your availability/security trade-off.
- Decide whether metrics and diagnostic routes should be exposed.
- Run `make ci` and `make verify-stack`.
- Document backup and restore for the chosen database.
- Document the release tag and rollback policy used by your team.
