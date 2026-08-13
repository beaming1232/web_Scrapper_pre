"""
Pipeline orchestration: fetch -> parse -> normalize -> filter_external ->
resolve_url -> dedup -> store, run once per registered source.

This is the only place that wires the stages together. Individual stage
logic lives in its own module (filter.py, resolver.py, dedup.py) so each
can be tested and reasoned about independently.

Per-source isolation: if one source's fetch()/parse() raises, that
source's run is logged and skipped — it never aborts the other sources'
runs in the same batch.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import JobModel, JobSchema
from db.session import get_session
from pipeline.dedup import compute_fingerprint, compute_job_id, find_duplicate, merge_into_existing
from pipeline.filter import apply_external_filter, revalidate_after_resolution
from pipeline.resolver import UrlResolver, default_resolver
from pipeline.rewriter import DescriptionRewriter, default_rewriter
from scrapers.base import BaseSource
from scrapers.registry import all_sources

logger = logging.getLogger(__name__)


@dataclass
class SourceRunStats:
    source: str
    fetched: int = 0
    normalized: int = 0
    external_kept: int = 0
    downgraded_after_resolution: int = 0
    inserted: int = 0
    merged_duplicates: int = 0
    dropped_invalid: int = 0
    rewritten: int = 0
    error: str | None = None


@dataclass
class PipelineRunReport:
    stats: list[SourceRunStats] = field(default_factory=list)

    @property
    def total_inserted(self) -> int:
        return sum(s.inserted for s in self.stats)

    @property
    def total_merged(self) -> int:
        return sum(s.merged_duplicates for s in self.stats)


def _finalize_job(raw_job: dict, source: str) -> JobSchema | None:
    """Compute pipeline-owned fields (id, fingerprint, scraped_at) on top
    of a scraper's normalize() output, then validate against JobSchema.

    Returns None (and logs) if the record is missing a truly-required
    field (title/company/raw_apply_url) or otherwise fails validation —
    this is the one place a bad record gets dropped rather than crashing
    the batch.
    """
    raw_job = dict(raw_job)
    raw_job.setdefault("source", source)
    raw_job["scraped_at"] = datetime.now(timezone.utc)
    raw_job["fingerprint"] = compute_fingerprint(
        raw_job.get("title", ""), raw_job.get("company", ""), raw_job.get("location")
    )
    raw_job["id"] = compute_job_id(source, raw_job.get("external_id", ""))

    try:
        return JobSchema(**raw_job)
    except ValidationError as exc:
        logger.warning("Dropping invalid record from source=%s: %s", source, exc)
        return None


async def _resolve_urls(jobs: list[JobSchema], resolver: UrlResolver) -> list[JobSchema]:
    resolved_jobs: list[JobSchema] = []
    for job in jobs:
        resolved = await resolver.resolve(job.raw_apply_url)
        resolved_jobs.append(
            job.model_copy(
                update={
                    "apply_url": resolved.apply_url,
                    "resolved_domain": resolved.resolved_domain,
                }
            )
        )
    return resolved_jobs


async def _store(
    session: AsyncSession,
    job: JobSchema,
    stats: SourceRunStats,
    rewriter: DescriptionRewriter,
) -> None:
    existing = await find_duplicate(session, job)
    if existing is not None:
        merge_into_existing(existing, job)
        stats.merged_duplicates += 1
        return

    # AI-rewrite only on the way to a genuine insert, never for a job that
    # turns out to be a duplicate above — the existing row already has
    # (or will already have) its own rewritten_description, so rewriting
    # here again would just burn API calls for nothing. See
    # pipeline/rewriter.py's module docstring for the full rationale.
    rewritten_description = await rewriter.rewrite(job.description_original)
    if rewritten_description is not None:
        job = job.model_copy(update={"rewritten_description": rewritten_description})
        stats.rewritten += 1

    # JobSchema.model_config sets use_enum_values=True, so apply_type is
    # already a plain str here — model_dump() maps 1:1 onto JobModel's
    # columns (merged_sources is new-row-default and not part of JobSchema).
    session.add(JobModel(**job.model_dump()))
    stats.inserted += 1


async def run_source(
    source_cls: type[BaseSource],
    resolver: UrlResolver | None = None,
    rewriter: DescriptionRewriter | None = None,
) -> SourceRunStats:
    """Run the full pipeline for a single source class."""
    source = source_cls()
    stats = SourceRunStats(source=source.source_name)
    resolver = resolver or default_resolver
    rewriter = rewriter or default_rewriter

    try:
        raw_records = await source.run()
    except Exception as exc:  # noqa: BLE001 - isolate one source's failure
        logger.exception("Source %s failed during fetch/parse/normalize", source.source_name)
        stats.error = str(exc)
        return stats

    stats.fetched = len(raw_records)

    finalized: list[JobSchema] = []
    for raw_job in raw_records:
        job = _finalize_job(raw_job, source.source_name)
        if job is None:
            stats.dropped_invalid += 1
            continue
        finalized.append(job)
    stats.normalized = len(finalized)

    externally_applyable = apply_external_filter(finalized)
    stats.external_kept = len(externally_applyable)

    resolved = await _resolve_urls(externally_applyable, resolver)
    # Second filter pass: resolved_domain only exists now, so this is the
    # first point a redirect-revealed aggregator domain can be caught
    # (see pipeline/filter.py's module docstring for why this can't happen
    # in the pre-resolution apply_external_filter pass above). Anything
    # downgraded here must be dropped, not merely flagged — architecture
    # rule 5 is "if is_external is False, discard the job entirely", the
    # same as the first pass.
    revalidated = revalidate_after_resolution(resolved)
    resolved = [job for job in revalidated if job.is_external]
    stats.downgraded_after_resolution = len(revalidated) - len(resolved)

    async with get_session() as session:
        for job in resolved:
            await _store(session, job, stats, rewriter)

    return stats


async def run_all_sources(
    source_names: list[str] | None = None,
    concurrency: int = 3,
) -> PipelineRunReport:
    """Run the pipeline for every registered source (or a subset), with a
    small concurrency limit so we don't hammer every site's rate limit
    boundary at once. Each source still separately honors its own
    requests_per_minute/crawl_delay_seconds inside fetch().
    """
    sources = all_sources()
    if source_names:
        sources = {name: cls for name, cls in sources.items() if name in source_names}

    semaphore = asyncio.Semaphore(concurrency)

    async def _run_with_limit(source_cls: type[BaseSource]) -> SourceRunStats:
        async with semaphore:
            return await run_source(source_cls)

    results = await asyncio.gather(*(_run_with_limit(cls) for cls in sources.values()))
    return PipelineRunReport(stats=list(results))
