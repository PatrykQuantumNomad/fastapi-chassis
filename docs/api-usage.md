# API Usage

This document provides practical examples for interacting with the
FastAPI template API endpoints.

## Base URL

By default the API listens on `http://localhost:8000`.

## Error Response Format

All error responses share a consistent JSON structure:

```json
{
  "error": "<error_type>",
  "detail": "<human_readable_detail>",
  "path": "/request/path"
}
```

| Error Type | HTTP Status | When |
| --- | --- | --- |
| `validation_error` | 422 | Request fails Pydantic validation |
| `http_error` | varies | Explicit HTTP errors (404, 403, etc.) |
| `internal_error` | 500 | Unhandled server exception |
| `rate_limited` | 429 | Request rate limit exceeded |
| `gateway_timeout` | 504 | Request exceeded timeout |
| `request_too_large` | 413 | Body exceeds `APP_MAX_REQUEST_BODY_BYTES` |

Query strings are never included in `path` values, preventing accidental
exposure of tokens or signed parameters.

## Health and Readiness

### Liveness

```bash
curl http://localhost:8000/healthcheck
```

Returns `200` with:

```json
{"status": "healthy"}
```

### Readiness

```bash
curl http://localhost:8000/ready
```

Returns `200` when all dependencies are healthy:

```json
{
  "status": "ready",
  "checks": {
    "application": {"healthy": true, "latency_ms": 0.1},
    "database": {"healthy": true, "latency_ms": 1.2},
    "auth": {"healthy": true}
  }
}
```

Returns `503` when any dependency is unhealthy. Dependency error details
are hidden by default; set `APP_READINESS_INCLUDE_DETAILS=true` only for
trusted environments.

## Root Endpoint

```bash
curl http://localhost:8000/
```

Returns application metadata:

```json
{
  "app": "FastAPI Template",
  "version": "1.0.0",
  "status": "running"
}
```

## Authenticated Endpoints

Protected endpoints require a JWT bearer token. The token must be issued
by the configured identity provider and include the expected `iss`, `aud`,
and `exp` claims.

### Local Auth Setup

To test protected endpoints locally, enable auth in your `.env`:

```bash
APP_AUTH_ENABLED=true
APP_AUTH_JWT_ISSUER=http://localhost
APP_AUTH_JWT_AUDIENCE=fastapi-template
APP_AUTH_JWT_ALGORITHMS=["HS256"]
APP_AUTH_JWT_SECRET=local-dev-secret-replace-me-in-production
```

Then restart the app.

### Generating a Test Token (HS256)

Generate a token and store it in a shell variable. The `iss`, `aud`, and
secret must match the values in your `.env`:

```bash
TOKEN=$(uv run python -c "
import jwt
token = jwt.encode(
    {'sub': 'test-user', 'iss': 'http://localhost', 'aud': 'fastapi-template',
     'exp': 9999999999, 'scope': 'reports:read', 'roles': ['admin']},
    'local-dev-secret-replace-me-in-production', algorithm='HS256')
print(token)
")
```

The token above includes all claims needed to access every example endpoint.
To test authorization failures, remove `scope` or `roles` from the payload.

### GET /api/v1/me

Returns the authenticated principal payload.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/me
```

Response:

```json
{
  "subject": "test-user",
  "issuer": "http://localhost",
  "audience": ["fastapi-template"],
  "scopes": ["reports:read"],
  "roles": ["admin"]
}
```

Without a token:

```bash
curl http://localhost:8000/api/v1/me
```

Returns `401`:

```json
{
  "error": "http_error",
  "detail": "Missing bearer token",
  "path": "/api/v1/me"
}
```

### GET /api/v1/reports

Requires the `reports:read` scope.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/reports
```

Response:

```json
{
  "status": "ok",
  "subject": "test-user",
  "report_access": true
}
```

Returns `403` if the token lacks the required scope.

### GET /api/v1/admin

Requires the `admin` role.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin
```

Response:

```json
{
  "status": "ok",
  "subject": "test-user",
  "admin": true
}
```

Returns `403` if the token lacks the required role.

## Optional Diagnostic Endpoints

These are disabled by default. Enable them only in development or
trusted internal environments.

### GET /info

Enable with `APP_INFO_ENDPOINT_ENABLED=true`.

```bash
curl http://localhost:8000/info
```

Returns:

```json
{
  "app": "FastAPI Template",
  "version": "1.0.0",
  "debug": false
}
```

### GET /endpoints

Enable with `APP_ENDPOINTS_LISTING_ENABLED=true`.

```bash
curl http://localhost:8000/endpoints
```

Returns a list of all registered routes with methods.

## Rate Limit Headers

When rate limiting is enabled, all non-exempt responses include:

| Header | Description |
| --- | --- |
| `X-RateLimit-Limit` | Maximum requests per window |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |
| `Retry-After` | Seconds until the window resets |

When the limit is exceeded:

```bash
curl http://localhost:8000/api/v1/me
```

Returns `429`:

```json
{
  "error": "rate_limited",
  "detail": "Request rate limit exceeded",
  "retry_after_seconds": 42
}
```

## Request and Correlation IDs

Every response includes tracing headers:

| Header | Description |
| --- | --- |
| `X-Request-ID` | Unique ID generated per request |
| `X-Correlation-ID` | Propagated from the incoming `X-Request-ID` or `X-Correlation-ID` header |

Pass a correlation ID for distributed tracing:

```bash
curl -H "X-Correlation-ID: my-trace-123" \
     http://localhost:8000/healthcheck
```
