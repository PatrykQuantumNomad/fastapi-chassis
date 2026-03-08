"""
Helpers for safely trusting reverse-proxy headers.
"""

from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from starlette.datastructures import Headers

type TrustedProxyNetwork = IPv4Network | IPv6Network


def parse_trusted_proxies(proxies: list[str]) -> tuple[TrustedProxyNetwork, ...]:
    """Parse configured proxy IPs/CIDRs into network objects."""
    return tuple(ip_network(proxy, strict=False) for proxy in proxies)


def is_trusted_proxy(client_host: str, trusted_proxies: tuple[TrustedProxyNetwork, ...]) -> bool:
    """Return whether the immediate peer is an explicitly trusted proxy."""
    try:
        client_ip = ip_address(client_host)
    except ValueError:
        return False

    return any(client_ip in network for network in trusted_proxies)


def normalize_ip(value: str) -> str | None:
    """Return a normalized IP string or None for invalid values."""
    try:
        return str(ip_address(value.strip()))
    except ValueError:
        return None


def get_forwarded_client_ip(
    headers: Headers,
    proxy_headers: list[str],
    trusted_proxies: tuple[TrustedProxyNetwork, ...],
) -> str | None:
    """
    Resolve the original client IP from trusted forwarded headers.

    For `X-Forwarded-For`, evaluate the chain from right to left and return the
    first address that is not one of the configured trusted proxies. This
    matches append-style proxy chains and avoids trusting caller-controlled
    leftmost values blindly.
    """

    for header_name in proxy_headers:
        header_value = headers.get(header_name)
        if not header_value:
            continue

        if header_name == "x-forwarded-for":
            candidates = [
                normalized
                for normalized in (normalize_ip(value) for value in header_value.split(","))
                if normalized is not None
            ]
            for candidate in reversed(candidates):
                if not is_trusted_proxy(candidate, trusted_proxies):
                    return candidate
            continue

        normalized = normalize_ip(header_value)
        if normalized and not is_trusted_proxy(normalized, trusted_proxies):
            return normalized

    return None


def normalize_forwarded_proto(value: str | None) -> str | None:
    """Return a normalized forwarded scheme if it is safe to trust."""
    if value is None:
        return None

    normalized = value.split(",", 1)[0].strip().lower()
    if normalized in {"http", "https"}:
        return normalized
    return None
