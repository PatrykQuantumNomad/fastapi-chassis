#!/usr/bin/env python3
"""
Live verification harness for the FastAPI template stack.

By default this script boots an isolated application instance with a temporary
SQLite database, local HS256 auth, Prometheus metrics, and a lightweight OTLP
capture server. Optional environment variables let the same harness target
external Postgres, Redis, and JWKS-backed verification flows for more
production-like coverage.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, NoReturn, cast
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from uuid import uuid4

import jwt
import uvicorn
from alembic.config import Config
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import Query, Request
from opentelemetry import trace
from sqlalchemy import select

from alembic import command
from app import create_app
from app.auth.service import build_test_jwt
from app.db.models import ExampleWidget
from app.settings import Settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTH_SECRET = "verification-secret-0123456789abcd"
AUTH_ISSUER = "https://verification.local/"
AUTH_AUDIENCE = "fastapi-template-live-check"
HEALTH_PATH = "/healthcheck"
READY_PATH = "/ready"
METRICS_PATH = "/metrics"
JWKS_PATH = "/.well-known/jwks.json"
JWKS_KID = "verification-jwks-key"


class VerificationError(RuntimeError):
    """Raised when one of the live verification checks fails."""


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _info(message: str) -> None:
    print(f"[verify-stack] {message}")


@dataclass
class TraceCaptureState:
    """Shared state for the in-process OTLP capture server."""

    requests: list[dict[str, Any]] = field(default_factory=list)
    received_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class VerificationConfig:
    """Configuration for local or production-like verification modes."""

    database_url: str | None
    alembic_database_url: str | None
    redis_url: str | None
    auth_mode: str

    @property
    def uses_external_database(self) -> bool:
        return self.database_url is not None and self.alembic_database_url is not None

    @property
    def uses_redis(self) -> bool:
        return bool(self.redis_url)


@dataclass
class JWKSKeyMaterial:
    """Signing and serving material for the local JWKS verification path."""

    private_key_pem: str
    jwks_payload: dict[str, Any]


@dataclass
class ResponseSnapshot:
    """Minimal HTTP response wrapper for stdlib-based verification requests."""

    status_code: int
    text: str
    headers: dict[str, str]

    def json(self) -> Any:
        return json.loads(self.text)


class TraceCaptureHandler(BaseHTTPRequestHandler):
    """Capture OTLP HTTP trace exports from the OpenTelemetry exporter."""

    server: TraceCaptureHTTPServer

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        self.server.capture_state.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body_size": len(body),
            }
        )
        self.server.capture_state.received_event.set()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        _ = format, args


class TraceCaptureHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server that stores OTLP capture state."""

    def __init__(self, server_address: tuple[str, int], capture_state: TraceCaptureState) -> None:
        super().__init__(server_address, TraceCaptureHandler)
        self.capture_state = capture_state


class JWKSHandler(BaseHTTPRequestHandler):
    """Serve a static JWKS payload over HTTPS for verification mode."""

    server: JWKSHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path != JWKS_PATH:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return

        payload = json.dumps(self.server.jwks_payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        _ = format, args


class JWKSHTTPServer(ThreadingHTTPServer):
    """Threaded HTTPS server that exposes a verification JWKS payload."""

    def __init__(
        self,
        server_address: tuple[str, int],
        jwks_payload: dict[str, Any],
        ssl_context: ssl.SSLContext,
    ) -> None:
        super().__init__(server_address, JWKSHandler)
        self.jwks_payload = jwks_payload
        self.socket = ssl_context.wrap_socket(self.socket, server_side=True)


class QuietUvicornServer(uvicorn.Server):
    """Uvicorn server that skips signal registration in background threads."""

    def install_signal_handlers(self) -> None:
        return


def _run_migrations(database_path: Path) -> None:
    _run_migrations_for_url(f"sqlite:///{database_path}")


def _run_migrations_for_url(database_url: str) -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _load_verification_config() -> VerificationConfig:
    database_url = os.environ.get("VERIFY_STACK_DATABASE_URL")
    alembic_database_url = os.environ.get("VERIFY_STACK_ALEMBIC_DATABASE_URL")
    redis_url = os.environ.get("VERIFY_STACK_REDIS_URL") or None
    auth_mode = os.environ.get("VERIFY_STACK_AUTH_MODE", "shared-secret")

    if bool(database_url) != bool(alembic_database_url):
        _fail(
            "VERIFY_STACK_DATABASE_URL and VERIFY_STACK_ALEMBIC_DATABASE_URL must be set together"
        )
    if auth_mode not in {"shared-secret", "jwks"}:
        _fail("VERIFY_STACK_AUTH_MODE must be either 'shared-secret' or 'jwks'")

    return VerificationConfig(
        database_url=database_url,
        alembic_database_url=alembic_database_url,
        redis_url=redis_url,
        auth_mode=auth_mode,
    )


def _build_settings(
    config: VerificationConfig,
    database_path: Path | None,
    app_port: int,
    otlp_port: int,
    jwks_url: str | None,
) -> Settings:
    database_url = config.database_url or f"sqlite+aiosqlite:///{database_path}"
    alembic_database_url = config.alembic_database_url or f"sqlite:///{database_path}"
    auth_kwargs: dict[str, object]
    if config.auth_mode == "jwks":
        auth_kwargs = {
            "auth_enabled": True,
            "auth_jwks_url": jwks_url,
            "auth_jwt_algorithms": ["RS256"],
            "auth_jwt_issuer": AUTH_ISSUER,
            "auth_jwt_audience": AUTH_AUDIENCE,
        }
    else:
        auth_kwargs = {
            "auth_enabled": True,
            "auth_jwt_secret": AUTH_SECRET,
            "auth_jwt_issuer": AUTH_ISSUER,
            "auth_jwt_audience": AUTH_AUDIENCE,
        }

    rate_limit_kwargs: dict[str, object] = {}
    if config.uses_redis:
        rate_limit_kwargs = {
            "rate_limit_enabled": True,
            "rate_limit_storage_url": config.redis_url,
            "rate_limit_key_strategy": "authorization",
            "rate_limit_requests": 5,
            "rate_limit_window_seconds": 60,
        }

    return Settings(
        _env_file=None,
        app_name="FastAPI Template Verification",
        app_version="0.0.1-verify",
        debug=False,
        docs_enabled=False,
        redoc_enabled=False,
        openapi_enabled=False,
        host="127.0.0.1",
        port=app_port,
        log_level="WARNING",
        database_url=database_url,
        alembic_database_url=alembic_database_url,
        metrics_enabled=True,
        readiness_include_details=True,
        info_endpoint_enabled=True,
        endpoints_listing_enabled=True,
        otel_enabled=True,
        otel_environment="verification",
        otel_exporter_otlp_endpoint=f"http://127.0.0.1:{otlp_port}/v1/traces",
        **auth_kwargs,
        **rate_limit_kwargs,
    )


def _attach_verification_routes(app: Any) -> None:
    @app.get("/__verify/db")
    async def verify_database(request: Request) -> dict[str, object]:
        session_factory = cast(
            "async_sessionmaker[AsyncSession]",
            request.app.state.db_session_factory,
        )
        widget_name = f"widget-{uuid4().hex}"
        async with session_factory() as session:
            widget = ExampleWidget(name=widget_name)
            session.add(widget)
            await session.commit()

            result = await session.execute(
                select(ExampleWidget).where(ExampleWidget.name == widget_name)
            )
            saved_widget = result.scalar_one()

        return {
            "status": "ok",
            "widget_id": saved_widget.id,
            "widget_name": saved_widget.name,
        }

    @app.get("/__verify/validated")
    async def verify_validation(count: int = Query(..., ge=1)) -> dict[str, int]:
        return {"count": count}

    @app.get("/__verify/crash")
    async def verify_crash() -> dict[str, str]:
        raise RuntimeError("verification crash")

    @app.get("/__verify/rate-limit")
    async def verify_rate_limit() -> dict[str, str]:
        return {"status": "ok"}


def _start_trace_capture_server(
    host: str, capture_state: TraceCaptureState
) -> tuple[TraceCaptureHTTPServer, threading.Thread]:
    port = 0
    server = TraceCaptureHTTPServer((host, port), capture_state)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="otlp-capture")
    thread.start()
    return server, thread


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate_jwks_key_material() -> JWKSKeyMaterial:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_numbers = private_key.public_key().public_numbers()
    jwks_payload = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": JWKS_KID,
                "n": _b64url_uint(public_numbers.n),
                "e": _b64url_uint(public_numbers.e),
            }
        ]
    }
    return JWKSKeyMaterial(private_key_pem=private_key_pem, jwks_payload=jwks_payload)


def _write_local_tls_certificate(temp_path: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FastAPI Template Verification"),
            x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(tz=UTC) - timedelta(minutes=5))
        .not_valid_after(datetime.now(tz=UTC) + timedelta(days=7))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path = temp_path / "jwks-cert.pem"
    key_path = temp_path / "jwks-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _start_jwks_server(
    host: str,
    temp_path: Path,
    key_material: JWKSKeyMaterial,
) -> tuple[JWKSHTTPServer, threading.Thread, str, Path]:
    cert_path, key_path = _write_local_tls_certificate(temp_path)
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server = JWKSHTTPServer((host, 0), key_material.jwks_payload, ssl_context)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="jwks-verify")
    thread.start()
    port = int(server.server_address[1])
    return server, thread, f"https://127.0.0.1:{port}{JWKS_PATH}", cert_path


def _build_rs256_test_jwt(
    *,
    subject: str,
    private_key_pem: str,
    audience: str,
    issuer: str,
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
    expires_in_seconds: int = 300,
) -> str:
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": datetime.now(tz=UTC) + timedelta(seconds=expires_in_seconds),
        "aud": audience,
        "iss": issuer,
    }
    if scopes:
        payload["scope"] = " ".join(scopes)
    if roles:
        payload["roles"] = roles
    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers={"kid": JWKS_KID})


def _start_app_server(app: Any, host: str) -> tuple[QuietUvicornServer, threading.Thread]:
    config = uvicorn.Config(
        app,
        host=host,
        port=0,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = QuietUvicornServer(config)
    thread = threading.Thread(target=server.run, daemon=True, name="uvicorn-verify")
    thread.start()

    deadline = time.time() + 20
    while time.time() < deadline:
        if server.started:
            return server, thread
        if not thread.is_alive():
            _fail("The verification app server exited before startup completed")
        time.sleep(0.1)

    _fail("Timed out waiting for the verification app server to start")


def _get_uvicorn_port(server: QuietUvicornServer) -> int:
    servers = getattr(server, "servers", [])
    if not servers:
        _fail("Uvicorn did not expose any listening sockets")

    sockets = getattr(servers[0], "sockets", [])
    if not sockets:
        _fail("Uvicorn started without any bound sockets")

    sock = sockets[0]
    return int(sock.getsockname()[1])


def _stop_app_server(server: QuietUvicornServer, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)
    if thread.is_alive():
        _fail("Timed out waiting for the verification app server to stop")


def _send_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout_seconds: int = 5,
) -> ResponseSnapshot:
    url = f"{base_url}{path}"
    if params:
        query = urllib_parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    request = urllib_request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            return ResponseSnapshot(
                status_code=response.status,
                text=body,
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return ResponseSnapshot(
            status_code=exc.code,
            text=body,
            headers=dict(exc.headers.items()),
        )
    except URLError as exc:
        _fail(f"Request to {url} failed: {exc}")


def _wait_for_ready(base_url: str, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""

    while time.time() < deadline:
        try:
            response = _send_request(base_url, HEALTH_PATH, timeout_seconds=2)
            if response.status_code == 200:
                return
            last_error = f"unexpected {HEALTH_PATH} status {response.status_code}"
        except VerificationError as exc:
            last_error = str(exc)
        time.sleep(0.2)

    _fail(f"Timed out waiting for the app to become reachable: {last_error}")


def _assert_status(
    response: ResponseSnapshot,
    expected_status: int,
    *,
    context: str,
) -> None:
    if response.status_code != expected_status:
        _fail(
            f"{context}: expected HTTP {expected_status}, got {response.status_code} with "
            f"body {response.text!r}"
        )


def _assert_contains(text: str, needle: str, *, context: str) -> None:
    if needle not in text:
        _fail(f"{context}: expected to find {needle!r}")


def _force_flush_traces() -> None:
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if callable(force_flush):
        flushed = bool(force_flush())
        if not flushed:
            _fail("OpenTelemetry tracer provider reported a failed force_flush()")


def _verify_live_stack(
    base_url: str,
    capture_state: TraceCaptureState,
    config: VerificationConfig,
    jwks_keys: JWKSKeyMaterial | None,
) -> None:
    if config.auth_mode == "jwks":
        if jwks_keys is None:
            _fail("JWKS auth mode requires local JWKS key material")
        admin_token = _build_rs256_test_jwt(
            subject="verification-admin",
            private_key_pem=jwks_keys.private_key_pem,
            issuer=AUTH_ISSUER,
            audience=AUTH_AUDIENCE,
            scopes=["reports:read"],
            roles=["admin"],
        )
        reports_only_token = _build_rs256_test_jwt(
            subject="verification-reporter",
            private_key_pem=jwks_keys.private_key_pem,
            issuer=AUTH_ISSUER,
            audience=AUTH_AUDIENCE,
            scopes=["reports:read"],
            roles=["analyst"],
        )
        rate_limit_token = _build_rs256_test_jwt(
            subject="verification-rate-limit",
            private_key_pem=jwks_keys.private_key_pem,
            issuer=AUTH_ISSUER,
            audience=AUTH_AUDIENCE,
            scopes=["reports:read"],
            roles=["analyst"],
        )
    else:
        admin_token = build_test_jwt(
            subject="verification-admin",
            secret=AUTH_SECRET,
            issuer=AUTH_ISSUER,
            audience=AUTH_AUDIENCE,
            scopes=["reports:read"],
            roles=["admin"],
        )
        reports_only_token = build_test_jwt(
            subject="verification-reporter",
            secret=AUTH_SECRET,
            issuer=AUTH_ISSUER,
            audience=AUTH_AUDIENCE,
            scopes=["reports:read"],
            roles=["analyst"],
        )
        rate_limit_token = build_test_jwt(
            subject="verification-rate-limit",
            secret=AUTH_SECRET,
            issuer=AUTH_ISSUER,
            audience=AUTH_AUDIENCE,
            scopes=["reports:read"],
            roles=["analyst"],
        )

    _wait_for_ready(base_url)

    _info("Checking root, liveness, and readiness endpoints")
    root_response = _send_request(base_url, "/")
    _assert_status(root_response, 200, context="root endpoint")
    root_payload = root_response.json()
    if root_payload.get("status") != "ok":
        _fail(f"root endpoint returned unexpected payload: {root_payload!r}")

    health_response = _send_request(base_url, HEALTH_PATH)
    _assert_status(health_response, 200, context="health check")
    ready_response = _send_request(base_url, READY_PATH)
    _assert_status(ready_response, 200, context="readiness check")
    ready_payload = ready_response.json()
    if ready_payload.get("status") != "ready":
        _fail(f"readiness endpoint returned unexpected payload: {ready_payload!r}")
    checks = ready_payload.get("checks", {})
    if checks.get("database", {}).get("healthy") is not True:
        _fail(f"database readiness failed: {checks!r}")
    if checks.get("auth", {}).get("healthy") is not True:
        _fail(f"auth readiness failed: {checks!r}")

    _info("Checking database CRUD through a live verification route")
    db_response = _send_request(base_url, "/__verify/db")
    _assert_status(db_response, 200, context="database verification route")
    db_payload = db_response.json()
    if db_payload.get("status") != "ok" or not db_payload.get("widget_id"):
        _fail(f"database verification route returned unexpected payload: {db_payload!r}")

    _info("Checking authentication and authorization flows")
    unauthorized_response = _send_request(base_url, "/api/v1/me")
    _assert_status(unauthorized_response, 401, context="unauthorized /api/v1/me")

    me_response = _send_request(
        base_url,
        "/api/v1/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    _assert_status(me_response, 200, context="authorized /api/v1/me")
    me_payload = me_response.json()
    if me_payload.get("subject") != "verification-admin":
        _fail(f"/api/v1/me returned unexpected payload: {me_payload!r}")

    reports_response = _send_request(
        base_url,
        "/api/v1/reports",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    _assert_status(reports_response, 200, context="authorized /api/v1/reports")

    forbidden_response = _send_request(
        base_url,
        "/api/v1/admin",
        headers={"Authorization": f"Bearer {reports_only_token}"},
    )
    _assert_status(forbidden_response, 403, context="forbidden /api/v1/admin")

    admin_response = _send_request(
        base_url,
        "/api/v1/admin",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    _assert_status(admin_response, 200, context="authorized /api/v1/admin")

    _info("Checking metrics exposure")
    metrics_response = _send_request(base_url, METRICS_PATH)
    _assert_status(metrics_response, 200, context="metrics endpoint")
    _assert_contains(metrics_response.text, "fastapi_app_info", context="metrics payload")
    if HEALTH_PATH in metrics_response.text or READY_PATH in metrics_response.text:
        _fail("metrics payload unexpectedly included skipped health/readiness paths")

    _info("Checking structured error responses")
    validation_response = _send_request(
        base_url,
        "/__verify/validated",
        params={"count": 0},
    )
    _assert_status(validation_response, 422, context="validation error route")
    validation_payload = validation_response.json()
    if validation_payload.get("error") != "validation_error":
        _fail(f"validation error payload was not normalized: {validation_payload!r}")

    crash_response = _send_request(base_url, "/__verify/crash")
    _assert_status(crash_response, 500, context="unhandled exception route")
    crash_payload = crash_response.json()
    if crash_payload.get("error") != "internal_error":
        _fail(f"500 error payload was not sanitized: {crash_payload!r}")
    if "verification crash" in str(crash_payload.get("detail", "")):
        _fail(f"500 response leaked exception detail: {crash_payload!r}")

    if config.uses_redis:
        _info("Checking Redis-backed rate limiting")
        limited_headers = {"Authorization": f"Bearer {rate_limit_token}"}
        for _ in range(5):
            limited_response = _send_request(
                base_url,
                "/__verify/rate-limit",
                headers=limited_headers,
            )
            _assert_status(limited_response, 200, context="rate limit warm-up request")
        throttled_response = _send_request(
            base_url,
            "/__verify/rate-limit",
            headers=limited_headers,
        )
        _assert_status(throttled_response, 429, context="Redis-backed rate limit enforcement")

    _info("Checking trace export")
    _force_flush_traces()
    if not capture_state.received_event.wait(timeout=10):
        _fail("Did not receive any OTLP trace export requests")

    otlp_paths = {item["path"] for item in capture_state.requests}
    if "/v1/traces" not in otlp_paths:
        _fail(f"Trace exporter posted to unexpected paths: {sorted(otlp_paths)!r}")


def main() -> int:
    app_host = "127.0.0.1"
    capture_state = TraceCaptureState()
    verification_config = _load_verification_config()
    server: QuietUvicornServer | None = None
    server_thread: threading.Thread | None = None
    capture_server: TraceCaptureHTTPServer | None = None
    capture_thread: threading.Thread | None = None
    jwks_server: JWKSHTTPServer | None = None
    jwks_thread: threading.Thread | None = None
    previous_ssl_cert_file = os.environ.get("SSL_CERT_FILE")

    try:
        with TemporaryDirectory(prefix="fastapi-template-verify-") as temp_dir:
            temp_path = Path(temp_dir)
            database_path: Path | None = None
            jwks_url: str | None = None
            jwks_keys: JWKSKeyMaterial | None = None

            if verification_config.auth_mode == "jwks":
                jwks_keys = _generate_jwks_key_material()
                jwks_server, jwks_thread, jwks_url, cert_path = _start_jwks_server(
                    app_host,
                    temp_path,
                    jwks_keys,
                )
                os.environ["SSL_CERT_FILE"] = str(cert_path)

            capture_server, capture_thread = _start_trace_capture_server(app_host, capture_state)
            otlp_port = int(capture_server.server_address[1])

            if verification_config.uses_external_database:
                _info("Applying Alembic migrations to the configured external database")
                _run_migrations_for_url(verification_config.alembic_database_url or "")
            else:
                database_path = temp_path / "verification.db"
                _info("Applying Alembic migrations to the temporary database")
                _run_migrations(database_path)

            settings = _build_settings(
                verification_config,
                database_path=database_path,
                app_port=8000,
                otlp_port=otlp_port,
                jwks_url=jwks_url,
            )
            app = create_app(settings=settings)
            _attach_verification_routes(app)

            server, server_thread = _start_app_server(app, app_host)
            app_port = _get_uvicorn_port(server)
            _info(f"Starting verification app on http://{app_host}:{app_port}")

            _verify_live_stack(
                f"http://{app_host}:{app_port}",
                capture_state,
                verification_config,
                jwks_keys,
            )
            _info("All live verification checks passed")
            return 0
    except VerificationError as exc:
        print(f"[verify-stack] ERROR: {exc}")
        return 1
    finally:
        if server is not None and server_thread is not None:
            _stop_app_server(server, server_thread)
        if jwks_server is not None:
            jwks_server.shutdown()
            jwks_server.server_close()
        if jwks_thread is not None:
            jwks_thread.join(timeout=5)
        if capture_server is not None:
            capture_server.shutdown()
            capture_server.server_close()
        if capture_thread is not None:
            capture_thread.join(timeout=5)
        if previous_ssl_cert_file is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = previous_ssl_cert_file


if __name__ == "__main__":
    raise SystemExit(main())
