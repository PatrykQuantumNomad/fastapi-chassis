"""
Database engine and session factory helpers.

This template is SQLite-first, so the helpers optimize the default
`sqlite+aiosqlite` path while still allowing explicit non-SQLite
configuration when the caller provides it.
"""

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..settings import Settings


def _ensure_sqlite_parent_exists(database_url: str) -> None:
    """Create the parent directory for the default file-backed SQLite URL."""
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return

    sqlite_path = database_url.removeprefix(prefix)
    if sqlite_path.startswith(":memory:"):
        return

    path = Path(sqlite_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the application's async engine, optimized for the default SQLite setup."""
    _ensure_sqlite_parent_exists(settings.database_url)

    connect_args: dict[str, int] = {}
    if settings.database_url.startswith("sqlite+aiosqlite://"):
        connect_args["timeout"] = settings.database_connect_timeout_seconds

    engine_kwargs: dict[str, object] = {
        "echo": settings.database_echo,
        "pool_pre_ping": settings.database_pool_pre_ping,
    }
    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    if not settings.database_url.startswith("sqlite+aiosqlite://"):
        engine_kwargs["pool_size"] = settings.database_pool_size
        engine_kwargs["max_overflow"] = settings.database_max_overflow

    return create_async_engine(settings.database_url, **engine_kwargs)


def create_session_factory(
    settings: Settings,
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory bound to the configured engine."""
    _ = settings
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped database session."""
    async with session_factory() as session:
        yield session
