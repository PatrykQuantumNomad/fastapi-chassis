"""
Unit tests for tracing helpers.
"""

from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from app.observability import tracing
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


class TestTracingHelpers:
    """Tests for tracing setup helpers."""

    def test_instrument_fastapi_app_is_noop_when_disabled(self) -> None:
        app = FastAPI()
        settings = make_settings(otel_enabled=False)
        tracing.instrument_fastapi_app(app, settings)
        assert not hasattr(app, "_is_instrumented")

    def test_parse_headers_handles_empty_input(self) -> None:
        assert tracing._parse_headers("") == {}

    def test_parse_headers_parses_multiple_entries(self) -> None:
        assert tracing._parse_headers("Authorization=Bearer token,X-Key=value") == {
            "Authorization": "Bearer token",
            "X-Key": "value",
        }

    def test_configure_tracing_is_noop_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        typed_tracing: Any = tracing
        monkeypatch.setattr(typed_tracing, "_provider_configured", False)
        monkeypatch.setattr(typed_tracing, "_httpx_instrumented", False)
        set_provider = Mock()
        monkeypatch.setattr(typed_tracing.trace, "set_tracer_provider", set_provider)

        tracing.configure_tracing(make_settings(otel_enabled=False))

        set_provider.assert_not_called()

    def test_configure_tracing_sets_provider_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        typed_tracing: Any = tracing
        monkeypatch.setattr(typed_tracing, "_provider_configured", False)
        monkeypatch.setattr(typed_tracing, "_httpx_instrumented", False)
        set_provider = Mock()
        httpx_instrument = Mock()
        monkeypatch.setattr(typed_tracing.trace, "set_tracer_provider", set_provider)
        monkeypatch.setattr(
            typed_tracing.HTTPXClientInstrumentor,
            "instrument",
            httpx_instrument,
        )

        settings = make_settings(
            otel_enabled=True,
            otel_exporter_otlp_headers="Authorization=Bearer token",
        )
        tracing.configure_tracing(settings)

        set_provider.assert_called_once()
        httpx_instrument.assert_called_once()
        assert typed_tracing._provider_configured is True
        assert typed_tracing._httpx_instrumented is True

    def test_instrument_fastapi_app_calls_instrumentor_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        typed_tracing: Any = tracing
        instrument_app = Mock()
        monkeypatch.setattr(typed_tracing.FastAPIInstrumentor, "instrument_app", instrument_app)
        app = FastAPI()
        settings = make_settings(otel_enabled=True)

        tracing.instrument_fastapi_app(app, settings)

        instrument_app.assert_called_once()

    @pytest.mark.asyncio
    async def test_instrument_database_engine_calls_instrumentor_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        typed_tracing: Any = tracing
        instrument = Mock()
        monkeypatch.setattr(typed_tracing.SQLAlchemyInstrumentor, "instrument", instrument)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        try:
            tracing.instrument_database_engine(engine, make_settings(otel_enabled=True))
        finally:
            await engine.dispose()

        instrument.assert_called_once_with(engine=engine.sync_engine)
