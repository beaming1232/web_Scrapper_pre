"""FastAPI app: the read-only HTTP layer the frontend talks to.

Deliberately separate from pipeline/runner.py - this process only reads
(sharing db/session.py's async engine/session factory in read-only
fashion via api/deps.py::get_db); nothing in this package ever scrapes,
rewrites, or writes to Postgres.

Run locally:
    ./.venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000

Then:
    http://127.0.0.1:8000/health        liveness + DB connectivity check
    http://127.0.0.1:8000/jobs          paginated/filtered job listings
    http://127.0.0.1:8000/jobs/{id}     single job
    http://127.0.0.1:8000/docs          interactive OpenAPI docs (auto-generated)

CORS is wide open (settings.cors_origins defaults to "*") because this API
has no auth/cookies to protect - it's a public read-only endpoint over
already-public job listings. Tighten cors_origins in .env to the real
frontend origin(s) before deploying this publicly; "*" is a dev
convenience, not a production stance.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, jobs, social
from config import settings
from db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


app = FastAPI(
    title="India Job Aggregator API",
    description="Read-only API serving scraped, AI-rewritten Indian job postings.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(social.router)
