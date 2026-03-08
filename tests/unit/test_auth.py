"""Unit tests for stateless JWT authentication and authorization."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.auth.dependencies import (
    get_current_principal,
    get_optional_principal,
    require_roles,
    require_scopes,
)
from app.auth.models import Principal
from app.auth.service import (
    AuthenticationError,
    JWTAuthService,
    _claim_as_optional_str,
    _normalize_audience,
    _normalize_roles,
    _normalize_scopes,
    build_test_jwt,
)
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


class TestJWTAuthService:
    """Tests for the JWT auth service."""

    @pytest.mark.asyncio
    async def test_authenticates_valid_hs256_token(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = build_test_jwt(
            subject="user-1",
            secret="super-secret-test-key-for-hs256-123",
            audience="fastapi-template",
            issuer="https://issuer.example.com/",
            scopes=["reports:read"],
            roles=["admin"],
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(token)

        assert principal.subject == "user-1"
        assert principal.scopes == ["reports:read"]
        assert principal.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_authenticate_token_rejects_when_auth_disabled(self) -> None:
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(make_settings(auth_enabled=False), client)
            with pytest.raises(AuthenticationError, match="disabled"):
                await service.authenticate_token("token")

    @pytest.mark.asyncio
    async def test_invalid_token_is_reported_as_invalid_jwt(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="Token validation failed"):
                await service.authenticate_token("not-a-jwt")

    @pytest.mark.asyncio
    async def test_readiness_reports_auth_disabled(self) -> None:
        settings = make_settings(auth_enabled=False)
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            result = await service.readiness_check(FastAPI())

        assert result.is_healthy is True
        assert result.detail == "Authentication disabled"

    @pytest.mark.asyncio
    async def test_missing_exp_claim_is_rejected(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = jwt.encode(
            {"sub": "user-1", "aud": "fastapi-template", "iss": "https://issuer.example.com/"},
            settings.auth_jwt_secret,
            algorithm="HS256",
        )

        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="Token validation failed"):
                await service.authenticate_token(token)

    @pytest.mark.asyncio
    async def test_accepts_token_without_exp_when_not_required(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
            auth_require_exp=False,
        )
        token = jwt.encode(
            {"sub": "user-1", "aud": "fastapi-template", "iss": "https://issuer.example.com/"},
            settings.auth_jwt_secret,
            algorithm="HS256",
        )

        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(token)

        assert principal.subject == "user-1"

    @pytest.mark.asyncio
    async def test_authenticates_token_with_scp_claim(self) -> None:
        secret = "super-secret-test-key-for-hs256-123"
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret=secret,
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = build_test_jwt(
            subject="user-1",
            secret=secret,
            audience="fastapi-template",
            issuer="https://issuer.example.com/",
        )
        raw = jwt.decode(token, secret, algorithms=["HS256"], audience="fastapi-template")
        raw["scp"] = "reports:read admin:write"
        raw.pop("scope", None)
        scp_token = jwt.encode(raw, secret, algorithm="HS256")

        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(scp_token)

        assert principal.scopes == ["reports:read", "admin:write"]

    @pytest.mark.asyncio
    async def test_readiness_reports_shared_secret_mode(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            result = await service.readiness_check(FastAPI())

        assert result.is_healthy is True
        assert "Shared-secret" in result.detail

    @pytest.mark.asyncio
    async def test_readiness_reports_public_key_mode(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_public_key=(
                "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqh\n-----END PUBLIC KEY-----"
            ),
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            result = await service.readiness_check(FastAPI())

        assert result.is_healthy is True
        assert "Static public key" in result.detail

    @pytest.mark.asyncio
    async def test_readiness_reports_jwks_failure(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code=503))
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            result = await service.readiness_check(FastAPI())

        assert result.is_healthy is False
        assert "JWKS unavailable" in result.detail

    @pytest.mark.asyncio
    async def test_readiness_reports_jwks_available(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"keys": [{"kid": "abc123", "kty": "RSA"}]})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            result = await service.readiness_check(FastAPI())

        assert result.is_healthy is True
        assert result.detail == "JWKS available"

    @pytest.mark.asyncio
    async def test_warm_up_fetches_jwks_and_populates_cache(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"keys": [{"kid": "abc123", "kty": "RSA"}]})

        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = JWTAuthService(settings, client)
            await service.warm_up()
            await service.warm_up()

        assert calls == 2

    @pytest.mark.asyncio
    async def test_resolve_key_requires_kid_for_jwks(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = jwt.encode(
            {"sub": "user-1", "exp": 9999999999},
            "super-secret-test-key-for-hs256-123",
            algorithm="HS256",
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="missing kid"):
                await service._resolve_key(token)

    @pytest.mark.asyncio
    async def test_resolve_key_fails_when_jwks_has_no_matching_key(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = jwt.encode(
            {"sub": "user-1", "exp": 9999999999},
            "super-secret-test-key-for-hs256-123",
            algorithm="HS256",
            headers={"kid": "abc123"},
        )
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": []}))
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="does not contain any signing keys"):
                await service._resolve_key(token)

    @pytest.mark.asyncio
    async def test_resolve_key_refreshes_jwks_once_on_kid_miss(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = jwt.encode(
            {"sub": "user-1", "exp": 9999999999},
            "super-secret-test-key-for-hs256-123",
            algorithm="HS256",
            headers={"kid": "rotated-key"},
        )
        responses = iter(
            [
                {"keys": [{"kid": "old-key", "kty": "RSA"}]},
                {"keys": [{"kid": "rotated-key", "kty": "RSA"}]},
            ]
        )
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=next(responses)))
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            with patch("app.auth.service.PyJWK.from_dict") as from_dict:
                from_dict.return_value = Mock(key="resolved-key")
                resolved_key = await service._resolve_key(token)

        assert resolved_key == "resolved-key"
        assert from_dict.call_count == 1

    @pytest.mark.asyncio
    async def test_resolve_key_fails_with_generic_message_when_no_key_matches_kid(self) -> None:
        """JWKS has keys but none match token kid; error message is generic (no kid leak)."""
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = jwt.encode(
            {"sub": "user-1", "exp": 9999999999},
            "super-secret-test-key-for-hs256-123",
            algorithm="HS256",
            headers={"kid": "unknown-kid"},
        )
        jwks_with_other_key = {"keys": [{"kid": "other-key", "kty": "RSA"}]}
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=jwks_with_other_key)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="No matching signing key found"):
                await service._resolve_key(token)

    @pytest.mark.asyncio
    async def test_resolve_key_prefers_static_public_key(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_public_key="public-key",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            assert await service._resolve_key("token") == "public-key"

    @pytest.mark.asyncio
    async def test_resolve_key_uses_shared_secret_when_configured(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            assert await service._resolve_key("token") == settings.auth_jwt_secret

    @pytest.mark.asyncio
    async def test_resolve_key_errors_when_no_verification_material_exists(self) -> None:
        settings = make_settings(
            auth_enabled=False,
            auth_jwt_algorithms=["RS256"],
            auth_require_audience=False,
            auth_require_issuer=False,
        )
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="no key material"):
                await service._resolve_key("token")

    @pytest.mark.asyncio
    async def test_fetch_jwks_uses_cache_until_ttl_expires(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"keys": [{"kid": "abc123", "kty": "RSA"}]})

        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
            auth_jwks_cache_ttl_seconds=3600,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = JWTAuthService(settings, client)
            await service._fetch_jwks(force_refresh=False)
            await service._fetch_jwks(force_refresh=False)

        assert calls == 1

    @pytest.mark.asyncio
    async def test_fetch_jwks_uses_stale_cache_when_refresh_fails(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
            auth_jwks_cache_ttl_seconds=5,
        )
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code=503))
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            service._jwks_cache = {"keys": [{"kid": "cached-key", "kty": "RSA"}]}
            service._jwks_loaded_at = 0

            jwks = await service._fetch_jwks(force_refresh=False)

        assert jwks == {"keys": [{"kid": "cached-key", "kty": "RSA"}]}
        assert service._jwks_last_fetch_used_stale_cache is True

    @pytest.mark.asyncio
    async def test_readiness_reports_stale_cache_when_refresh_fails(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
            auth_jwks_cache_ttl_seconds=5,
        )
        transport = httpx.MockTransport(lambda request: httpx.Response(status_code=503))
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            service._jwks_cache = {"keys": [{"kid": "cached-key", "kty": "RSA"}]}
            service._jwks_loaded_at = 0

            result = await service.readiness_check(FastAPI())

        assert result.is_healthy is True
        assert "stale JWKS cache" in result.detail

    def test_jwks_cache_expired_reports_true_after_elapsed_time(self) -> None:
        settings = make_settings(auth_jwks_cache_ttl_seconds=5)
        service = JWTAuthService(settings, Mock(spec=httpx.AsyncClient))
        service._jwks_loaded_at = 0
        assert service._jwks_cache_expired() is True

    def test_auth_enabled_requires_explicit_key_material(self) -> None:
        with pytest.raises(ValidationError, match="auth_jwt_secret"):
            make_settings(auth_enabled=True)

    def test_auth_enabled_rejects_insecure_jwks_url(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWKS_URL"):
            make_settings(
                auth_enabled=True,
                auth_jwks_url="http://issuer.example.com/.well-known/jwks.json",
                auth_jwt_algorithms=["RS256"],
                auth_jwt_audience="fastapi-template",
                auth_jwt_issuer="https://issuer.example.com/",
            )

    def test_auth_enabled_rejects_mixed_algorithm_families(self) -> None:
        with pytest.raises(ValidationError, match="same algorithm family"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["HS256", "RS256"],
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_audience="fastapi-template",
                auth_jwt_issuer="https://issuer.example.com/",
            )

    def test_auth_enabled_rejects_shared_secret_with_asymmetric_algorithms(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWT_SECRET"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["RS256"],
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_public_key="public-key",
                auth_jwt_audience="fastapi-template",
                auth_jwt_issuer="https://issuer.example.com/",
            )

    def test_auth_enabled_requires_issuer_by_default(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWT_ISSUER"):
            make_settings(
                auth_enabled=True,
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_audience="fastapi-template",
            )

    def test_auth_enabled_requires_audience_by_default(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWT_AUDIENCE"):
            make_settings(
                auth_enabled=True,
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_issuer="https://issuer.example.com/",
            )

    def test_auth_issuer_not_required_when_explicitly_disabled(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_require_issuer=False,
        )
        assert settings.auth_jwt_issuer == ""

    def test_auth_audience_not_required_when_explicitly_disabled(self) -> None:
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_issuer="https://issuer.example.com/",
            auth_require_audience=False,
        )
        assert settings.auth_jwt_audience == ""


class TestAuthorizationDependencies:
    """Tests for authorization dependency factories."""

    def test_require_scopes_allows_present_scope(self) -> None:
        dependency = require_scopes("reports:read")
        principal = dependency(
            Principal(
                subject="user-1",
                audience=[],
                scopes=["reports:read"],
                roles=[],
                claims={},
            )
        )
        assert principal.scopes == ["reports:read"]

    def test_require_roles_allows_present_role(self) -> None:
        dependency = require_roles("admin")
        principal = dependency(
            Principal(
                subject="user-1",
                audience=[],
                scopes=[],
                roles=["admin"],
                claims={},
            )
        )
        assert principal.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_get_optional_principal_returns_none_without_credentials(self) -> None:
        request = Mock()
        request.app.state.auth_service = Mock()

        assert await get_optional_principal(request, credentials=None) is None

    @pytest.mark.asyncio
    async def test_get_optional_principal_converts_authentication_error_to_http_401(self) -> None:
        request = Mock()
        auth_service = Mock()
        auth_service.authenticate_token = AsyncMock(side_effect=AuthenticationError("bad token"))
        request.app.state.auth_service = auth_service
        credentials = Mock()
        credentials.credentials = "token"

        with pytest.raises(HTTPException, match="Invalid bearer token") as exc_info:
            await get_optional_principal(request, credentials=credentials)

        assert exc_info.value.status_code == 401

    def test_get_current_principal_requires_authenticated_principal(self) -> None:
        with pytest.raises(HTTPException, match="Missing bearer token") as exc_info:
            get_current_principal(None)

        assert exc_info.value.status_code == 401

    def test_require_scopes_rejects_missing_scope(self) -> None:
        dependency = require_scopes("reports:read")
        with pytest.raises(HTTPException, match="Missing required scopes") as exc_info:
            dependency(
                Principal(
                    subject="user-1",
                    audience=[],
                    scopes=["profile:read"],
                    roles=[],
                    claims={},
                )
            )

        assert exc_info.value.status_code == 403

    def test_require_roles_rejects_missing_role(self) -> None:
        dependency = require_roles("admin")
        with pytest.raises(HTTPException, match="Missing required roles") as exc_info:
            dependency(
                Principal(
                    subject="user-1",
                    audience=[],
                    scopes=[],
                    roles=["user"],
                    claims={},
                )
            )

        assert exc_info.value.status_code == 403


class TestAuthHelpers:
    """Tests for helper normalization functions used by auth service."""

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (None, []),
            (["a", 2], ["a", "2"]),
            ("aud", ["aud"]),
        ],
    )
    def test_normalize_audience(self, input_val: object, expected: list[str]) -> None:
        assert _normalize_audience(input_val) == expected

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (None, []),
            ("read write", ["read", "write"]),
            (["read", 2], ["read", "2"]),
            (7, ["7"]),
        ],
    )
    def test_normalize_scopes(self, input_val: object, expected: list[str]) -> None:
        assert _normalize_scopes(input_val) == expected

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (None, []),
            ("admin,user", ["admin", "user"]),
            ('["admin","user"]', ["admin", "user"]),
            ("[invalid", ["[invalid"]),
            (["admin", 1], ["admin", "1"]),
            (7, ["7"]),
        ],
    )
    def test_normalize_roles(self, input_val: object, expected: list[str]) -> None:
        assert _normalize_roles(input_val) == expected

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (None, None),
            (123, "123"),
        ],
    )
    def test_claim_as_optional_str(self, input_val: object, expected: str | None) -> None:
        assert _claim_as_optional_str(input_val) == expected
