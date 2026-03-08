# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-07

### Added

- FastAPI application factory with Builder pattern configuration.
- Pydantic settings with `APP_*` environment variable overrides.
- SQLite-first async SQLAlchemy database with Alembic migrations.
- Postgres support via `APP_DATABASE_BACKEND=postgres`.
- Pluggable cache store with memory and Redis backends, TTL support, and max-entry eviction.
- Stateless JWT authentication with HS256, RS256, ES256, and JWKS support.
- JWKS cache with TTL, stale fallback, and `kid`-miss refresh.
- Authorization dependencies for scopes and roles.
- Security response headers (X-Content-Type-Options, X-Frame-Options,
  Referrer-Policy, Permissions-Policy, Cache-Control, Content-Security-Policy).
- Conditional HSTS with proxy-aware `X-Forwarded-Proto` trust.
- Fixed-window rate limiting with memory and Redis backends.
- Proxy-aware IP extraction with right-to-left `X-Forwarded-For` parsing.
- Request ID and correlation ID middleware with OpenTelemetry span attributes.
- Structured request logging with query string redaction.
- Structured error handlers with consistent JSON error responses.
- Body size limit middleware.
- Request timeout middleware.
- Trusted host validation.
- CORS with configurable origins, methods, and headers.
- Dependency-aware readiness checks (database, authentication).
- Application lifespan management for startup and shutdown resource handling.
- Optional Prometheus metrics via starlette-exporter.
- Optional OpenTelemetry tracing with OTLP HTTP export.
- Multi-stage Docker image with non-root user, tini, and digest-pinned bases.
- Production Docker Compose with read-only FS, dropped capabilities, and
  resource limits.
- CI pipeline with linting, type checking, testing, coverage, Docker build,
  smoke test, and production-like stack verification.
- Deploy workflows for image and compose based deployments with rollback.
- Pre-commit hooks for ruff, mypy, and unit tests.
- Comprehensive test suite with unit and integration coverage.
- Documentation: architecture, operations, security, testing stack, monitoring, API usage, runbooks.
- Architecture Decision Records (ADRs) for builder pattern, factory function, raw ASGI
  middleware, proxy hop extraction, and readiness/liveness separation.
- `docs/configuration.md` with complete reference for all `APP_*` environment variables.
- Dependabot configuration for automated dependency updates (pip, GitHub Actions, Docker).
- `pip-audit` dependency vulnerability scanning in CI pipeline.
- Bandit Python SAST (security-oriented static analysis) in CI pipeline.
- Trivy container image scanning in the Docker image release workflow.
- Prometheus metrics and alert rules documentation in `docs/operations.md`.
- Complete Makefile target reference in `CONTRIBUTING.md`.
- Integration test fixtures for Postgres and Redis backends (CI-only via service containers).
- Tests for `auth_require_exp=False`, `scp` claim, and optional issuer/audience validation.
