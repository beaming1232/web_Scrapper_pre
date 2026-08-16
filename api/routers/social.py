"""GET /social/digest - the ready-to-post social message for recent jobs.

Read-only like the rest of `api/`: it selects recent rows and hands them to
social/digest.py, which does the formatting. Nothing here writes, and nothing
here posts to any platform - X and WhatsApp are copy-paste by necessity (X's
posting API is paid; WhatsApp has no community/broadcast API at all), so the
job of this endpoint is to produce text a human can copy.

The window is `scraped_at`-based rather than `posted_at`-based on purpose:
the question this answers is "what have we *added* since the last post", which
is about our own storage, not about when the employer published. `scraped_at`
is also updated by dedup when a job is re-seen, which is the behaviour we want
- a job merged again is not new and should not be announced twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import SocialDigestOut
from config import settings
from db.models import JobModel
from social.digest import X_CHARACTER_LIMIT, build_digest, x_length

router = APIRouter(prefix="/social", tags=["social"])


@router.get("/digest", response_model=SocialDigestOut)
async def social_digest(
    hours: float = Query(
        default=None,
        gt=0,
        le=720,
        description="How far back to look. Defaults to settings.social_digest_hours.",
    ),
    max_jobs: int = Query(
        default=None,
        ge=1,
        le=20,
        description="Most titles to name. Defaults to settings.social_digest_max_jobs.",
    ),
    session: AsyncSession = Depends(get_db),
) -> SocialDigestOut:
    window_hours = hours if hours is not None else settings.social_digest_hours
    limit = max_jobs if max_jobs is not None else settings.social_digest_max_jobs
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    result = await session.execute(
        select(JobModel)
        .where(JobModel.scraped_at >= cutoff, JobModel.is_active.is_(True))
        .order_by(JobModel.scraped_at.desc())
    )
    jobs = list(result.scalars().all())

    site_url = settings.site_base_url.rstrip("/")
    message = build_digest(jobs, site_url, max_jobs=limit)
    # Job lines are the only ones that start with a bullet, so counting them
    # is how many jobs are actually named (the rest fold into "+N more").
    listed = sum(1 for line in message.splitlines() if line.startswith("• ")) if message else 0

    return SocialDigestOut(
        message=message,
        job_count=len(jobs),
        listed_count=listed,
        x_character_count=x_length(message, site_url) if message else 0,
        fits_x_limit=(x_length(message, site_url) <= X_CHARACTER_LIMIT) if message else True,
        window_hours=window_hours,
        site_url=site_url,
    )
