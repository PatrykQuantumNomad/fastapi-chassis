"""
Security-focused response headers middleware.
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..utils import is_trusted_proxy, normalize_forwarded_proto, parse_trusted_proxies


class SecurityHeadersMiddleware:
    """Attach conservative security headers to all HTTP responses."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        hsts_enabled: bool,
        hsts_max_age_seconds: int,
        referrer_policy: str,
        permissions_policy: str,
        content_security_policy: str,
        trust_proxy_proto_header: bool,
        trusted_proxies: list[str],
    ) -> None:
        self.app = app
        self.hsts_enabled = hsts_enabled
        self.hsts_max_age_seconds = hsts_max_age_seconds
        self.referrer_policy = referrer_policy
        self.permissions_policy = permissions_policy
        self.content_security_policy = content_security_policy
        self.trust_proxy_proto_header = trust_proxy_proto_header
        self.trusted_proxies = parse_trusted_proxies(trusted_proxies)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = self.referrer_policy
                headers["Permissions-Policy"] = self.permissions_policy
                headers["Cache-Control"] = "no-store"
                if self.content_security_policy:
                    headers["Content-Security-Policy"] = self.content_security_policy

                request_headers = Headers(raw=scope.get("headers", []))
                client = scope.get("client")
                client_host = client[0] if client else "unknown"
                forwarded_proto = None
                if self.trust_proxy_proto_header and is_trusted_proxy(
                    client_host, self.trusted_proxies
                ):
                    forwarded_proto = normalize_forwarded_proto(
                        request_headers.get("x-forwarded-proto")
                    )
                scheme = forwarded_proto or scope.get("scheme", "http")
                if self.hsts_enabled and scheme == "https":
                    headers["Strict-Transport-Security"] = (
                        f"max-age={self.hsts_max_age_seconds}; includeSubDomains"
                    )

            await send(message)

        await self.app(scope, receive, send_wrapper)
