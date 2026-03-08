"""
Unit tests for application settings and validation.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import os

import pytest
from pydantic import ValidationError

from tests.helpers import make_settings

pytestmark = pytest.mark.unit

POSTGRES_TEST_TOKEN = "pg-test-token"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove APP_* env vars so tests exercise code defaults, not local overrides."""
    for key in os.environ.copy():
        if key.startswith("APP_"):
            monkeypatch.delenv(key)


class TestSettingsDefaults:
    """Verify default values are sensible for production."""

    def test_default_app_name(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.app_name == "FastAPI Template"

    def test_default_debug_off(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.debug is False

    def test_default_docs_are_disabled(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.docs_enabled is False
        assert s.redoc_enabled is False
        assert s.openapi_enabled is False

    def test_default_log_level(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.log_level == "INFO"

    def test_default_log_format(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.log_format == "text"

    def test_default_port(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.port == 8000

    def test_default_timeout(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.request_timeout == 30

    def test_default_cors_credentials_disabled(self) -> None:
        """Credentials are off by default to avoid conflicts with wildcard origins."""
        s = make_settings(metrics_enabled=False)
        assert s.cors_allow_credentials is False

    def test_default_cors_expose_headers_include_correlation_ids(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert "X-Request-ID" in s.cors_expose_headers
        assert "X-Correlation-ID" in s.cors_expose_headers

    def test_default_database_url_is_async_sqlite(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.database_url.startswith("sqlite+aiosqlite://")

    def test_default_alembic_url_is_sync_sqlite(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.alembic_database_url.startswith("sqlite://")

    def test_default_database_backend_is_sqlite(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.database_backend == "sqlite"

    def test_default_rate_limit_is_disabled(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.rate_limit_enabled is False

    def test_default_security_headers_enabled(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.security_headers_enabled is True

    def test_default_metrics_are_disabled(self) -> None:
        s = make_settings()
        assert s.metrics_enabled is False

    def test_default_trusted_hosts_are_local_only(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.trusted_hosts == ["localhost", "127.0.0.1", "test", "testserver"]

    def test_default_readiness_hides_details(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.readiness_include_details is False

    def test_default_diagnostic_endpoints_are_disabled(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.info_endpoint_enabled is False
        assert s.endpoints_listing_enabled is False


class TestSettingsValidation:
    """Pydantic validation rejects invalid configurations."""

    @pytest.mark.parametrize("port", [0, 70000])
    def test_invalid_port_rejected(self, port: int) -> None:
        with pytest.raises(ValidationError, match="port"):
            make_settings(port=port, metrics_enabled=False)

    def test_invalid_log_level(self) -> None:
        with pytest.raises(ValidationError, match="log_level"):
            make_settings(log_level="VERBOSE", metrics_enabled=False)

    def test_invalid_log_format(self) -> None:
        with pytest.raises(ValidationError, match="log_format"):
            make_settings(log_format="yaml", metrics_enabled=False)

    @pytest.mark.parametrize("timeout", [0, 999])
    def test_invalid_timeout_rejected(self, timeout: int) -> None:
        with pytest.raises(ValidationError, match="request_timeout"):
            make_settings(request_timeout=timeout, metrics_enabled=False)

    def test_valid_port_boundaries(self) -> None:
        s_low = make_settings(port=1, metrics_enabled=False)
        s_high = make_settings(port=65535, metrics_enabled=False)
        assert s_low.port == 1
        assert s_high.port == 65535

    def test_valid_log_levels(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            s = make_settings(log_level=level, metrics_enabled=False)
            assert s.log_level == level

    def test_auth_requires_issuer_when_enabled(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWT_ISSUER"):
            make_settings(
                auth_enabled=True,
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_requires_audience_when_enabled(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWT_AUDIENCE"):
            make_settings(
                auth_enabled=True,
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_issuer="https://issuer.example.com/",
                metrics_enabled=False,
            )

    def test_rate_limit_request_id_strategy_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="rate_limit_key_strategy"):
            make_settings(rate_limit_key_strategy="request_id", metrics_enabled=False)

    def test_auth_jwks_url_requires_https(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWKS_URL"):
            make_settings(
                auth_jwks_url="http://issuer.example.com/.well-known/jwks.json",
                metrics_enabled=False,
            )

    def test_proxy_header_trust_requires_explicit_trusted_proxies(self) -> None:
        with pytest.raises(ValidationError, match="APP_RATE_LIMIT_TRUSTED_PROXIES"):
            make_settings(
                rate_limit_trust_proxy_headers=True,
                metrics_enabled=False,
            )

    def test_invalid_trusted_proxy_network_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid trusted proxy network"):
            make_settings(
                rate_limit_trust_proxy_headers=True,
                rate_limit_trusted_proxies=["not-a-network"],
                metrics_enabled=False,
            )

    def test_valid_trusted_proxy_networks_are_accepted(self) -> None:
        s = make_settings(
            rate_limit_trust_proxy_headers=True,
            rate_limit_trusted_proxies=["10.0.0.0/8", "127.0.0.1/32"],
            metrics_enabled=False,
        )
        assert s.rate_limit_trusted_proxies == ["10.0.0.0/8", "127.0.0.1/32"]

    def test_security_proxy_trust_requires_explicit_trusted_proxies(self) -> None:
        with pytest.raises(ValidationError, match="APP_SECURITY_TRUSTED_PROXIES"):
            make_settings(
                security_trust_proxy_proto_header=True,
                metrics_enabled=False,
            )

    def test_invalid_security_trusted_proxy_network_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="APP_SECURITY_TRUSTED_PROXIES"):
            make_settings(
                security_trust_proxy_proto_header=True,
                security_trusted_proxies=["not-a-network"],
                metrics_enabled=False,
            )

    def test_valid_security_trusted_proxy_networks_are_accepted(self) -> None:
        s = make_settings(
            security_trust_proxy_proto_header=True,
            security_trusted_proxies=["10.0.0.0/8", "127.0.0.1/32"],
            metrics_enabled=False,
        )
        assert s.security_trusted_proxies == ["10.0.0.0/8", "127.0.0.1/32"]

    def test_postgres_backend_requires_password(self) -> None:
        with pytest.raises(ValidationError, match="APP_DATABASE_POSTGRES_PASSWORD"):
            make_settings(
                database_backend="postgres",
                metrics_enabled=False,
            )

    def test_custom_database_backend_requires_database_url(self) -> None:
        with pytest.raises(ValidationError, match="APP_DATABASE_URL"):
            make_settings(database_backend="custom", metrics_enabled=False)


class TestLoggingConfigPath:
    """The logging config path resolves to the bundled file by default."""

    def test_default_resolves_to_existing_file(self) -> None:
        from pathlib import Path

        s = make_settings(metrics_enabled=False)
        assert Path(s.logging_config_path).exists()
        assert s.logging_config_path.endswith("config.json")

    def test_custom_path_preserved(self) -> None:
        s = make_settings(logging_config_path="/tmp/custom.json", metrics_enabled=False)
        assert s.logging_config_path == "/tmp/custom.json"

    def test_empty_string_triggers_default(self) -> None:
        from pathlib import Path

        s = make_settings(logging_config_path="", metrics_enabled=False)
        assert Path(s.logging_config_path).exists()

    def test_postgres_backend_derives_runtime_and_alembic_urls(self) -> None:
        s = make_settings(
            database_backend="postgres",
            database_postgres_host="db.example.internal",
            database_postgres_port=5433,
            database_postgres_name="service",
            database_postgres_user="app",
            database_postgres_password=POSTGRES_TEST_TOKEN,
            metrics_enabled=False,
        )
        assert (
            s.database_url
            == f"postgresql+asyncpg://app:{POSTGRES_TEST_TOKEN}@db.example.internal:5433/service"
        )
        assert (
            s.alembic_database_url
            == f"postgresql+psycopg://app:{POSTGRES_TEST_TOKEN}@db.example.internal:5433/service"
        )

    def test_explicit_postgres_database_url_auto_derives_alembic_url(self) -> None:
        s = make_settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
            metrics_enabled=False,
        )
        assert s.alembic_database_url == "postgresql+psycopg://user:pass@localhost:5432/app"

    def test_custom_database_backend_accepts_explicit_urls(self) -> None:
        s = make_settings(
            database_backend="custom",
            database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
            alembic_database_url="postgresql+psycopg://user:pass@localhost:5432/app",
            metrics_enabled=False,
        )
        assert s.database_url == "postgresql+asyncpg://user:pass@localhost:5432/app"
        assert s.alembic_database_url == "postgresql+psycopg://user:pass@localhost:5432/app"

    def test_redis_rate_limit_backend_derives_storage_url(self) -> None:
        s = make_settings(
            rate_limit_storage_backend="redis",
            redis_host="cache.internal",
            redis_port=6380,
            redis_db=2,
            metrics_enabled=False,
        )
        assert s.rate_limit_storage_url == "redis://cache.internal:6380/2"

    def test_explicit_rate_limit_storage_url_overrides_backend_defaults(self) -> None:
        s = make_settings(
            rate_limit_storage_backend="redis",
            rate_limit_storage_url="redis://override:6379/5",
            metrics_enabled=False,
        )
        assert s.rate_limit_storage_url == "redis://override:6379/5"

    def test_otel_defaults_follow_app_metadata(self) -> None:
        s = make_settings(app_name="Template", app_version="2.0.0", metrics_enabled=False)
        assert s.otel_service_name == "Template"
        assert s.otel_service_version == "2.0.0"


class TestSettingsAuthEdgeCases:
    """Edge cases for auth validation paths."""

    def test_auth_rejects_mixed_algorithm_families(self) -> None:
        with pytest.raises(ValidationError, match="same algorithm family"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["HS256", "RS256"],
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_issuer="https://issuer.example.com/",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_rejects_short_hs_secret(self) -> None:
        with pytest.raises(ValidationError, match="at least 32 characters"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["HS256"],
                auth_jwt_secret="too-short",
                auth_jwt_issuer="https://issuer.example.com/",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_rejects_hs_with_public_key(self) -> None:
        with pytest.raises(ValidationError, match="cannot be combined"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["HS256"],
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwt_public_key="-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----",
                auth_jwt_issuer="https://issuer.example.com/",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_rejects_hs_with_jwks_url(self) -> None:
        with pytest.raises(ValidationError, match="cannot be combined"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["HS256"],
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
                auth_jwt_issuer="https://issuer.example.com/",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_rejects_asymmetric_with_secret(self) -> None:
        with pytest.raises(ValidationError, match="APP_AUTH_JWT_SECRET cannot be set"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["RS256"],
                auth_jwt_secret="super-secret-test-key-for-hs256-123",
                auth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
                auth_jwt_issuer="https://issuer.example.com/",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_rejects_enabled_without_key_material(self) -> None:
        with pytest.raises(ValidationError, match="no JWT verification material"):
            make_settings(
                auth_enabled=True,
                auth_jwt_algorithms=["RS256"],
                auth_jwt_issuer="https://issuer.example.com/",
                auth_jwt_audience="fastapi-template",
                metrics_enabled=False,
            )

    def test_auth_optional_issuer_when_require_issuer_false(self) -> None:
        s = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["HS256"],
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_audience="fastapi-template",
            auth_require_issuer=False,
            metrics_enabled=False,
        )
        assert s.auth_jwt_issuer == ""

    def test_auth_optional_audience_when_require_audience_false(self) -> None:
        s = make_settings(
            auth_enabled=True,
            auth_jwt_algorithms=["HS256"],
            auth_jwt_secret="super-secret-test-key-for-hs256-123",
            auth_jwt_issuer="https://issuer.example.com/",
            auth_require_audience=False,
            metrics_enabled=False,
        )
        assert s.auth_jwt_audience == ""

    def test_custom_backend_requires_alembic_url_when_not_derivable(self) -> None:
        with pytest.raises(ValidationError, match="APP_ALEMBIC_DATABASE_URL"):
            make_settings(
                database_backend="custom",
                database_url="mysql+aiomysql://user:pass@localhost/db",
                metrics_enabled=False,
            )

    def test_redis_password_included_in_derived_url(self) -> None:
        s = make_settings(
            rate_limit_storage_backend="redis",
            redis_host="cache.internal",
            redis_port=6380,
            redis_db=2,
            redis_password="s3cret",
            metrics_enabled=False,
        )
        assert s.rate_limit_storage_url == "redis://:s3cret@cache.internal:6380/2"


class TestCacheSettings:
    """Tests for cache-related settings."""

    def test_cache_disabled_by_default(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.cache_enabled is False

    def test_cache_default_backend_is_memory(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.cache_backend == "memory"

    def test_cache_default_ttl(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.cache_default_ttl_seconds == 300

    def test_cache_default_max_entries(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.cache_max_entries == 10_000

    def test_cache_default_redis_db_is_1(self) -> None:
        s = make_settings(metrics_enabled=False)
        assert s.cache_redis_db == 1

    def test_cache_redis_url_derived_from_shared_settings(self) -> None:
        s = make_settings(
            cache_enabled=True,
            cache_backend="redis",
            redis_host="cache.internal",
            redis_port=6380,
            redis_password="s3cret",
            cache_redis_db=3,
            metrics_enabled=False,
        )
        assert s.cache_storage_url == "redis://:s3cret@cache.internal:6380/3"

    def test_cache_explicit_url_overrides_derived(self) -> None:
        s = make_settings(
            cache_enabled=True,
            cache_backend="redis",
            cache_storage_url="redis://override:6379/5",
            metrics_enabled=False,
        )
        assert s.cache_storage_url == "redis://override:6379/5"

    def test_cache_memory_backend_leaves_url_empty(self) -> None:
        s = make_settings(
            cache_enabled=True,
            cache_backend="memory",
            metrics_enabled=False,
        )
        assert s.cache_storage_url == ""

    def test_cache_invalid_backend_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cache_backend"):
            make_settings(cache_backend="memcached", metrics_enabled=False)


class TestJWTAlgorithmFamilyHelper:
    """Tests for the _jwt_algorithm_family helper."""

    def test_unsupported_algorithm_raises_value_error(self) -> None:
        from app.settings import _jwt_algorithm_family

        with pytest.raises(ValueError, match="Unsupported JWT algorithm family"):
            _jwt_algorithm_family("UNKNOWN256")
