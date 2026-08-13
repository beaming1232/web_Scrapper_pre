"""
Throwaway diagnostic script — NOT part of the deliverable.

Runs the real pipeline stages (fetch -> parse -> normalize -> validate ->
filter_external -> resolve_url -> revalidate) against the live talentd.in
site, stopping just short of the DB-write step (since no Postgres is set
up yet). Dumps whatever WOULD have been stored to a JSON file so it can be
eyeballed before wiring up the database.

Writes to scraper_output_talentd.json (deliberately distinct from
scraper_output.json, jobfound's own preview artifact) so the two don't
clobber each other.
"""
import asyncio
import json
import logging
from datetime import datetime

from pipeline.filter import apply_external_filter, revalidate_after_resolution
from pipeline.resolver import UrlResolver
from pipeline.runner import _finalize_job, _resolve_urls
from scrapers.sources.talentd import TalentdSource

logging.basicConfig(level=logging.WARNING)


def _default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


async def main():
    source = TalentdSource()  # default: last 24h, no fixed page count

    raw_pages = await source.fetch()
    print(f"[fetch]      detail pages fetched (posted within {source.max_job_age_hours}h): {len(raw_pages)}")

    raw_records = source.parse(raw_pages)
    print(f"[parse]      India records found:  {len(raw_records)}")

    finalized = []
    dropped_invalid = 0
    for r in raw_records:
        normalized = source.normalize(r)
        job = _finalize_job(normalized, source.source_name)
        if job is None:
            dropped_invalid += 1
            continue
        finalized.append(job)
    print(f"[normalize]  valid canonical jobs:  {len(finalized)}  (dropped_invalid={dropped_invalid})")

    externally_applyable = apply_external_filter(finalized)
    print(f"[filter #1]  external (pre-resolution): {len(externally_applyable)}")

    resolver = UrlResolver()
    resolved = await _resolve_urls(externally_applyable, resolver)

    revalidated = revalidate_after_resolution(resolved)
    final_jobs = [j for j in revalidated if j.is_external]
    downgraded = len(revalidated) - len(final_jobs)
    print(f"[filter #2]  downgraded post-resolution: {downgraded}")
    print(f"[FINAL]      jobs that would be stored: {len(final_jobs)}")

    output = [j.model_dump() for j in final_jobs]
    with open("scraper_output_talentd.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=_default, ensure_ascii=False)
    print("\nwrote scraper_output_talentd.json")


if __name__ == "__main__":
    asyncio.run(main())
