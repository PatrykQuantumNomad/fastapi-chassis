"""Unit tests for asymmetric JWT authentication (RSA and EC key modes)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.auth.service import AuthenticationError, JWTAuthService, _get_jwk_key_for_kid
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


def _rsa_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """Generate a fresh RSA key pair. Returns (private_key, pem_public_key)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    return private_key, public_pem.decode("utf-8")


def _ec_key_pair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """Generate a fresh EC P-256 key pair. Returns (private_key, pem_public_key)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    return private_key, public_pem.decode("utf-8")


def _build_jwt(
    private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
    algorithm: str,
    kid: str | None = None,
    subject: str = "user-1",
    audience: str = "fastapi-template",
    issuer: str = "https://issuer.example.com/",
) -> str:
    payload = {
        "sub": subject,
        "aud": audience,
        "iss": issuer,
        "exp": datetime.now(tz=UTC) + timedelta(minutes=5),
    }
    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, private_key, algorithm=algorithm, headers=headers)


class TestRS256Authentication:
    """Tests for RSA-based JWT validation via static public key."""

    @pytest.mark.asyncio
    async def test_validates_rs256_token_with_static_public_key(self) -> None:
        private_key, public_pem = _rsa_key_pair()
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["RS256"],
            auth_jwt_public_key=public_pem,
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = _build_jwt(private_key, "RS256")
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(token)

        assert principal.subject == "user-1"
        assert principal.issuer == "https://issuer.example.com/"

    @pytest.mark.asyncio
    async def test_rejects_rs256_token_signed_with_wrong_key(self) -> None:
        _, public_pem = _rsa_key_pair()
        other_private_key, _ = _rsa_key_pair()
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["RS256"],
            auth_jwt_public_key=public_pem,
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = _build_jwt(other_private_key, "RS256")
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="Token validation failed"):
                await service.authenticate_token(token)


class TestES256Authentication:
    """Tests for EC-based JWT validation via static public key."""

    @pytest.mark.asyncio
    async def test_validates_es256_token_with_static_public_key(self) -> None:
        private_key, public_pem = _ec_key_pair()
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["ES256"],
            auth_jwt_public_key=public_pem,
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = _build_jwt(private_key, "ES256")
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(token)

        assert principal.subject == "user-1"

    @pytest.mark.asyncio
    async def test_rejects_es256_token_signed_with_wrong_key(self) -> None:
        _, public_pem = _ec_key_pair()
        other_private_key, _ = _ec_key_pair()
        settings = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["ES256"],
            auth_jwt_public_key=public_pem,
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = _build_jwt(other_private_key, "ES256")
        async with httpx.AsyncClient() as client:
            service = JWTAuthService(settings, client)
            with pytest.raises(AuthenticationError, match="Token validation failed"):
                await service.authenticate_token(token)


class TestJWKSKeyTypeBranching:
    """Tests for JWKS key resolution covering RSA and EC key types."""

    @pytest.mark.asyncio
    async def test_jwks_resolves_rsa_key_by_kid(self) -> None:
        private_key, _ = _rsa_key_pair()
        jwk_obj = jwt.algorithms.RSAAlgorithm(jwt.algorithms.RSAAlgorithm.SHA256)
        public_jwk = jwk_obj.to_jwk(private_key.public_key(), as_dict=True)
        public_jwk["kid"] = "rsa-key-1"
        public_jwk["use"] = "sig"
        public_jwk["alg"] = "RS256"

        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["RS256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = _build_jwt(private_key, "RS256", kid="rsa-key-1")
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"keys": [public_jwk]})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(token)

        assert principal.subject == "user-1"

    @pytest.mark.asyncio
    async def test_jwks_resolves_ec_key_by_kid(self) -> None:
        private_key, _ = _ec_key_pair()
        jwk_obj = jwt.algorithms.ECAlgorithm(jwt.algorithms.ECAlgorithm.SHA256)
        public_jwk = jwk_obj.to_jwk(private_key.public_key(), as_dict=True)
        public_jwk["kid"] = "ec-key-1"
        public_jwk["use"] = "sig"
        public_jwk["alg"] = "ES256"

        settings = make_settings(
            auth_enabled=True,
            auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
            auth_jwt_algorithms=["ES256"],
            auth_jwt_audience="fastapi-template",
            auth_jwt_issuer="https://issuer.example.com/",
        )
        token = _build_jwt(private_key, "ES256", kid="ec-key-1")
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"keys": [public_jwk]})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            service = JWTAuthService(settings, client)
            principal = await service.authenticate_token(token)

        assert principal.subject == "user-1"

    def test_get_jwk_key_for_kid_returns_none_for_missing_kid(self) -> None:
        jwks = {"keys": [{"kid": "other-key", "kty": "RSA"}]}
        with patch("app.auth.service.PyJWK.from_dict") as from_dict:
            from_dict.return_value = Mock(key="resolved-key")
            result = _get_jwk_key_for_kid(jwks, "missing-kid")
        assert result is None

    def test_get_jwk_key_for_kid_returns_key_for_matching_kid(self) -> None:
        jwks = {"keys": [{"kid": "my-key", "kty": "RSA"}]}
        with patch("app.auth.service.PyJWK.from_dict") as from_dict:
            from_dict.return_value = Mock(key="resolved-key")
            result = _get_jwk_key_for_kid(jwks, "my-key")
        assert result == "resolved-key"

    def test_get_jwk_key_for_kid_returns_none_for_empty_keys(self) -> None:
        assert _get_jwk_key_for_kid({"keys": []}, "any-kid") is None
