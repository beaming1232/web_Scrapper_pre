"""Tests for api/routers/health.py.

These exist because of a real production incident, not for coverage: `/health`
is Railway's `healthcheckPath`, so a 500 from it fails the deploy and takes the
container down. The original implementation took an `AsyncSession` via
`Depends(get_db)` and ran `SELECT 1` unguarded, so a refused Neon connection
raised inside the dependency and FastAPI returned a bare 500. Railway read that
as "unhealthy" and emailed a crash notice for a process that was fine.

The load-bearing assertion in this file is therefore
`test_health_returns_200_when_database_is_unreachable` - if that ever goes red,
intermittent deploy crashes are back.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import health as health_module


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class _FakeSession:
    """Minimal stand-in for AsyncSession - health only ever calls execute()."""

    async def execute(self, *_args, **_kwargs) -> None:
        return None


@asynccontextmanager
async def _reachable_session():
    yield _FakeSession()


@asynccontextmanager
async def _refused_session():
    # Mirrors what asyncpg actually raised in production against Neon:
    # ConnectionRefusedError: [Errno 111] Connection refused
    raise ConnectionRefusedError(111, "Connection refused")
    yield  # pragma: no cover - unreachable, keeps this a valid generator


@asynccontextmanager
async def _hanging_session():
    await asyncio.sleep(3600)
    yield _FakeSession()  # pragma: no cover - never reached


def test_health_returns_200_and_connected_when_database_is_up(client, monkeypatch):
    monkeypatch.setattr(health_module, "get_session", _reachable_session)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_returns_200_when_database_is_unreachable(client, monkeypatch):
    """The regression guard: a dead database must not fail the healthcheck.

    Railway restarts the container on a failing healthcheck, so returning 500
    here turns a transient Neon blip into a crashed deployment.
    """
    monkeypatch.setattr(health_module, "get_session", _refused_session)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "unreachable"}


def test_health_reports_unreachable_rather_than_hanging(client, monkeypatch):
    """A hung connection must be bounded, not merely a refused one.

    A connect that never returns would otherwise stall the healthcheck until
    Railway's healthcheckTimeout expired - failing the deploy just as surely as
    a 500 would.
    """
    monkeypatch.setattr(health_module, "get_session", _hanging_session)
    monkeypatch.setattr(
        health_module.settings, "health_db_probe_timeout_seconds", 0.05
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "unreachable"


def test_health_db_returns_200_when_database_is_up(client, monkeypatch):
    monkeypatch.setattr(health_module, "get_session", _reachable_session)

    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_db_returns_503_when_database_is_unreachable(client, monkeypatch):
    """Readiness is allowed to fail - it's the endpoint nothing restarts on."""
    monkeypatch.setattr(health_module, "get_session", _refused_session)

    response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
