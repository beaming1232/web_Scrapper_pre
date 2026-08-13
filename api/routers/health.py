"""Liveness/readiness endpoint - confirms the process is up and can reach
Postgres, nothing more."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(session: AsyncSession = Depends(get_db)) -> HealthOut:
    await session.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="connected")
