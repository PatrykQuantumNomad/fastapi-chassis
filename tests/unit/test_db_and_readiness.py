"""
Unit tests for database helpers and readiness registry.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.db.engine import (
    _ensure_sqlite_parent_exists,
    create_database_engine,
    create_session_factory,
)
from app.db.health import check_database_readiness
from app.db.session import get_db_session, get_session_factory
from app.readiness import ReadinessCheckResult, ReadinessRegistry
from tests.helpers import make_settings

pytestmark = pytest.mark.unit


class TestDatabaseEngine:
    """Tests for engine/session factory helpers."""

    def test_create_database_engine_supports_sqlite_file(self, tmp_path: Path) -> None:
        settings = make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/app.db")
        engine = create_database_engine(settings)
        session_factory = create_session_factory(settings, engine)

        assert engine is not None
        assert session_factory is not None

    def test_ensure_sqlite_parent_exists_skips_non_sqlite_url(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "missing"
        _ensure_sqlite_parent_exists(f"postgresql+asyncpg://user:pass@localhost/{target_dir.name}")
        assert target_dir.exists() is False

    def test_ensure_sqlite_parent_exists_skips_memory_database(self, tmp_path: Path) -> None:
        _ensure_sqlite_parent_exists("sqlite+aiosqlite:///:memory:")
        assert list(tmp_path.iterdir()) == []

    def test_create_database_engine_passes_pool_settings_for_non_sqlite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def fake_create_async_engine(url: str, **kwargs: object) -> object:
            captured["url"] = url
            captured["kwargs"] = kwargs
            return object()

        monkeypatch.setattr("app.db.engine.create_async_engine", fake_create_async_engine)
        settings = make_settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
            alembic_database_url="postgresql+psycopg://user:pass@localhost:5432/app",
            database_pool_size=7,
            database_max_overflow=11,
        )

        create_database_engine(settings)

        assert captured["url"] == settings.database_url
        assert captured["kwargs"] == {
            "echo": settings.database_echo,
            "pool_pre_ping": settings.database_pool_pre_ping,
            "pool_size": 7,
            "max_overflow": 11,
        }

    @pytest.mark.asyncio
    async def test_get_db_session_yields_session(self, tmp_path: Path) -> None:
        settings = make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/session.db")
        engine = create_database_engine(settings)
        session_factory = create_session_factory(settings, engine)
        app = FastAPI()
        app.state.db_session_factory = session_factory
        request = Request(
            {
                "type": "http",
                "app": app,
                "headers": [],
                "query_string": b"",
                "method": "GET",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "client": ("127.0.0.1", 1234),
                "server": ("test", 80),
                "root_path": "",
                "http_version": "1.1",
                "asgi": {"version": "3.0"},
            }
        )

        try:
            session = None
            async for yielded_session in get_db_session(request):
                session = yielded_session
                break
            assert session is not None
            assert get_session_factory(request) is session_factory
        finally:
            await engine.dispose()


class TestReadinessRegistry:
    """Tests for the readiness registry."""

    @pytest.mark.asyncio
    async def test_registry_runs_checks_and_serializes_results(self) -> None:
        registry = ReadinessRegistry()
        registry.register("application", lambda app: _healthy(app))
        results = await registry.run(FastAPI())

        assert len(results) == 1
        assert results[0].as_payload()["healthy"] is True

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_list(self) -> None:
        registry = ReadinessRegistry()
        results = await registry.run(FastAPI())
        assert results == []

    @pytest.mark.asyncio
    async def test_register_replaces_check_with_same_name(self) -> None:
        registry = ReadinessRegistry()
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app", detail="first"))
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app", detail="replaced"))
        results = await registry.run(FastAPI())

        assert len(results) == 1
        assert results[0].detail == "replaced"

    @pytest.mark.asyncio
    async def test_registry_runs_sync_and_async_checks_together(self) -> None:
        async def async_check(app: FastAPI) -> ReadinessCheckResult:
            return ReadinessCheckResult.ok("async_dep")

        def sync_check(app: FastAPI) -> ReadinessCheckResult:
            return ReadinessCheckResult.ok("sync_dep")

        registry = ReadinessRegistry()
        registry.register("async_dep", async_check)
        registry.register("sync_dep", sync_check)
        results = await registry.run(FastAPI())

        assert len(results) == 2
        assert all(r.is_healthy for r in results)

    @pytest.mark.asyncio
    async def test_registry_auto_measures_latency(self) -> None:
        registry = ReadinessRegistry()
        registry.register("app", lambda _app: ReadinessCheckResult.ok("app"))
        results = await registry.run(FastAPI())

        assert results[0].latency_ms is not None
        assert results[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_registry_preserves_pre_set_latency(self) -> None:
        registry = ReadinessRegistry()
        registry.register(
            "app",
            lambda _app: ReadinessCheckResult.ok("app", latency_ms=42.0),
        )
        results = await registry.run(FastAPI())

        assert results[0].latency_ms == 42.0

    def test_result_ok_factory(self) -> None:
        result = ReadinessCheckResult.ok("test", detail="works")
        assert result.is_healthy is True
        assert result.name == "test"
        assert result.detail == "works"

    def test_result_error_factory(self) -> None:
        result = ReadinessCheckResult.error("test", "broken")
        assert result.is_healthy is False
        assert result.name == "test"
        assert result.detail == "broken"

    def test_as_payload_without_detail(self) -> None:
        result = ReadinessCheckResult.ok("test", detail="secret")
        payload = result.as_payload(include_detail=False)

        assert "detail" not in payload
        assert payload["healthy"] is True

    def test_as_payload_with_detail(self) -> None:
        result = ReadinessCheckResult.ok("test", detail="all good")
        payload = result.as_payload(include_detail=True)

        assert payload["detail"] == "all good"
        assert payload["healthy"] is True

    def test_as_payload_rounds_latency(self) -> None:
        result = ReadinessCheckResult.ok("test", latency_ms=1.23456)
        payload = result.as_payload()

        assert payload["latency_ms"] == 1.23

    @pytest.mark.asyncio
    async def test_database_readiness_is_healthy_after_startup(self, tmp_path: Path) -> None:
        settings = make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/ready.db")
        app = FastAPI()
        app.state.settings = settings
        app.state.db_engine = create_database_engine(settings)

        result = await check_database_readiness(app)

        await app.state.db_engine.dispose()
        assert result.is_healthy is True

    @pytest.mark.asyncio
    async def test_database_readiness_reports_missing_engine(self) -> None:
        app = FastAPI()
        app.state.settings = make_settings()
        app.state.db_engine = None

        result = await check_database_readiness(app)

        assert result.is_healthy is False
        assert "not initialized" in result.detail

    @pytest.mark.asyncio
    async def test_database_readiness_reports_timeout(self) -> None:
        class HangingConnection:
            async def __aenter__(self) -> "HangingConnection":
                await asyncio.sleep(0.05)
                return self

            async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            async def execute(self, _query: object) -> None:
                await asyncio.sleep(0.05)

        class HangingEngine:
            def connect(self) -> HangingConnection:
                return HangingConnection()

        app = FastAPI()
        app.state.settings = make_settings(database_health_timeout_seconds=1)
        app.state.db_engine = HangingEngine()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("app.db.health.asyncio.timeout", _instant_timeout)
            result = await check_database_readiness(app)

        assert result.is_healthy is False
        assert "Timed out" in result.detail

    @pytest.mark.asyncio
    async def test_database_readiness_reports_query_failure(self) -> None:
        class BrokenConnection:
            async def __aenter__(self) -> "BrokenConnection":
                return self

            async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            async def execute(self, _query: object) -> None:
                raise RuntimeError("db unavailable")

        class BrokenEngine:
            def connect(self) -> BrokenConnection:
                return BrokenConnection()

        app = FastAPI()
        app.state.settings = make_settings()
        app.state.db_engine = BrokenEngine()

        result = await check_database_readiness(app)

        assert result.is_healthy is False
        assert "db unavailable" in result.detail


def _healthy(app: FastAPI) -> ReadinessCheckResult:
    _ = app
    return ReadinessCheckResult.ok("application")


class _InstantTimeout:
    async def __aenter__(self) -> None:
        raise TimeoutError

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _instant_timeout(_seconds: float) -> _InstantTimeout:
    return _InstantTimeout()
