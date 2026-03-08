"""Tests for the reusable HTTP probe script."""

from __future__ import annotations

import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from collections.abc import Generator


class _ProbeHandler(BaseHTTPRequestHandler):
    response_code = 200
    expected_host = ""
    seen_host = ""

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen_host = self.headers.get("Host", "")
        if self.path != "/ready":
            self.send_response(404)
            self.end_headers()
            return

        if type(self).expected_host and type(self).seen_host != type(self).expected_host:
            self.send_response(400)
            self.end_headers()
            return

        self.send_response(type(self).response_code)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


@pytest.fixture
def probe_server() -> Generator[tuple[ThreadingHTTPServer, str]]:
    _ProbeHandler.response_code = 200
    _ProbeHandler.expected_host = ""
    _ProbeHandler.seen_host = ""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = "127.0.0.1"
    port = server.server_port
    try:
        yield server, f"{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _probe_script() -> Path:
    return Path(__file__).resolve().parents[2] / "ops" / "http_probe.py"


def test_http_probe_succeeds_with_explicit_path_and_port(
    probe_server: tuple[ThreadingHTTPServer, str],
) -> None:
    _, address = probe_server
    host, port = address.split(":")
    result = subprocess.run(
        [
            sys.executable,
            str(_probe_script()),
            "--host",
            host,
            "--port",
            port,
            "--path",
            "/ready",
            "--path-env",
            "APP_READINESS_CHECK_PATH",
            "--default-path",
            "/ready",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_http_probe_supports_host_header_override(
    probe_server: tuple[ThreadingHTTPServer, str],
) -> None:
    _, address = probe_server
    host, port = address.split(":")
    _ProbeHandler.expected_host = "api.example.test"
    result = subprocess.run(
        [
            sys.executable,
            str(_probe_script()),
            "--host",
            host,
            "--host-header",
            "api.example.test",
            "--port",
            port,
            "--path",
            "/ready",
            "--path-env",
            "APP_READINESS_CHECK_PATH",
            "--default-path",
            "/ready",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert _ProbeHandler.seen_host == "api.example.test"


def test_http_probe_fails_when_status_does_not_match(
    probe_server: tuple[ThreadingHTTPServer, str],
) -> None:
    _, address = probe_server
    host, port = address.split(":")
    _ProbeHandler.response_code = 503
    result = subprocess.run(
        [
            sys.executable,
            str(_probe_script()),
            "--host",
            host,
            "--port",
            port,
            "--path",
            "/ready",
            "--path-env",
            "APP_READINESS_CHECK_PATH",
            "--default-path",
            "/ready",
            "--expected-status",
            "200",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "expected status 200" in result.stderr
