"""Shared FastAPI dependencies."""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency wrapping db.session.get_session's context manager.

    Every request gets its own session, committed (a no-op for the
    read-only queries this API issues) or rolled back exactly like any
    other caller of get_session - no separate transaction-handling logic
    needed here.
    """
    async with get_session() as session:
        yield session
