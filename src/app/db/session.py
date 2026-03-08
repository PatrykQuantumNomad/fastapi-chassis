"""
FastAPI database session dependency helpers.
"""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .engine import session_scope


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the configured session factory from application state."""
    return cast("async_sessionmaker[AsyncSession]", request.app.state.db_session_factory)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped async database session."""
    async for session in session_scope(get_session_factory(request)):
        yield session
