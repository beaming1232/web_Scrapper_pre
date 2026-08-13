"""
Cron entry point: run the full scrape pipeline for every registered source.

Run directly:
    python -m jobs.scrape_all

Or schedule with APScheduler (see config.settings.scrape_cron_schedule)
by importing `main` and adding it as a job:

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from config import settings
    from jobs.scrape_all import main

    scheduler = AsyncIOScheduler()
    scheduler.add_job(main, CronTrigger.from_crontab(settings.scrape_cron_schedule))
    scheduler.start()
"""
from __future__ import annotations

import asyncio
import logging

from db.session import dispose_engine
from pipeline.runner import run_all_sources

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    report = await run_all_sources()

    for stats in report.stats:
        if stats.error:
            logger.error("source=%s FAILED: %s", stats.source, stats.error)
            continue
        logger.info(
            "source=%s fetched=%d normalized=%d external_kept=%d "
            "downgraded_after_resolution=%d inserted=%d merged_duplicates=%d dropped_invalid=%d",
            stats.source,
            stats.fetched,
            stats.normalized,
            stats.external_kept,
            stats.downgraded_after_resolution,
            stats.inserted,
            stats.merged_duplicates,
            stats.dropped_invalid,
        )

    logger.info(
        "TOTAL inserted=%d merged=%d across %d sources",
        report.total_inserted,
        report.total_merged,
        len(report.stats),
    )

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
