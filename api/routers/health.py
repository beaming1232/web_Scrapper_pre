"""Liveness and readiness endpoints.

`/health` is Railway's `healthcheckPath` (see railway.json), which makes it a
**liveness** check: its only job is to answer "is this process alive?". It must
therefore never fail just because Postgres is momentarily unreachable.

That distinction is not academic - it is the cause of a real outage. The
original version of this module declared `session: AsyncSession = Depends(get_db)`
and ran `SELECT 1` unguarded. When Neon refused a connection, the failure
happened *inside the dependency*, before the handler body ever ran, so FastAPI
could not turn it into a graceful response and returned a bare 500:

    ConnectionRefusedError: [Errno 111] Connection refused
    INFO:  100.64.0.2:49239 - "GET /health HTTP/1.1" 500 Internal Server Error

Railway read that 500 as "the deployment is unhealthy", failed the deploy
inside `healthcheckTimeout`, burned its `restartPolicyMaxRetries`, and emailed
a crash notice - for a process that was perfectly alive and whose database came
back seconds later. Deploys that happened to land while Neon's compute was
scaled to zero died; deploys that didn't, survived. Hence "it crashes
sometimes".

So the two concerns are split:

- `GET /health`     liveness. Always 200 while the process is up. Still reports
                    the database state in its `database` field (so the response
                    stays informative and backwards-compatible), but reports it
                    as data rather than as an HTTP failure.
- `GET /health/db`  readiness. 503 when Postgres is unreachable. This is the one
                    to point real monitoring/alerting at - it is deliberately
                    NOT the endpoint that can tear the container down.

The probe is bounded by `health_db_probe_timeout_seconds` so that a hung
connection (as opposed to a refused one) also cannot stall the healthcheck
until Railway's window expires.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from api.schemas import HealthOut
from config import settings
from db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_CONNECTED = "connected"
_UNREACHABLE = "unreachable"


async def _probe_database() -> str:
    """Return `"connected"` or `"unreachable"`. Never raises.

    Deliberately swallows every exception: callers use the return value to
    describe the database, and a health endpoint that can itself throw is the
    bug this module exists to prevent. The failure is logged at WARNING with a
    traceback so a real outage is still visible in `railway logs`.
    """
    try:
        async with asyncio.timeout(settings.health_db_probe_timeout_seconds):
            async with get_session() as session:
                await session.execute(text("SELECT 1"))
    except Exception:
        logger.warning("health: database probe failed", exc_info=True)
        return _UNREACHABLE
    return _CONNECTED


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness check - 200 for as long as this process can serve a request.

    Used by Railway's healthcheck, so it must not fail on a database blip.
    """
    return HealthOut(status="ok", database=await _probe_database())


@router.get("/health/db", response_model=HealthOut)
async def health_db(response: Response) -> HealthOut:
    """Readiness check - 503 when Postgres is unreachable.

    Point monitoring here rather than at `/health`: this endpoint is allowed to
    report failure precisely because nothing restarts the container over it.
    """
    database = await _probe_database()
    if database != _CONNECTED:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="degraded", database=database)
    return HealthOut(status="ok", database=database)
