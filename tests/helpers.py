"""
Shared test utilities.

Provides factory functions for settings, JWT tokens, and principals
so that test files can avoid duplicating boilerplate setup code.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

from app.auth.models import Principal
from app.auth.service import build_test_jwt
from app.settings import Settings

# ──────────────────────────────────────────────
# Constants matching the default test auth config
# ──────────────────────────────────────────────

TEST_SECRET = "super-secret-test-key-for-hs256-123"
TEST_AUDIENCE = "fastapi-template"
TEST_ISSUER = "https://issuer.example.com/"


# ──────────────────────────────────────────────
# Factory functions
# ──────────────────────────────────────────────


def make_settings(**overrides: object) -> Settings:
    """Build Settings isolated from local environment and .env files."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type, call-arg]


def make_jwt(
    subject: str = "test-user",
    *,
    secret: str = TEST_SECRET,
    audience: str | None = TEST_AUDIENCE,
    issuer: str | None = TEST_ISSUER,
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
    expires_in_seconds: int = 300,
) -> str:
    """Mint an HS256 test JWT with sensible defaults."""
    return build_test_jwt(
        subject=subject,
        secret=secret,
        audience=audience,
        issuer=issuer,
        scopes=scopes,
        roles=roles,
        expires_in_seconds=expires_in_seconds,
    )


def make_principal(
    subject: str = "test-user",
    *,
    issuer: str | None = TEST_ISSUER,
    audience: list[str] | None = None,
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
) -> Principal:
    """Build a Principal with sensible defaults."""
    return Principal(
        subject=subject,
        issuer=issuer,
        audience=audience or [TEST_AUDIENCE],
        scopes=scopes or [],
        roles=roles or [],
        claims={"sub": subject},
    )
