# ADR 0004: Rightmost Untrusted Proxy Hop for Client IP

**Status**: Accepted
**Date**: 2026-01-15

## Context

When an application sits behind reverse proxies (load balancers, CDNs, API gateways), the direct TCP peer address is the proxy, not the end client. The real client IP is typically passed in `X-Forwarded-For` (XFF), which contains a comma-separated list of IPs representing each hop:

```bash
X-Forwarded-For: <client>, <proxy1>, <proxy2>
```

There are two common strategies for extracting the client IP:

1. **Leftmost entry**: Take `XFF[0]`. This is the "original client" but is trivially spoofable — any caller can prepend arbitrary IPs to the header.
2. **Rightmost untrusted hop**: Walk the XFF list from right to left, skipping entries that belong to known trusted proxy networks. The first entry that does not match a trusted proxy is the real client IP.

The leftmost strategy is used by many frameworks by default (including early FastAPI/Starlette middleware) but is a security vulnerability for rate limiting and audit logging. An attacker can bypass rate limits by sending `X-Forwarded-For: 1.2.3.4` with a different spoofed IP on each request.

## Decision

Use the rightmost untrusted hop strategy for all features that depend on client IP:

- **Rate limiting** (`RateLimitMiddleware`): Client IP is the rate limit key
- **Security headers** (`SecurityHeadersMiddleware`): HSTS and protocol detection via `X-Forwarded-Proto`

Both middleware accept:

- A `trust_proxy_headers` / `trust_proxy_proto_header` flag to opt in
- A `trusted_proxies` list of IP addresses and CIDR ranges

The extraction logic in `src/app/utils.py` (`get_forwarded_client_ip`) walks XFF right-to-left and returns the first IP not in the trusted set. If all entries are trusted (misconfiguration), it falls back to the direct TCP peer address.

Proxy header trust is disabled by default. Operators must explicitly enable it and provide their infrastructure's proxy IP ranges.

## Consequences

**Benefits:**

- Resistant to client-side XFF spoofing — attackers cannot bypass rate limits by forging headers
- Explicit opt-in prevents accidental trust of unverified headers in deployments without proxies
- The trusted proxy list makes the security boundary visible and auditable
- Consistent behavior across rate limiting and security header handling

**Trade-offs:**

- Operators must know and configure their proxy infrastructure IPs/CIDRs
- Misconfigured trusted proxy lists can cause all traffic to appear from the same IP (the outermost proxy) or from spoofed IPs
- More complex than the naive leftmost approach — requires documentation and testing
