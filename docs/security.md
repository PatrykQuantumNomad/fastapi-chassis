# Security

This document covers the security model, configuration, and operational
guidance for the FastAPI template.

## Authentication

The service acts as a stateless JWT resource server. It validates
externally-issued tokens and does not handle login flows, sessions, or
password management.

### Verification Modes

Configure one of three verification modes when `APP_AUTH_ENABLED=true`:

**Shared secret (HS256)** -- for local development and testing only:

```bash
APP_AUTH_ENABLED=true
APP_AUTH_JWT_ALGORITHMS=["HS256"]
APP_AUTH_JWT_SECRET=<at-least-32-characters>
APP_AUTH_JWT_ISSUER=https://your-idp.example.com/
APP_AUTH_JWT_AUDIENCE=your-app
```

**Static public key (RS256/ES256)** -- for environments with a fixed signing key:

```bash
APP_AUTH_ENABLED=true
APP_AUTH_JWT_ALGORITHMS=["RS256"]
APP_AUTH_JWT_PUBLIC_KEY=<PEM-encoded-public-key>
APP_AUTH_JWT_ISSUER=https://your-idp.example.com/
APP_AUTH_JWT_AUDIENCE=your-app
```

**JWKS endpoint (RS256/ES256)** -- recommended for production with key rotation:

```bash
APP_AUTH_ENABLED=true
APP_AUTH_JWT_ALGORITHMS=["RS256"]
APP_AUTH_JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
APP_AUTH_JWT_ISSUER=https://your-idp.example.com/
APP_AUTH_JWT_AUDIENCE=your-app
```

### Configuration Validation

The settings layer enforces these rules at startup:

- JWKS URLs must use HTTPS.
- HS256 secrets must be at least 32 characters.
- Algorithm families cannot be mixed (e.g. HS256 + RS256 is rejected).
- Shared secrets cannot be combined with public keys or JWKS.
- Issuer and audience are required by default when auth is enabled.

### JWKS Cache Behavior

When using a JWKS endpoint:

- Keys are cached for `APP_AUTH_JWKS_CACHE_TTL_SECONDS` (default 300s).
- On token `kid` miss, the service forces one cache refresh before rejecting.
- If refresh fails but a prior cache exists, the stale cache is used for
  already-known keys **up to `APP_AUTH_JWKS_MAX_STALE_SECONDS`** (default 3600s).
  After that window expires, the stale cache is discarded and requests that
  require JWKS validation will fail until the endpoint recovers. Set this to
  `0` to never accept stale keys (fail immediately on any refresh failure).
  Readiness reports the degraded state while stale keys are in use.
- Brand new keys (not in the stale cache) require a successful refresh.

### Startup Warmup

When `APP_AUTH_REQUIRE_WARMUP=true`, the application aborts startup if the
JWKS endpoint is unreachable during the initial warm-up. This prevents an
instance from accepting traffic when it cannot validate tokens. The default
(`false`) keeps the existing behavior: the app starts with degraded readiness
and retries on the next request or readiness check.

### Secret Rotation

- **Shared secret**: requires a process restart or settings reload.
- **Static public key**: requires updating the `APP_AUTH_JWT_PUBLIC_KEY` value
  and restarting.
- **JWKS**: key rotation is automatic via cache TTL and `kid`-miss refresh.
  No restart needed.

### Credential Rotation Procedures

**JWT shared secret (HS256)**:

1. Generate a new secret (at least 32 characters).
2. Update `APP_AUTH_JWT_SECRET` in the environment.
3. Restart the application. During the restart window, tokens signed
   with the old secret will be rejected.
4. Re-issue tokens from the identity provider using the new secret.

Because HS256 uses a single shared key for both signing and verification,
there is no zero-downtime rotation path. Use JWKS with asymmetric keys
for environments that require seamless rotation.

**Static public key (RS256/ES256)**:

1. Generate a new key pair.
2. Update `APP_AUTH_JWT_PUBLIC_KEY` with the new public key.
3. Restart the application.
4. Ensure the identity provider signs new tokens with the new private key.

**JWKS endpoint**:

No application restart is needed. Key rotation is automatic:

1. Publish the new key to the JWKS endpoint with a new `kid`.
2. The auth service refreshes its cache on `kid` miss or at TTL expiry
   (`APP_AUTH_JWKS_CACHE_TTL_SECONDS`).
3. Remove the old key from the JWKS endpoint after all outstanding tokens
   signed with it have expired.

**Database password**:

1. Update the password in the database server.
2. Update `APP_DATABASE_POSTGRES_PASSWORD` (or `APP_DATABASE_URL`) in
   the environment.
3. Restart the application. In-flight requests using existing pooled
   connections will complete; new connections use the updated credentials.

**Redis password**:

1. If using Redis ACLs, update the password on the Redis server.
2. Update `APP_REDIS_PASSWORD` (or `APP_RATE_LIMIT_STORAGE_URL`) in
   the environment.
3. Restart the application.

## Authorization

Protected routes use `Principal` objects containing subject, scopes, and roles
extracted from JWT claims. Two dependency factories are provided:

- `require_scopes("scope1", "scope2")` -- returns 403 if any scope is missing.
- `require_roles("admin", "editor")` -- returns 403 if any role is missing.

## Security Headers

When `APP_SECURITY_HEADERS_ENABLED=true` (default), every HTTP response
includes:

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | Configurable, default `no-referrer` |
| `Permissions-Policy` | Configurable, default `geolocation=(), camera=(), microphone=()` |
| `Cache-Control` | `no-store` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` |

### HSTS

HSTS is opt-in via `APP_SECURITY_HSTS_ENABLED=true`. The
`Strict-Transport-Security` header is only added when the request arrives
over HTTPS (either directly or via a trusted proxy's `X-Forwarded-Proto`).

To trust `X-Forwarded-Proto`:

```bash
APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true
APP_SECURITY_TRUSTED_PROXIES=["10.0.0.0/8"]
```

## Proxy Trust

Proxy-aware features (rate limiting IP extraction, HSTS via forwarded proto)
require explicit configuration. The template never trusts forwarded headers
from arbitrary callers.

### Rate Limiting Proxy Trust

```bash
APP_RATE_LIMIT_TRUST_PROXY_HEADERS=true
APP_RATE_LIMIT_TRUSTED_PROXIES=["10.0.0.0/8", "172.16.0.0/12"]
```

Only requests arriving from IPs in the trusted-proxy list will have their
`X-Forwarded-For` header parsed for the real client IP. For
`X-Forwarded-For`, the chain is evaluated right-to-left and the first
non-trusted IP is used. This avoids trusting caller-controlled leftmost
values.

### Security Headers Proxy Trust

```bash
APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true
APP_SECURITY_TRUSTED_PROXIES=["10.0.0.0/8"]
```

Only requests arriving from trusted proxies will have `X-Forwarded-Proto`
honored for HSTS decisions.

### Uvicorn-Level Proxy Trust

In addition to the application-level settings above, the container entrypoint
passes `--proxy-headers` to Uvicorn so that forwarded headers populate the ASGI
scope (`request.client`, `request.url.scheme`). Uvicorn only trusts these
headers from IPs listed in `UVICORN_FORWARDED_ALLOW_IPS` (default `127.0.0.1`).

In container networks the reverse proxy typically reaches the app from a
non-loopback IP. Set this variable to match the proxy address:

```bash
UVICORN_FORWARDED_ALLOW_IPS=10.0.0.0/8
```

Both the Uvicorn-level and application-level proxy trust must be configured for
proxy-aware features (HSTS, rate-limit IP extraction) to work end-to-end.

### Validation

Both application-level proxy trust settings require an explicit non-empty
allowlist when enabled. The settings layer rejects startup if trust is enabled
without proxies configured.

## Rate Limiting

Rate limiting is opt-in (`APP_RATE_LIMIT_ENABLED=true`) and uses a
fixed-window algorithm:

- **Memory backend**: suitable for single-process deployments.
- **Redis backend**: required for multi-worker or multi-instance deployments.

Health, readiness, metrics, and favicon paths are exempt from rate limiting.

The `authorization` key strategy normalizes Bearer tokens before hashing:
the `Bearer ` scheme prefix is stripped and whitespace is trimmed so that
casing differences (e.g. `Bearer`, `bearer`, `BEARER`) produce the same
rate-limit bucket.

Rate-limited responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset`, and `Retry-After` headers.

## Request Hardening

- **Body size limit**: `APP_MAX_REQUEST_BODY_BYTES` (default 5 MB, max 100 MB).
- **Request timeout**: `APP_REQUEST_TIMEOUT` (default 30s, max 300s).
- **Trusted hosts**: `APP_TRUSTED_HOSTS` validates `Host` headers.
- **CORS**: explicit origin allowlists via `APP_CORS_ALLOWED_ORIGINS`.
  Wildcard (`"*"`) origins cannot be combined with
  `APP_CORS_ALLOW_CREDENTIALS=true`; the settings layer rejects this at startup.

## Error Handling

The error handling layer prevents information leakage:

- Validation errors strip the `input` field from Pydantic errors to avoid
  echoing credentials or signed values back to clients.
- 500 responses return a generic message without stack traces or internal
  details.
- Error payloads include only the sanitized path (no query string).
- Query strings are redacted in request logs.

## Logging and PII

Request logs include `user_agent` and `referer` fields. These can contain
PII. When `APP_LOG_REDACT_HEADERS=true`, these values are replaced with
`[redacted]` in request logs.

Stack traces from unhandled exceptions are logged server-side via
`logger.exception()`. Ensure log aggregation systems restrict access to
these logs.

## Container Security

The Docker image follows defense-in-depth principles:

- Non-root user (`app`, UID 10001).
- Read-only root filesystem in production compose.
- All Linux capabilities dropped (`--cap-drop ALL`).
- `no-new-privileges` security option.
- tini as PID 1 for proper signal forwarding.
- Base images pinned by digest for reproducibility.

## Checklist

Before deploying to production:

- [ ] Set `APP_AUTH_ENABLED=true` with JWKS or static public key
- [ ] Set `APP_AUTH_JWT_ISSUER` and `APP_AUTH_JWT_AUDIENCE`
- [ ] Consider `APP_AUTH_REQUIRE_WARMUP=true` to fail fast on JWKS issues
- [ ] Review `APP_AUTH_JWKS_MAX_STALE_SECONDS` for your availability/security trade-off
- [ ] Set `APP_TRUSTED_HOSTS` to your public hostnames
- [ ] Set `APP_CORS_ALLOWED_ORIGINS` to your frontend origins
- [ ] Enable HSTS if behind HTTPS (`APP_SECURITY_HSTS_ENABLED=true`)
- [ ] Use Redis for rate limiting in multi-worker deployments
- [ ] Configure trusted proxies if behind a load balancer
- [ ] Disable `APP_DOCS_ENABLED`, `APP_REDOC_ENABLED`, `APP_OPENAPI_ENABLED`
- [ ] Disable `APP_INFO_ENDPOINT_ENABLED` and `APP_ENDPOINTS_LISTING_ENABLED`
- [ ] Set `APP_DEBUG=false`
- [ ] Review log aggregation access controls
