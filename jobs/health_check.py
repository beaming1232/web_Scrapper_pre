"""
Cron entry point: link health checker.

Independent of the scrape cron (jobs/scrape_all.py) — this only ever
reads apply_url / is_active on already-stored jobs and issues HEAD
requests, it never scrapes a source.

Runs a HEAD request against every currently-active job's apply_url (or
raw_apply_url if apply_url was never resolved). On 404/410, or on any
connection error, the row's `is_active` is flipped to False. Any other
response (2xx/3xx, or a transient 5xx) leaves the row untouched — a
flaky server or a temporary block shouldn't get a job de-listed.

Run directly:
    python -m jobs.health_check
"""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select, update

from config import settings
from db.models import JobModel
from db.session import dispose_engine, get_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Status codes that mean "this listing is gone" -> deactivate.
_DEAD_STATUS_CODES = {404, 410}


async def _check_one(client: httpx.AsyncClient, job: JobModel) -> bool:
    """Return True if the job's link is confirmed dead and should be
    deactivated.
    """
    url = job.apply_url or job.raw_apply_url
    if not url:
        # Nothing to check - leave it alone rather than guessing.
        return False

    try:
        response = await client.head(url)
    except (httpx.TimeoutException, httpx.RequestError):
        return True

    return response.status_code in _DEAD_STATUS_CODES


async def main() -> None:
    deactivated = 0
    checked = 0

    async with get_session() as session:
        result = await session.execute(select(JobModel).where(JobModel.is_active.is_(True)))
        active_jobs = result.scalars().all()

        async with httpx.AsyncClient(
            timeout=settings.url_resolve_timeout_seconds,
            follow_redirects=True,
        ) as client:
            for job in active_jobs:
                checked += 1
                is_dead = await _check_one(client, job)
                if is_dead:
                    await session.execute(
                        update(JobModel).where(JobModel.id == job.id).values(is_active=False)
                    )
                    deactivated += 1
                await asyncio.sleep(settings.default_crawl_delay_seconds)

    logger.info("Health check complete: checked=%d deactivated=%d", checked, deactivated)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
