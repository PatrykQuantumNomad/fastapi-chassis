# ADR 0005: Readiness vs Liveness Separation

**Status**: Accepted
**Date**: 2026-01-15

## Context

Container orchestrators (Kubernetes, ECS, Docker Swarm) use health probes to manage service lifecycle. Two probe types serve fundamentally different purposes:

- **Liveness**: "Is the process alive?" A failure triggers a container restart.
- **Readiness**: "Can the process accept traffic?" A failure removes the instance from the load balancer but does not restart it.

Conflating these into a single endpoint causes operational problems:

1. If the combined check includes a database probe and the database is temporarily unreachable, the orchestrator restarts the container — which cannot fix a database outage and may cause cascading restarts across the fleet.
2. If the combined check is lightweight (always returns healthy), the orchestrator routes traffic to instances that have not finished initializing or have lost a backend dependency.

## Decision

Provide two separate endpoints with distinct semantics:

- **`/healthcheck`** (configurable via `APP_HEALTH_CHECK_PATH`): Liveness probe. Returns `{"status": "healthy"}` immediately with no dependency checks. If this fails, the process itself is broken.

- **`/ready`** (configurable via `APP_READINESS_CHECK_PATH`): Readiness probe. Runs all checks in the `ReadinessRegistry` and returns 200 (ready) or 503 (not ready) based on aggregate health.

The `ReadinessRegistry` supports:

- Named dependency checks (application, database, auth)
- Both sync and async check functions
- Automatic latency measurement per check
- Optional detail hiding (`APP_READINESS_INCLUDE_DETAILS=false`) for production environments where internal dependency names and error messages should not be exposed

Checks are registered during app construction via the builder:

- `application`: always healthy (confirms the registry itself works)
- `database`: verifies the async engine can execute a query
- `auth`: verifies the JWT service has valid key material (JWKS refresh status)

## Consequences

**Benefits:**

- Database outages cause traffic draining (readiness failure) instead of cascading restarts (liveness failure)
- New dependencies get readiness coverage by registering a check — no changes to the endpoint handler
- Latency measurement per check makes it easy to identify slow dependencies
- Detail hiding prevents information leakage in production while keeping diagnostics available in staging
- The registry pattern is dependency-aware — checks run in registration order and results are aggregated

**Trade-offs:**

- Operators must configure both probe paths in their orchestrator (not just one)
- Adding a new backend dependency requires registering a readiness check — forgetting this means silent degradation
- The `/ready` endpoint adds latency proportional to the number and speed of registered checks
