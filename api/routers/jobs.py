"""Read-only job listing endpoints - GET /jobs (paginated + filtered) and
GET /jobs/{id}.

This is the only place a JobModel row gets turned into the public JobOut
shape - see api/schemas.py's docstring for what's hidden/derived and why
(never description_original directly, rewritten_description falls back to
description_original only here, at serialization time - the stored
rewritten_description column itself is never touched by this API, since
this process never writes).

No is_external filter is applied below on purpose: pipeline/runner.py's
architecture rule is that a row with is_external=False is never persisted
in the first place (see CLAUDE.md's "external-link filter" section), so
every row in this table already satisfies is_external=True by
construction. is_active *does* need filtering here - health_check.py
flips it to False on a live schedule as apply links go dead, independent
of when a row was inserted.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import JobListOut, JobOut
from db.models import JobModel

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_job_out(job: JobModel) -> JobOut:
    return JobOut(
        id=job.id,
        source=job.source,
        title=job.title,
        company=job.company,
        location=job.location,
        is_remote=job.is_remote,
        employment_type=job.employment_type,
        seniority=job.seniority,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        salary_period=job.salary_period,
        salary_raw=job.salary_raw,
        has_salary=job.has_salary,
        description=job.rewritten_description or job.description_original,
        description_is_ai_rewritten=job.rewritten_description is not None,
        tags=job.tags,
        apply_type=job.apply_type,
        apply_url=job.apply_url or job.raw_apply_url,
        posted_at=job.posted_at,
        scraped_at=job.scraped_at,
        merged_sources=job.merged_sources,
    )


@router.get("", response_model=JobListOut)
async def list_jobs(
    session: AsyncSession = Depends(get_db),
    source: str | None = Query(default=None, description="Exact match, e.g. 'jobfound' or 'talentd'."),
    location: str | None = Query(default=None, description="Case-insensitive substring match."),
    employment_type: str | None = Query(default=None),
    seniority: str | None = Query(default=None),
    is_remote: bool | None = Query(default=None),
    has_salary: bool | None = Query(default=None),
    min_salary: int | None = Query(default=None, description="salary_min >= this value."),
    tag: str | None = Query(default=None, description="Row must have this exact tag in its tags array."),
    q: str | None = Query(default=None, description="Case-insensitive substring match on title or company."),
    include_inactive: bool = Query(
        default=False, description="Include jobs whose apply link failed health_check.py's check."
    ),
    sort: str = Query(default="posted_at", pattern="^(posted_at|scraped_at)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    stmt = select(JobModel)

    if not include_inactive:
        stmt = stmt.where(JobModel.is_active.is_(True))
    if source:
        stmt = stmt.where(JobModel.source == source)
    if location:
        stmt = stmt.where(JobModel.location.ilike(f"%{location}%"))
    if employment_type:
        stmt = stmt.where(JobModel.employment_type == employment_type)
    if seniority:
        stmt = stmt.where(JobModel.seniority == seniority)
    if is_remote is not None:
        stmt = stmt.where(JobModel.is_remote.is_(is_remote))
    if has_salary is not None:
        stmt = stmt.where(JobModel.has_salary.is_(has_salary))
    if min_salary is not None:
        stmt = stmt.where(JobModel.salary_min.is_not(None), JobModel.salary_min >= min_salary)
    if tag:
        stmt = stmt.where(JobModel.tags.contains([tag]))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(JobModel.title.ilike(like) | JobModel.company.ilike(like))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    sort_col = JobModel.posted_at if sort == "posted_at" else JobModel.scraped_at
    sort_col = sort_col.desc().nullslast() if order == "desc" else sort_col.asc().nullsfirst()
    stmt = stmt.order_by(sort_col).offset(offset).limit(limit)

    rows = (await session.execute(stmt)).scalars().all()
    return JobListOut(items=[_to_job_out(job) for job in rows], total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_db)) -> JobOut:
    job = await session.get(JobModel, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_job_out(job)
