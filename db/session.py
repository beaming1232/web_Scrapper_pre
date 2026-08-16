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

def _asyncpg_connect_args() -> dict[str, float]:
    """asyncpg-specific timeouts, or `{}` for any other driver.

    Guarded on the driver name because these keyword arguments are asyncpg's
    own (`timeout`, `command_timeout`) - handing them to a different DBAPI
    (e.g. a sqlite URL in a test) raises on connect.

    Both bound how long a network problem can hang a caller: `timeout` caps
    establishing a connection (Neon scales compute to zero when idle, so a cold
    connect is slow), `command_timeout` caps a single statement.
    """
    if "+asyncpg" not in settings.database_url:
        return {}
    return {
        "timeout": settings.db_connect_timeout_seconds,
        "command_timeout": settings.db_command_timeout_seconds,
    }


_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # pool_pre_ping catches a connection that died while idle; pool_recycle
    # stops it going stale in the first place. Neon's pooled (-pooler) endpoint
    # closes idle server-side connections, so both matter here.
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_timeout=settings.db_pool_timeout_seconds,
    connect_args=_asyncpg_connect_args(),
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
