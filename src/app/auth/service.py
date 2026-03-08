"""
Stateless JWT validation service.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import httpx
import jwt
from fastapi import FastAPI
from jwt import InvalidTokenError, PyJWK

from ..readiness import ReadinessCheckResult
from ..settings import Settings
from .models import Principal

logger = logging.getLogger(__name__)


class AuthenticationError(RuntimeError):
    """Raised when a token cannot be authenticated."""


class AuthorizationError(RuntimeError):
    """Raised when an authenticated principal lacks required privileges."""


class JWTAuthService:
    """Validate externally-issued JWTs against local config or JWKS."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http_client = http_client
        self._jwks_lock = asyncio.Lock()
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0
        self._jwks_last_fetch_used_stale_cache = False

    async def authenticate_token(self, token: str) -> Principal:
        """Validate a JWT and map the claims to a principal object."""
        if not self.settings.auth_enabled:
            raise AuthenticationError("Authentication is disabled")

        required_claims = ["sub"]
        if self.settings.auth_require_exp:
            required_claims.append("exp")

        try:
            key = await self._resolve_key(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=self.settings.auth_jwt_algorithms,
                audience=self.settings.auth_jwt_audience or None,
                issuer=self.settings.auth_jwt_issuer or None,
                leeway=self.settings.auth_clock_skew_seconds,
                options={
                    "require": required_claims,
                    "verify_aud": bool(self.settings.auth_jwt_audience),
                    "verify_iss": bool(self.settings.auth_jwt_issuer),
                },
            )
        except InvalidTokenError as exc:
            logger.debug("JWT validation failed: %s", exc)
            raise AuthenticationError("Token validation failed") from exc
        except Exception as exc:
            logger.debug("JWT authentication error: %s", exc)
            raise AuthenticationError("Token authentication failed") from exc

        return Principal(
            subject=str(claims["sub"]),
            issuer=_claim_as_optional_str(claims.get("iss")),
            audience=_normalize_audience(claims.get("aud")),
            scopes=_normalize_scopes(claims.get("scope") or claims.get("scp")),
            roles=_normalize_roles(claims.get("roles")),
            claims=claims,
        )

    async def readiness_check(self, app: FastAPI) -> ReadinessCheckResult:
        """Report whether JWT validation dependencies are ready."""
        _ = app
        if not self.settings.auth_enabled:
            return ReadinessCheckResult.ok("auth", detail="Authentication disabled")

        if self.settings.auth_jwks_url:
            try:
                await self._fetch_jwks(force_refresh=False)
            except Exception as exc:
                return ReadinessCheckResult.error("auth", f"JWKS unavailable: {exc!s}")
            detail = (
                "Using stale JWKS cache after refresh failure"
                if self._jwks_last_fetch_used_stale_cache
                else "JWKS available"
            )
            return ReadinessCheckResult.ok("auth", detail=detail)

        if self.settings.auth_jwt_public_key:
            return ReadinessCheckResult.ok("auth", detail="Static public key configured")

        if self._uses_shared_secret():
            return ReadinessCheckResult.ok(
                "auth",
                detail="Shared-secret JWT validation configured",
            )

        return ReadinessCheckResult.error("auth", "No JWT verification material configured")

    async def warm_up(self) -> None:
        """Prime caches used for JWT verification when auth is enabled."""
        if self.settings.auth_enabled and self.settings.auth_jwks_url:
            await self._fetch_jwks(force_refresh=True)

    async def _resolve_key(self, token: str) -> Any:
        if self.settings.auth_jwks_url:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if not kid:
                raise AuthenticationError("JWT is missing kid header required for JWKS")

            jwks = await self._fetch_jwks(force_refresh=False)
            key = _get_jwk_key_for_kid(jwks, kid)
            if key is not None:
                return key

            # Force one refresh on kid misses so key rotation does not require
            # a process restart or cache TTL expiry before new tokens work.
            refreshed_jwks = await self._fetch_jwks(force_refresh=True)
            refreshed_key = _get_jwk_key_for_kid(refreshed_jwks, kid)
            if refreshed_key is not None:
                return refreshed_key
            raise AuthenticationError("No matching signing key found")

        if self.settings.auth_jwt_public_key:
            return self.settings.auth_jwt_public_key

        if self._uses_shared_secret():
            return self.settings.auth_jwt_secret

        raise AuthenticationError("JWT validation is enabled but no key material is configured")

    async def _fetch_jwks(self, force_refresh: bool) -> dict[str, Any]:
        if not force_refresh and self._jwks_cache and not self._jwks_cache_expired():
            self._jwks_last_fetch_used_stale_cache = False
            return self._jwks_cache

        async with self._jwks_lock:
            if not force_refresh and self._jwks_cache and not self._jwks_cache_expired():
                self._jwks_last_fetch_used_stale_cache = False
                return self._jwks_cache

            try:
                response = await self.http_client.get(self.settings.auth_jwks_url)
                response.raise_for_status()
                self._jwks_cache = _validate_jwks_payload(response.json())
                self._jwks_loaded_at = monotonic()
                self._jwks_last_fetch_used_stale_cache = False
                return self._jwks_cache
            except Exception:
                if self._jwks_cache is not None:
                    self._jwks_last_fetch_used_stale_cache = True
                    return self._jwks_cache
                raise

    def _jwks_cache_expired(self) -> bool:
        return monotonic() - self._jwks_loaded_at >= self.settings.auth_jwks_cache_ttl_seconds

    def _uses_shared_secret(self) -> bool:
        return any(algorithm.startswith("HS") for algorithm in self.settings.auth_jwt_algorithms)


def _normalize_audience(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _normalize_scopes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [scope for scope in value.split() if scope]
    if isinstance(value, list):
        return [str(scope) for scope in value]
    return [str(value)]


def _normalize_roles(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if value.startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return [value]
            if isinstance(decoded, list):
                return [str(role) for role in decoded]
        return [role for role in value.replace(",", " ").split() if role]
    if isinstance(value, list):
        return [str(role) for role in value]
    return [str(value)]


def _claim_as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_jwks_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = payload.get("keys")
    if not isinstance(keys, list) or not keys:
        raise AuthenticationError("JWKS payload does not contain any signing keys")
    return payload


def _get_jwk_key_for_kid(jwks: dict[str, Any], kid: str) -> Any | None:
    for jwk_data in jwks.get("keys", []):
        if jwk_data.get("kid") == kid:
            return PyJWK.from_dict(jwk_data).key
    return None


def build_test_jwt(
    *,
    subject: str,
    secret: str,
    audience: str | None = None,
    issuer: str | None = None,
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
    expires_in_seconds: int = 300,
) -> str:
    """Utility used by tests to mint HS256 tokens."""
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": datetime.now(tz=UTC) + timedelta(seconds=expires_in_seconds),
    }
    if audience:
        payload["aud"] = audience
    if issuer:
        payload["iss"] = issuer
    if scopes:
        payload["scope"] = " ".join(scopes)
    if roles:
        payload["roles"] = roles
    return jwt.encode(payload, secret, algorithm="HS256")
