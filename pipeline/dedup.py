"""
Deduplication: fingerprint identity + domain-based secondary matching, and
the merge logic applied when an incoming job turns out to already exist.

Two independent signals decide "is this the same job we already have":

1. PRIMARY — fingerprint: sha256 of
   slugify(title) + "|" + slugify(company) + "|" + slugify(location or "unknown")
   This is the main dedup key and is always available (title/company are
   required fields; location falls back to the literal string "unknown").

2. SECONDARY — resolved_domain + apply_url path: only usable when the
   pipeline's URL resolver (pipeline/resolver.py) succeeded, i.e.
   apply_url is not None. Two listings whose apply link resolves to the
   same domain + path are almost certainly the same posting even if the
   title/company text differs slightly across sources.

If either signal matches an existing row, the incoming job is treated as
a duplicate: we update `scraped_at` and add the incoming job's `source`
to `merged_sources` on the existing row, rather than inserting a new row.
"""
from __future__ import annotations

import hashlib

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yarl import URL

from db.models import JobModel, JobSchema


def compute_fingerprint(title: str, company: str, location: str | None) -> str:
    """Compute the dedup fingerprint for a job.

    slugify(title) + slugify(company) + slugify(location or "unknown"),
    hashed with sha256. Deterministic and stable across runs so the same
    posting always produces the same fingerprint regardless of source.
    """
    parts = [
        slugify(title or ""),
        slugify(company or ""),
        slugify(location or "unknown"),
    ]
    key = "|".join(parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def compute_job_id(source: str, external_id: str) -> str:
    """Compute the DB primary key: hash of source + external_id.

    Falls back to hashing just `source` + an empty external_id when a
    source doesn't expose a stable external ID — collisions in that case
    are expected and are exactly what the fingerprint-based dedup below
    is meant to catch instead.
    """
    key = f"{source}:{external_id or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _url_path_key(apply_url: str | None, resolved_domain: str | None) -> str | None:
    if not apply_url or not resolved_domain:
        return None
    path = URL(apply_url).path.rstrip("/")
    return f"{resolved_domain}{path}"


async def find_duplicate(session: AsyncSession, job: JobSchema) -> JobModel | None:
    """Look up an existing row that matches `job` via fingerprint (primary)
    or resolved_domain+path (secondary). Returns None if no duplicate.
    """
    stmt = select(JobModel).where(JobModel.fingerprint == job.fingerprint)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    url_key = _url_path_key(job.apply_url, job.resolved_domain)
    if url_key is None:
        return None

    # Secondary match: compare against all rows that have a resolved domain
    # matching this one, then check the path in Python (path comparison via
    # SQL would need a generated column; this dataset is small enough that
    # a domain-scoped scan is fine for phase 1).
    stmt = select(JobModel).where(JobModel.resolved_domain == job.resolved_domain)
    candidates = (await session.execute(stmt)).scalars().all()
    for candidate in candidates:
        if _url_path_key(candidate.apply_url, candidate.resolved_domain) == url_key:
            return candidate

    return None


def merge_into_existing(existing: JobModel, incoming: JobSchema) -> None:
    """Mutate `existing` in place to absorb a duplicate `incoming` job:
    bump scraped_at and record the incoming source in merged_sources,
    without touching any other field (the original row's data wins).
    """
    existing.scraped_at = incoming.scraped_at
    if incoming.source != existing.source and incoming.source not in existing.merged_sources:
        existing.merged_sources = [*existing.merged_sources, incoming.source]
