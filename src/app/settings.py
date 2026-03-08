"""
Application settings module using Pydantic Settings.

Provides typed, validated configuration with environment variable overrides.
All settings can be overridden via environment variables prefixed with APP_
or via a .env file.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

from ipaddress import ip_network
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable overrides.

    Configuration priority (highest to lowest):
    1. Environment variables (prefixed with APP_)
    2. .env file values
    3. Default values defined below
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Metadata
    app_name: str = Field(
        default="FastAPI Template",
        description="Application name used in metrics, logging, and OpenAPI docs",
    )
    app_version: str = Field(
        default="1.0.0",
        description="Semantic version of the application",
    )
    app_description: str = Field(
        default="Production-ready FastAPI template with Builder pattern configuration",
        description="Application description for OpenAPI docs",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode (exposes detailed error responses)",
    )
    docs_enabled: bool = Field(
        default=False,
        description="Expose the Swagger UI at /docs",
    )
    redoc_enabled: bool = Field(
        default=False,
        description="Expose the ReDoc UI at /redoc",
    )
    openapi_enabled: bool = Field(
        default=False,
        description="Expose the OpenAPI schema at /openapi.json",
    )

    # Server Configuration
    host: str = Field(default="127.0.0.1", description="Server bind address")
    port: int = Field(default=8000, ge=1, le=65535, description="Server bind port")

    # Logging
    log_level: str = Field(
        default="INFO",
        pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Application log level",
    )
    log_format: str = Field(
        default="text",
        pattern="^(text|json)$",
        description="Log output format",
    )
    log_text_template: str = Field(
        default=(
            "%(asctime)s | %(levelname)-8s | %(name)s"
            " | request_id=%(request_id)s"
            " | correlation_id=%(correlation_id)s"
            " | %(module)s:%(funcName)s:%(lineno)d | %(message)s"
        ),
        description="Python logging format string used when log_format is 'text'",
    )
    log_date_format: str = Field(
        default="%Y-%m-%d %H:%M:%S",
        description="Date format string for log timestamps (strftime syntax)",
    )
    logging_config_path: str = Field(
        default="",
        description="Path to JSON logging configuration file. Defaults to bundled config.",
    )
    log_redact_headers: bool = Field(
        default=False,
        description="Redact user-agent and referer values in request logs to reduce PII exposure",
    )

    # Database
    database_backend: str = Field(
        default="sqlite",
        pattern="^(sqlite|postgres|custom)$",
        description="Select the primary application database backend",
    )
    database_sqlite_path: str = Field(
        default="./data/app.db",
        description="SQLite file path used when APP_DATABASE_BACKEND=sqlite",
    )
    database_postgres_host: str = Field(
        default="postgres",
        description="Postgres host used when APP_DATABASE_BACKEND=postgres",
    )
    database_postgres_port: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="Postgres port used when APP_DATABASE_BACKEND=postgres",
    )
    database_postgres_name: str = Field(
        default="fastapi_template",
        description="Postgres database name used when APP_DATABASE_BACKEND=postgres",
    )
    database_postgres_user: str = Field(
        default="fastapi",
        description="Postgres username used when APP_DATABASE_BACKEND=postgres",
    )
    database_postgres_password: str = Field(
        default="",
        description="Postgres password used when APP_DATABASE_BACKEND=postgres",
    )
    database_url: str = Field(
        default="",
        description="Explicit async SQLAlchemy database URL; overrides backend-derived defaults",
    )
    alembic_database_url: str = Field(
        default="",
        description="Explicit sync Alembic database URL; overrides backend-derived defaults",
    )
    database_echo: bool = Field(
        default=False,
        description="Enable SQL echo logging for the local SQLite template",
    )
    database_pool_size: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Connection pool size for explicit non-SQLite deployments",
    )
    database_max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Maximum overflow connections for explicit non-SQLite deployments",
    )
    database_pool_pre_ping: bool = Field(
        default=True,
        description="Ping pooled connections before use for non-SQLite pooled backends",
    )
    database_connect_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="SQLite driver timeout, and the default connect timeout baseline for other DBs",
    )
    database_health_timeout_seconds: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Maximum time allowed for the readiness ping against the configured database",
    )

    # Stateless JWT resource-server auth
    auth_enabled: bool = Field(
        default=False,
        description="Enable JWT authentication and authorization dependencies",
    )
    auth_jwt_issuer: str = Field(default="", description="Expected JWT issuer claim")
    auth_jwt_audience: str = Field(default="", description="Expected JWT audience claim")
    auth_jwt_algorithms: list[str] = Field(
        default=["HS256"],
        description="Allowed JWT signature algorithms",
    )
    auth_jwt_secret: str = Field(
        default="",
        description="Shared secret for symmetric JWT validation in local/test use",
    )
    auth_jwt_public_key: str = Field(
        default="",
        description="PEM-encoded public key for asymmetric JWT validation",
    )
    auth_jwks_url: str = Field(default="", description="JWKS endpoint for rotating signing keys")
    auth_require_exp: bool = Field(
        default=True,
        description="Require exp claims on JWTs validated by this resource server",
    )
    auth_require_issuer: bool = Field(
        default=True,
        description="Require APP_AUTH_JWT_ISSUER when authentication is enabled",
    )
    auth_require_audience: bool = Field(
        default=True,
        description="Require APP_AUTH_JWT_AUDIENCE when authentication is enabled",
    )
    auth_jwks_cache_ttl_seconds: int = Field(
        default=300,
        ge=5,
        le=86400,
        description="JWKS cache TTL in seconds",
    )
    auth_clock_skew_seconds: int = Field(
        default=30,
        ge=0,
        le=300,
        description="Allowed JWT clock skew in seconds",
    )
    auth_http_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="HTTP timeout used for JWKS and auth-adjacent network calls",
    )

    # CORS
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="List of allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(
        default=False,
        description="Allow credentials in CORS requests",
    )
    cors_allowed_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        description="List of allowed HTTP methods for CORS",
    )
    cors_allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID"],
        description="List of allowed headers for CORS",
    )
    cors_expose_headers: list[str] = Field(
        default=["X-Request-ID", "X-Correlation-ID", "X-RateLimit-Remaining"],
        description="Headers exposed to the browser in CORS responses",
    )

    # Middleware and request hardening
    request_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Request timeout in seconds",
    )
    max_request_body_bytes: int = Field(
        default=5_242_880,
        ge=1024,
        le=104_857_600,
        description="Maximum request body size in bytes",
    )
    trusted_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1", "test", "testserver"],
        description="Allowed Host headers for TrustedHostMiddleware",
    )
    security_headers_enabled: bool = Field(
        default=True,
        description="Enable default security response headers",
    )
    security_hsts_enabled: bool = Field(
        default=False,
        description="Enable HSTS when requests arrive over HTTPS",
    )
    security_hsts_max_age_seconds: int = Field(
        default=31_536_000,
        ge=0,
        le=63_072_000,
        description="HSTS max-age in seconds",
    )
    security_referrer_policy: str = Field(
        default="no-referrer",
        description="Referrer-Policy header value",
    )
    security_permissions_policy: str = Field(
        default="geolocation=(), camera=(), microphone=()",
        description="Permissions-Policy header value",
    )
    security_content_security_policy: str = Field(
        default="default-src 'none'; frame-ancestors 'none'",
        description="Content-Security-Policy header value (empty string to disable)",
    )
    security_trust_proxy_proto_header: bool = Field(
        default=False,
        description="Honor X-Forwarded-Proto for HTTPS-aware headers when behind a trusted proxy",
    )
    security_trusted_proxies: list[str] = Field(
        default=[],
        description=(
            "Explicit proxy IPs or CIDRs allowed to supply forwarded protocol headers "
            "for security middleware"
        ),
    )

    # Metrics and tracing
    metrics_enabled: bool = Field(
        default=False,
        description="Enable Prometheus metrics collection",
    )
    metrics_prefix: str = Field(
        default="http",
        description="Prefix for Prometheus metric names",
    )
    otel_enabled: bool = Field(default=False, description="Enable OpenTelemetry tracing")
    otel_service_name: str = Field(
        default="",
        description="OpenTelemetry service.name resource attribute",
    )
    otel_service_version: str = Field(
        default="",
        description="OpenTelemetry service.version resource attribute",
    )
    otel_environment: str = Field(
        default="development",
        description="OpenTelemetry deployment.environment resource attribute",
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4318/v1/traces",
        description="OTLP HTTP trace exporter endpoint",
    )
    otel_exporter_otlp_headers: str = Field(
        default="",
        description="Comma-separated OTLP headers formatted as key=value,key2=value2",
    )

    # Health and readiness
    health_check_path: str = Field(
        default="/healthcheck",
        description="Path for the liveness health check endpoint",
    )
    readiness_check_path: str = Field(
        default="/ready",
        description="Path for the readiness check endpoint",
    )
    readiness_include_details: bool = Field(
        default=False,
        description="Expose detailed dependency failure messages in readiness responses",
    )

    # Utility endpoints
    info_endpoint_enabled: bool = Field(
        default=False,
        description="Expose the /info diagnostic endpoint",
    )
    endpoints_listing_enabled: bool = Field(
        default=False,
        description="Expose the /endpoints route inventory endpoint",
    )

    # Rate limiting
    rate_limit_enabled: bool = Field(default=False, description="Enable request rate limiting")
    rate_limit_requests: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum requests allowed per window",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Rate limit window length in seconds",
    )
    rate_limit_key_strategy: str = Field(
        default="ip",
        pattern="^(ip|authorization)$",
        description="Strategy used to build the rate limiting key",
    )
    rate_limit_storage_url: str = Field(
        default="",
        description="Explicit Redis URL for distributed rate limiting",
    )
    rate_limit_storage_backend: str = Field(
        default="memory",
        pattern="^(memory|redis)$",
        description="Storage backend used for rate limiting when enabled",
    )
    redis_host: str = Field(
        default="redis",
        description="Redis host used when APP_RATE_LIMIT_STORAGE_BACKEND=redis",
    )
    redis_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis port used when APP_RATE_LIMIT_STORAGE_BACKEND=redis",
    )
    redis_db: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Redis database index used when APP_RATE_LIMIT_STORAGE_BACKEND=redis",
    )
    redis_password: str = Field(
        default="",
        description="Optional Redis password used when APP_RATE_LIMIT_STORAGE_BACKEND=redis",
    )
    rate_limit_trust_proxy_headers: bool = Field(
        default=False,
        description="Honor proxy IP headers for rate limiting when behind a trusted proxy",
    )
    rate_limit_proxy_headers: list[str] = Field(
        default=["X-Forwarded-For", "X-Real-IP"],
        description="Headers inspected for the client IP when proxy trust is enabled",
    )
    rate_limit_trusted_proxies: list[str] = Field(
        default=[],
        description=(
            "Explicit proxy IPs or CIDRs allowed to supply forwarded client IP headers "
            "for rate limiting"
        ),
    )

    # Cache
    cache_enabled: bool = Field(
        default=False,
        description="Enable the application cache layer",
    )
    cache_backend: str = Field(
        default="memory",
        pattern="^(memory|redis)$",
        description="Storage backend: memory (in-process) or redis (distributed)",
    )
    cache_default_ttl_seconds: int = Field(
        default=300,
        ge=1,
        le=86400,
        description="Default cache entry time-to-live in seconds",
    )
    cache_max_entries: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
        description="Maximum entries in the in-memory cache before eviction",
    )
    cache_key_prefix: str = Field(
        default="cache:",
        description="Key prefix applied to all cache entries (useful for Redis namespacing)",
    )
    cache_redis_db: int = Field(
        default=1,
        ge=0,
        le=15,
        description="Redis database index used when APP_CACHE_BACKEND=redis",
    )
    cache_storage_url: str = Field(
        default="",
        description="Explicit Redis URL for cache; overrides APP_REDIS_* derivation",
    )
    cache_health_timeout_seconds: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Maximum time allowed for the readiness ping against the cache store",
    )

    @model_validator(mode="after")
    def _resolve_paths_and_defaults(self) -> "Settings":
        """Resolve derived settings values after environment parsing."""
        _resolve_logging_defaults(self)
        _resolve_database_defaults(self)
        _resolve_otel_defaults(self)
        _resolve_rate_limit_storage_defaults(self)
        _resolve_cache_storage_defaults(self)
        _resolve_csp_for_docs(self)
        _validate_auth_settings(self)
        _validate_proxy_settings(self)
        return self


def _derive_alembic_database_url(database_url: str) -> str:
    """Derive a sync Alembic URL from the configured async runtime URL when possible."""
    sqlite_prefix = "sqlite+aiosqlite://"
    if database_url.startswith(sqlite_prefix):
        return database_url.replace(sqlite_prefix, "sqlite://", 1)

    postgres_prefix = "postgresql+asyncpg://"
    if database_url.startswith(postgres_prefix):
        return database_url.replace(postgres_prefix, "postgresql+psycopg://", 1)

    raise ValueError("APP_ALEMBIC_DATABASE_URL must be set explicitly for this database URL")


def _jwt_algorithm_family(algorithm: str) -> str:
    """Collapse JWT algorithms into their signing-key family."""
    for family in ("HS", "RS", "ES", "PS", "EdDSA"):
        if algorithm.startswith(family):
            return family
    raise ValueError(f"Unsupported JWT algorithm family for {algorithm}")


def _derive_database_url(settings: Settings) -> str:
    """Build a runtime database URL from the selected backend configuration."""
    if settings.database_backend == "sqlite":
        return f"sqlite+aiosqlite:///{settings.database_sqlite_path}"

    if settings.database_backend == "postgres":
        if not settings.database_postgres_password:
            raise ValueError(
                "APP_DATABASE_POSTGRES_PASSWORD must be set when APP_DATABASE_BACKEND=postgres"
            )
        return (
            "postgresql+asyncpg://"
            f"{settings.database_postgres_user}:{settings.database_postgres_password}"
            f"@{settings.database_postgres_host}:{settings.database_postgres_port}"
            f"/{settings.database_postgres_name}"
        )

    raise ValueError("APP_DATABASE_URL must be set when APP_DATABASE_BACKEND=custom")


def _build_redis_url(*, host: str, port: int, db: int, password: str) -> str:
    """Build a Redis URL from discrete connection settings."""
    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def _resolve_logging_defaults(settings: Settings) -> None:
    """Populate derived logging configuration defaults."""
    if not settings.logging_config_path:
        settings.logging_config_path = str(
            Path(__file__).resolve().parent / "log_config" / "config.json"
        )


def _resolve_database_defaults(settings: Settings) -> None:
    """Populate derived runtime and Alembic database URLs."""
    if not settings.database_url:
        settings.database_url = _derive_database_url(settings)
    if not settings.alembic_database_url:
        settings.alembic_database_url = _derive_alembic_database_url(settings.database_url)


def _resolve_otel_defaults(settings: Settings) -> None:
    """Populate OpenTelemetry resource defaults from app metadata."""
    if not settings.otel_service_name:
        settings.otel_service_name = settings.app_name
    if not settings.otel_service_version:
        settings.otel_service_version = settings.app_version


def _resolve_rate_limit_storage_defaults(settings: Settings) -> None:
    """Populate the Redis storage URL from selector-style settings."""
    if settings.rate_limit_storage_url or settings.rate_limit_storage_backend != "redis":
        return

    settings.rate_limit_storage_url = _build_redis_url(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password,
    )


def _resolve_cache_storage_defaults(settings: Settings) -> None:
    """Populate the Redis storage URL for caching from selector-style settings."""
    if settings.cache_storage_url or settings.cache_backend != "redis":
        return

    settings.cache_storage_url = _build_redis_url(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.cache_redis_db,
        password=settings.redis_password,
    )


_DEFAULT_CSP = "default-src 'none'; frame-ancestors 'none'"


def _resolve_csp_for_docs(settings: Settings) -> None:
    """Extend the default CSP when Swagger UI or ReDoc are enabled.

    Swagger UI and ReDoc load external scripts, styles, fonts, and images from
    CDNs.  The strict production default (``default-src 'none'``) blocks all of
    these, making the docs pages unusable.  When either docs endpoint is enabled
    and the CSP has not been customized, this resolver automatically extends the
    policy with the minimum directives required.

    If the operator has already set a custom CSP value, it is left untouched so
    explicit configuration always wins.
    """
    if not (settings.docs_enabled or settings.redoc_enabled):
        return

    if settings.security_content_security_policy != _DEFAULT_CSP:
        return

    directives = [
        "default-src 'none'",
        "connect-src 'self' https://cdn.jsdelivr.net",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "img-src 'self' https://fastapi.tiangolo.com",
        "frame-ancestors 'none'",
    ]

    if settings.redoc_enabled:
        directives[3] += " https://fonts.googleapis.com"
        directives[4] += " data: https://cdn.redoc.ly"
        directives.insert(-1, "font-src 'self' https://fonts.gstatic.com")
        directives.insert(-1, "worker-src 'self' blob:")

    settings.security_content_security_policy = "; ".join(directives)


def _validate_auth_settings(settings: Settings) -> None:
    """Validate JWT/auth-related configuration after defaults resolve."""
    if settings.auth_jwks_url and not settings.auth_jwks_url.startswith("https://"):
        raise ValueError("APP_AUTH_JWKS_URL must use https://")

    if not settings.auth_enabled:
        return

    algorithm_families = {
        _jwt_algorithm_family(algorithm) for algorithm in settings.auth_jwt_algorithms
    }
    if len(algorithm_families) != 1:
        raise ValueError("APP_AUTH_JWT_ALGORITHMS must all belong to the same algorithm family")

    uses_shared_secret = "HS" in algorithm_families
    _validate_auth_key_material(settings, uses_shared_secret)
    _validate_auth_claim_requirements(settings)


def _validate_auth_key_material(settings: Settings, uses_shared_secret: bool) -> None:
    """Validate the configured JWT verification material."""
    if uses_shared_secret and len(settings.auth_jwt_secret) < 32:
        raise ValueError(
            "auth_jwt_secret must be at least 32 characters when HS* algorithms are enabled"
        )
    if uses_shared_secret and (settings.auth_jwt_public_key or settings.auth_jwks_url):
        raise ValueError(
            "HS* algorithms cannot be combined with APP_AUTH_JWT_PUBLIC_KEY or APP_AUTH_JWKS_URL"
        )
    if not uses_shared_secret and settings.auth_jwt_secret:
        raise ValueError("APP_AUTH_JWT_SECRET cannot be set with asymmetric JWT algorithms")

    has_key_material = bool(
        settings.auth_jwks_url
        or settings.auth_jwt_public_key
        or (settings.auth_jwt_secret and uses_shared_secret)
    )
    if not has_key_material:
        raise ValueError("Authentication is enabled but no JWT verification material is configured")


def _validate_auth_claim_requirements(settings: Settings) -> None:
    """Validate required issuer and audience settings for auth."""
    if settings.auth_require_issuer and not settings.auth_jwt_issuer:
        raise ValueError("APP_AUTH_JWT_ISSUER must be set when authentication is enabled")
    if settings.auth_require_audience and not settings.auth_jwt_audience:
        raise ValueError("APP_AUTH_JWT_AUDIENCE must be set when authentication is enabled")


def _validate_proxy_settings(settings: Settings) -> None:
    """Validate proxy-trust configuration for rate limiting and HTTPS semantics."""
    _validate_trusted_proxy_list(
        trust_enabled=settings.rate_limit_trust_proxy_headers,
        proxies=settings.rate_limit_trusted_proxies,
        setting_name="APP_RATE_LIMIT_TRUSTED_PROXIES",
        toggle_name="APP_RATE_LIMIT_TRUST_PROXY_HEADERS",
    )
    _validate_trusted_proxy_list(
        trust_enabled=settings.security_trust_proxy_proto_header,
        proxies=settings.security_trusted_proxies,
        setting_name="APP_SECURITY_TRUSTED_PROXIES",
        toggle_name="APP_SECURITY_TRUST_PROXY_PROTO_HEADER",
    )


def _validate_trusted_proxy_list(
    *,
    trust_enabled: bool,
    proxies: list[str],
    setting_name: str,
    toggle_name: str,
) -> None:
    """Require and validate proxy CIDR allowlists when trust is enabled."""
    if trust_enabled and not proxies:
        raise ValueError(f"{setting_name} must be set when {toggle_name}=true")

    for proxy in proxies:
        try:
            ip_network(proxy, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid trusted proxy network in {setting_name}: {proxy}") from exc
