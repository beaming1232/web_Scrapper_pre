"""
External-apply-link filter.

Policy: this platform only ever stores jobs that send applicants to the
hiring company's own external site/ATS. Jobs whose apply flow stays
in-platform (DIRECT) or whose apply type couldn't be determined (UNKNOWN)
are discarded entirely. Jobs whose apply link *resolves* (after following
redirects) to another job board rather than a company's own page are
downgraded the same way, even if a scraper's pre-resolution classification
couldn't have known that.

This is a pipeline-stage concern, not a scraper concern: scrapers only
*classify* `apply_type` from what they can see pre-resolution (they know
their own site's link markup, not where a tracker link ultimately lands);
this module is what actually enforces the "external only" rule, in
exactly one place, applied identically to every source. It runs in two
passes because of that same pre/post-resolution split:

1. `apply_external_filter` — right after normalize(), using only the
   scraper-supplied `apply_type`. Per pipeline/runner.py's fixed stage
   order (filter_external -> resolve_url), `resolved_domain` does not
   exist yet at this point.
2. `revalidate_after_resolution` — right after pipeline/resolver.py has
   populated `resolved_domain`, catching the case a scraper couldn't:
   a link that *looked* like a plain external URL pre-resolution but
   whose redirect chain actually lands on a known aggregator domain (or
   back on the source's own site).
"""
from __future__ import annotations

from db.models import ApplyType, JobSchema

# Domains that are themselves job boards/aggregators rather than a hiring
# company's own page or ATS. Deliberately general (not tied to any one
# source) since any source's apply link can end up resolving to one of
# these after redirects — e.g. a tracker link that bounces through an
# aggregator instead of landing on the company's own careers page.
KNOWN_AGGREGATOR_DOMAINS = frozenset(
    {
        "linkedin.com",
        "indeed.com",
        "indeed.co.in",
        "naukri.com",
        "monster.com",
        "monsterindia.com",
        "shine.com",
        "timesjobs.com",
        "foundit.in",
        "instahyre.com",
        "cutshort.io",
        "wellfound.com",
        "angel.co",
        "internshala.com",
        "ziprecruiter.com",
        "simplyhired.com",
        "glassdoor.com",
        "glassdoor.co.in",
        "ambitionbox.com",
    }
)


def is_aggregator_domain(domain: str | None) -> bool:
    """True if `domain` (or any subdomain of it) is a known job-board
    aggregator rather than a hiring company's own page.
    """
    if not domain:
        return False
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[len("www."):]
    return any(domain == d or domain.endswith("." + d) for d in KNOWN_AGGREGATOR_DOMAINS)


def is_external_job(job: JobSchema) -> bool:
    """Return True if this job's apply link is classified EXTERNAL.

    UNKNOWN and DIRECT are both treated as "not external" — when in
    doubt, we drop the job rather than risk surfacing an in-platform
    apply flow.
    """
    apply_type = job.apply_type
    # JobSchema stores enums as their .value (use_enum_values=True), so
    # apply_type may already be a plain str here.
    value = apply_type.value if isinstance(apply_type, ApplyType) else apply_type
    return value == ApplyType.EXTERNAL.value


def apply_external_filter(jobs: list[JobSchema]) -> list[JobSchema]:
    """Filter a batch of normalized jobs down to only externally-applyable
    ones, and stamp `is_external=True` on the survivors.

    This is the first of the two `filter_external` passes described in
    the module docstring — pre-resolution, using only `apply_type`. Jobs
    that fail the check are dropped silently here; the runner is
    responsible for logging counts if desired.
    """
    kept: list[JobSchema] = []
    for job in jobs:
        if is_external_job(job):
            kept.append(job.model_copy(update={"is_external": True}))
    return kept


def revalidate_after_resolution(jobs: list[JobSchema]) -> list[JobSchema]:
    """Second pass: re-check `is_external` now that `resolved_domain` is
    populated (must run after pipeline/resolver.py's resolve stage).

    Downgrades `is_external` to False for any job whose apply link's
    *final* destination turns out to be a known aggregator domain — a
    case a scraper's pre-resolution `apply_type` classification cannot
    catch on its own, since the raw URL alone (e.g. a tracker link) may
    give no hint of where it ultimately lands.

    Jobs that failed to resolve (`resolved_domain is None`, e.g. timeout)
    are left as-is: an unresolved URL is not evidence of anything, so we
    don't punish it — `apply_external_filter`'s pre-resolution
    `apply_type` classification is still the operative signal for those.
    """
    revalidated: list[JobSchema] = []
    for job in jobs:
        if job.is_external and is_aggregator_domain(job.resolved_domain):
            job = job.model_copy(update={"is_external": False})
        revalidated.append(job)
    return revalidated
