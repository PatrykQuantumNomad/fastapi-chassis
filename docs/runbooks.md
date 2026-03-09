# Operational Runbooks

Quick-reference incident response procedures for common production issues.

---

## Database Connection Pool Exhaustion

**Symptoms:** 503 readiness failures, slow responses, `TimeoutError` in logs.

**Diagnosis:**

```bash
# Check readiness endpoint for database check latency
curl -s http://localhost:8000/ready | jq .

# Check active connections (Postgres)
psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'your_db';"
```

**Resolution:**

1. Increase `APP_DATABASE_POOL_SIZE` (default: 5) and `APP_DATABASE_POOL_MAX_OVERFLOW` (default: 10)
2. Check for leaked sessions — ensure all endpoints use the `get_session` dependency
3. Review slow queries that hold connections open
4. Restart the application to reset the pool if connections are stuck

---

## Rate Limiting Behind a Reverse Proxy

**Symptoms:** All clients share a single rate-limit bucket, or rate limiting doesn't work at all.

**Diagnosis:**

```bash
# Check which IP the rate limiter sees
curl -s http://localhost:8000/api/v1/me -H "Authorization: Bearer $TOKEN" -v 2>&1 | grep x-ratelimit
```

**Resolution:**

1. Set `APP_RATE_LIMIT_TRUST_PROXY_HEADERS=true`
2. Set `APP_RATE_LIMIT_TRUSTED_PROXIES` to your proxy's CIDR (e.g., `10.0.0.0/8`)
3. Ensure your proxy sets `X-Forwarded-For` with the real client IP
4. Verify with two different source IPs that they get independent rate-limit counters

---

## Auth JWKS Cache Refresh Failures

**Symptoms:** 401 errors for valid tokens, `JWTAuthService` warnings in logs about JWKS fetch failures.

**Diagnosis:**

```bash
# Check readiness endpoint for auth check status
curl -s http://localhost:8000/ready | jq .

# Test JWKS endpoint connectivity from the container
curl -s "$APP_AUTH_JWKS_URL"
```

**Resolution:**

1. Verify the JWKS URL is reachable from the application container
2. Check DNS resolution and network policies
3. If using mTLS, ensure certificates are valid
4. The service uses stale-while-revalidate — existing tokens continue working
   for up to `APP_AUTH_JWKS_MAX_STALE_SECONDS` (default 3600s) after the last
   successful refresh. Once that window expires, the stale cache is discarded
   and all JWKS-dependent token validation fails. Set this to `0` to never
   accept stale keys (fail immediately on refresh failure)
5. If `APP_AUTH_REQUIRE_WARMUP=true`, readiness will fail immediately on JWKS
   issues and the app will not start if JWKS is unreachable at boot
6. Fix connectivity, then restart the service to force a fresh JWKS fetch on warm-up

---

## Graceful Shutdown Timeout

**Symptoms:** Kubernetes pods killed with SIGKILL, in-flight requests dropped during deploys.

**Diagnosis:**

```bash
# Check for SIGKILL in container logs
kubectl logs <pod> --previous | grep -i "signal\|killed\|timeout"
```

**Resolution:**

1. Ensure `APP_REQUEST_TIMEOUT` < Kubernetes `terminationGracePeriodSeconds` (default: 30s)
2. Set `terminationGracePeriodSeconds` to at least `APP_REQUEST_TIMEOUT + 5`
3. Configure Uvicorn `--timeout-graceful-shutdown` via `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN`
4. Use a `preStop` hook with a short sleep (2-3s) to allow load balancer deregistration

---

## Request Timeouts (504)

**Symptoms:** Clients receive 504 Gateway Timeout responses.

**Diagnosis:**

```bash
# Check logs for timeout warnings
grep "timed out" /var/log/app/*.log

# Look for the path and duration
grep "gateway_timeout" /var/log/app/*.log
```

**Resolution:**

1. Identify the slow endpoint from the log path
2. Check database query performance for that endpoint
3. Check external API latency if the endpoint makes outbound calls
4. Increase `APP_REQUEST_TIMEOUT` if the endpoint legitimately needs more time
5. Ensure `APP_REQUEST_TIMEOUT` < ingress controller timeout to get a meaningful error

---

## High Memory Usage

**Symptoms:** OOM kills, increasing memory over time.

**Diagnosis:**

```bash
# Check Prometheus metrics
curl -s http://localhost:8000/metrics | grep process_resident_memory_bytes

# Check container memory limits
kubectl top pod <pod>
```

**Resolution:**

1. Check `APP_MAX_REQUEST_BODY_BYTES` — large uploads consume memory
2. Review rate-limit memory store size if not using Redis (`APP_RATE_LIMIT_STORAGE_BACKEND=redis`)
3. Check for database session leaks (sessions hold query results in memory)
4. Consider switching from in-memory to Redis rate limiting for multi-worker deployments
