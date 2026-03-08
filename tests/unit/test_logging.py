"""
Unit tests for logging filters and bootstrap configuration.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging
from typing import Any, cast

import pytest

from app.log_config.filters import RequestContextFilter, SuppressEndpointFilter
from app.logging_setup import configure_root_logging
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


class TestSuppressEndpointFilter:
    """Tests for the access-log suppression filter."""

    def _make_record(self, message: str) -> logging.LogRecord:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        return record

    def test_suppresses_matching_endpoint(self) -> None:
        f = SuppressEndpointFilter(["/healthcheck", "/metrics"])
        record = self._make_record("GET /healthcheck HTTP/1.1 200")
        assert f.filter(record) is False

    def test_suppresses_metrics(self) -> None:
        f = SuppressEndpointFilter(["/healthcheck", "/metrics"])
        record = self._make_record("GET /metrics HTTP/1.1 200")
        assert f.filter(record) is False

    def test_allows_non_matching_endpoint(self) -> None:
        f = SuppressEndpointFilter(["/healthcheck", "/metrics"])
        record = self._make_record("GET /api/users HTTP/1.1 200")
        assert f.filter(record) is True

    def test_empty_endpoint_list_allows_all(self) -> None:
        f = SuppressEndpointFilter([])
        record = self._make_record("GET /healthcheck HTTP/1.1 200")
        assert f.filter(record) is True

    def test_partial_match_suppresses(self) -> None:
        """Filter uses 'in' matching — /healthcheck/detailed would also be suppressed."""
        f = SuppressEndpointFilter(["/healthcheck"])
        record = self._make_record("GET /healthcheck/detailed HTTP/1.1 200")
        assert f.filter(record) is False


class TestRequestContextFilter:
    """Tests for injecting request-scoped context into log records."""

    def test_injects_default_request_id_when_absent(self) -> None:
        f = RequestContextFilter()
        record = logging.LogRecord(
            name="app",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        allowed = f.filter(record)
        assert allowed is True
        typed_record = cast("Any", record)
        assert typed_record.request_id == "-"
        assert typed_record.correlation_id == "-"


class TestConfigureRootLogging:
    """Tests for the root logger bootstrap function."""

    def test_text_format_uses_settings_template(self) -> None:
        settings = make_settings(
            log_format="text",
            log_text_template="[%(levelname)s] %(message)s",
            metrics_enabled=False,
        )
        configure_root_logging(settings)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert root.handlers[0].formatter._fmt == "[%(levelname)s] %(message)s"  # type: ignore[union-attr]

    def test_json_format_uses_json_formatter(self) -> None:
        from pythonjsonlogger.json import JsonFormatter

        settings = make_settings(
            log_format="json",
            metrics_enabled=False,
        )
        configure_root_logging(settings)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_clears_existing_handlers(self) -> None:
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        root.addHandler(logging.StreamHandler())
        initial_count = len(root.handlers)
        assert initial_count >= 2

        settings = make_settings(metrics_enabled=False)
        configure_root_logging(settings)
        assert len(root.handlers) == 1

    def test_sets_log_level(self) -> None:
        settings = make_settings(
            log_level="WARNING",
            metrics_enabled=False,
        )
        configure_root_logging(settings)
        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert root.handlers[0].level == logging.WARNING

    def test_adds_request_context_filter(self) -> None:
        settings = make_settings(metrics_enabled=False)
        configure_root_logging(settings)
        root = logging.getLogger()
        assert any(isinstance(f, RequestContextFilter) for f in root.handlers[0].filters)
