"""
Async database session management.

Single source of truth for the SQLAlchemy async engine and session
factory. Everything else (pipeline, jobs/*.py cron scripts) imports
`get_session` rather than constructing its own engine.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)

_session_factory = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,
    autoflush=False,
)


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine."""
    return _engine


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession as a context manager, committing on success and
    rolling back on error.

    Usage:
        async with get_session() as session:
            session.add(obj)
    """
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Dispose the engine's connection pool. Call on graceful shutdown."""
    await _engine.dispose()
