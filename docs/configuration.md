# Configuration Reference

All application settings use the `APP_` environment variable prefix. Configuration priority (highest to lowest):

1. Environment variables
2. `.env` file
3. Default values

Use `.env.sqlite.example`, `.env.sqlite-redis.example`, or `.env.postgres-redis.example` as presets.

## Application Metadata

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_APP_NAME` | string | `FastAPI Template` | Application name used in metrics, logging, and OpenAPI docs |
| `APP_APP_VERSION` | string | `1.0.0` | Semantic version |
| `APP_APP_DESCRIPTION` | string | (see settings) | Application description for OpenAPI |
| `APP_DEBUG` | bool | `false` | Enable debug mode (exposes detailed error responses) |
| `APP_DOCS_ENABLED` | bool | `false` | Expose Swagger UI at `/docs` |
| `APP_REDOC_ENABLED` | bool | `false` | Expose ReDoc at `/redoc` |
| `APP_OPENAPI_ENABLED` | bool | `false` | Expose OpenAPI schema at `/openapi.json` |

## Server

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_HOST` | string | `127.0.0.1` | Server bind address |
| `APP_PORT` | int | `8000` | Server bind port (1–65535) |

## Logging

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_LOG_LEVEL` | string | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `APP_LOG_FORMAT` | string | `text` | Output format: `text` or `json` |
| `APP_LOG_TEXT_TEMPLATE` | string | (see settings) | Python logging format when `log_format` is text |
| `APP_LOG_DATE_FORMAT` | string | `%Y-%m-%d %H:%M:%S` | Date format for timestamps |
| `APP_LOGGING_CONFIG_PATH` | string | (bundled) | Path to JSON logging config; defaults to bundled |
| `APP_LOG_REDACT_HEADERS` | bool | `false` | Redact user-agent and referer in request logs |

## Database

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_DATABASE_BACKEND` | string | `sqlite` | Backend: `sqlite`, `postgres`, or `custom` |
| `APP_DATABASE_SQLITE_PATH` | string | `./data/app.db` | SQLite file path |
| `APP_DATABASE_POSTGRES_HOST` | string | `postgres` | Postgres host |
| `APP_DATABASE_POSTGRES_PORT` | int | `5432` | Postgres port |
| `APP_DATABASE_POSTGRES_NAME` | string | `fastapi_template` | Database name |
| `APP_DATABASE_POSTGRES_USER` | string | `fastapi` | Username |
| `APP_DATABASE_POSTGRES_PASSWORD` | string | (required for postgres) | Password |
| `APP_DATABASE_URL` | string | (derived) | Explicit async SQLAlchemy URL; overrides backend |
| `APP_ALEMBIC_DATABASE_URL` | string | (derived) | Explicit sync Alembic URL |
| `APP_DATABASE_ECHO` | bool | `false` | Enable SQL echo logging |
| `APP_DATABASE_POOL_SIZE` | int | `5` | Connection pool size (1–100) |
| `APP_DATABASE_MAX_OVERFLOW` | int | `10` | Max overflow connections |
| `APP_DATABASE_POOL_PRE_PING` | bool | `true` | Ping connections before use |
| `APP_DATABASE_CONNECT_TIMEOUT_SECONDS` | int | `5` | Connect timeout |
| `APP_DATABASE_HEALTH_TIMEOUT_SECONDS` | int | `2` | Readiness ping timeout |

## Authentication (JWT)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_AUTH_ENABLED` | bool | `false` | Enable JWT auth |
| `APP_AUTH_JWT_ISSUER` | string | (required when auth enabled) | Expected issuer claim |
| `APP_AUTH_JWT_AUDIENCE` | string | (required when auth enabled) | Expected audience claim |
| `APP_AUTH_JWT_ALGORITHMS` | list | `["HS256"]` | Allowed algorithms (HS256, RS256, ES256, etc.) |
| `APP_AUTH_JWT_SECRET` | string | (min 32 chars for HS*) | Shared secret for symmetric JWT |
| `APP_AUTH_JWT_PUBLIC_KEY` | string | | PEM public key for asymmetric JWT |
| `APP_AUTH_JWKS_URL` | string | | JWKS endpoint (must use https://) |
| `APP_AUTH_REQUIRE_EXP` | bool | `true` | Require `exp` claim |
| `APP_AUTH_REQUIRE_ISSUER` | bool | `true` | Require issuer when auth enabled |
| `APP_AUTH_REQUIRE_AUDIENCE` | bool | `true` | Require audience when auth enabled |
| `APP_AUTH_JWKS_CACHE_TTL_SECONDS` | int | `300` | JWKS cache TTL (5–86400) |
| `APP_AUTH_CLOCK_SKEW_SECONDS` | int | `30` | Allowed clock skew |
| `APP_AUTH_HTTP_TIMEOUT_SECONDS` | int | `5` | HTTP timeout for JWKS |

## CORS

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_CORS_ALLOWED_ORIGINS` | list | `["http://localhost:3000", ...]` | Allowed origins |
| `APP_CORS_ALLOW_CREDENTIALS` | bool | `false` | Allow credentials |
| `APP_CORS_ALLOWED_METHODS` | list | GET, POST, PUT, PATCH, DELETE, OPTIONS | Allowed methods |
| `APP_CORS_ALLOWED_HEADERS` | list | Authorization, Content-Type, ... | Allowed headers |
| `APP_CORS_EXPOSE_HEADERS` | list | X-Request-ID, X-Correlation-ID, ... | Exposed headers |

## Middleware and Security

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_REQUEST_TIMEOUT` | int | `30` | Request timeout in seconds |
| `APP_MAX_REQUEST_BODY_BYTES` | int | `5242880` | Max body size (1KB–100MB) |
| `APP_TRUSTED_HOSTS` | list | localhost, 127.0.0.1, ... | Allowed Host headers |
| `APP_SECURITY_HEADERS_ENABLED` | bool | `true` | Enable security headers |
| `APP_SECURITY_HSTS_ENABLED` | bool | `false` | Enable HSTS over HTTPS |
| `APP_SECURITY_HSTS_MAX_AGE_SECONDS` | int | `31536000` | HSTS max-age |
| `APP_SECURITY_REFERRER_POLICY` | string | `no-referrer` | Referrer-Policy |
| `APP_SECURITY_PERMISSIONS_POLICY` | string | (see settings) | Permissions-Policy |
| `APP_SECURITY_CONTENT_SECURITY_POLICY` | string | (see settings) | CSP value |
| `APP_SECURITY_TRUST_PROXY_PROTO_HEADER` | bool | `false` | Honor X-Forwarded-Proto |
| `APP_SECURITY_TRUSTED_PROXIES` | list | `[]` | Proxy IPs/CIDRs (required when trust enabled) |

## Metrics and Tracing

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_METRICS_ENABLED` | bool | `false` | Enable Prometheus metrics |
| `APP_METRICS_PREFIX` | string | `http` | Prefix for metric names |
| `APP_OTEL_ENABLED` | bool | `false` | Enable OpenTelemetry |
| `APP_OTEL_SERVICE_NAME` | string | (from app_name) | service.name attribute |
| `APP_OTEL_SERVICE_VERSION` | string | (from app_version) | service.version attribute |
| `APP_OTEL_ENVIRONMENT` | string | `development` | deployment.environment |
| `APP_OTEL_EXPORTER_OTLP_ENDPOINT` | string | `http://localhost:4318/v1/traces` | OTLP endpoint |
| `APP_OTEL_EXPORTER_OTLP_HEADERS` | string | | Comma-separated key=value headers |

## Health and Readiness

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_HEALTH_CHECK_PATH` | string | `/healthcheck` | Liveness endpoint path |
| `APP_READINESS_CHECK_PATH` | string | `/ready` | Readiness endpoint path |
| `APP_READINESS_INCLUDE_DETAILS` | bool | `false` | Expose failure details in readiness |
| `APP_INFO_ENDPOINT_ENABLED` | bool | `false` | Expose `/info` |
| `APP_ENDPOINTS_LISTING_ENABLED` | bool | `false` | Expose `/endpoints` |

## Rate Limiting

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_RATE_LIMIT_ENABLED` | bool | `false` | Enable rate limiting |
| `APP_RATE_LIMIT_REQUESTS` | int | `100` | Max requests per window |
| `APP_RATE_LIMIT_WINDOW_SECONDS` | int | `60` | Window length |
| `APP_RATE_LIMIT_KEY_STRATEGY` | string | `ip` | Key strategy: `ip` or `authorization` |
| `APP_RATE_LIMIT_STORAGE_BACKEND` | string | `memory` | Backend: `memory` or `redis` |
| `APP_RATE_LIMIT_STORAGE_URL` | string | (derived) | Explicit Redis URL |
| `APP_REDIS_HOST` | string | `redis` | Redis host |
| `APP_REDIS_PORT` | int | `6379` | Redis port |
| `APP_REDIS_DB` | int | `0` | Redis database index |
| `APP_REDIS_PASSWORD` | string | | Optional Redis password |
| `APP_RATE_LIMIT_TRUST_PROXY_HEADERS` | bool | `false` | Honor proxy IP headers |
| `APP_RATE_LIMIT_PROXY_HEADERS` | list | X-Forwarded-For, X-Real-IP | Headers for client IP |
| `APP_RATE_LIMIT_TRUSTED_PROXIES` | list | `[]` | Proxy IPs/CIDRs (required when trust enabled) |

## Cache

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_CACHE_ENABLED` | bool | `false` | Enable the caching layer |
| `APP_CACHE_BACKEND` | string | `memory` | Backend: `memory` or `redis` |
| `APP_CACHE_DEFAULT_TTL_SECONDS` | int | `300` | Default TTL for cached entries (1–86400) |
| `APP_CACHE_MAX_ENTRIES` | int | `10000` | Maximum entries for the memory backend (1–1000000) |
| `APP_CACHE_KEY_PREFIX` | string | `cache:` | Namespace prefix for Redis keys |
| `APP_CACHE_REDIS_DB` | int | `1` | Redis database index (separate from rate limiting db 0) |
| `APP_CACHE_STORAGE_URL` | string | (derived) | Explicit Redis URL; overrides derived value |
| `APP_CACHE_HEALTH_TIMEOUT_SECONDS` | int | `2` | Readiness ping timeout (1–30) |

The cache layer reuses the shared Redis connection fields (`APP_REDIS_HOST`, `APP_REDIS_PORT`, `APP_REDIS_PASSWORD`) defined in the Rate Limiting section. When `APP_CACHE_BACKEND=redis`, the storage URL is automatically derived from these fields using `APP_CACHE_REDIS_DB` as the database index.
