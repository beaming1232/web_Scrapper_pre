"""
BaseSource: the abstract contract every job-source scraper must implement.

Design intent
-------------
Adding source #N to this system should mean: create one new file in
`scrapers/sources/`, subclass BaseSource, implement fetch/parse/normalize,
and nothing else changes. No core module should need to know a new source
exists — scrapers/registry.py discovers subclasses automatically.

A source is expected to be "messy": different sites expose different
subsets of fields, in different formats, with different reliability. The
contract below is built around that assumption:

- fetch() is the only method allowed to touch the network.
- parse() is pure — it turns raw fetched content into a list of loosely
  structured dicts ("raw records"), one per job posting found.
- normalize() is pure and MUST NOT raise on missing/malformed data. Every
  canonical field has a documented default (see db/models.py::JobSchema).
  If a field can't be extracted, normalize() sets it to that default and
  records the field's name in `source_fields_missing`.

Nothing here talks to the database or enforces the external-link-only
policy — those are pipeline concerns (see pipeline/filter.py), not scraper
concerns, so that every source implementation stays focused purely on
"how do I read this website".
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseSource(ABC):
    """Abstract base class for all job sources.

    Subclasses must set the class attributes below and implement
    fetch(), parse(), and normalize(). See scrapers/sources/.gitkeep's
    sibling files (added in later phases) for concrete examples.

    Class attributes
    -----------------
    source_name: str
        Unique, stable, lowercase identifier for this source (e.g. "naukri",
        "linkedin_in"). Used as the `source` field on every Job record and as
        the registry key, so it must never change once jobs have been scraped
        under it.
    requests_per_minute: int
        Max requests/minute this source allows. Enforced by the pipeline's
        rate limiter, not by the scraper itself.
    crawl_delay_seconds: float
        Minimum delay to leave between consecutive requests to this source.
        Enforced by the pipeline, not the scraper.
    """

    source_name: str
    requests_per_minute: int = 20
    crawl_delay_seconds: float = 1.0

    def __init__(self) -> None:
        if not getattr(self, "source_name", None):
            raise ValueError(
                f"{type(self).__name__} must define a non-empty `source_name` "
                "class attribute (unique, stable, lowercase)."
            )

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------
    @abstractmethod
    async def fetch(self) -> Any:
        """Retrieve raw content from the source.

        This is the only stage allowed to perform network I/O. It should
        return whatever raw payload(s) `parse()` needs — e.g. a list of
        HTML strings (one per listing page crawled), a list of JSON
        responses, etc. The concrete return type is source-specific and is
        only ever consumed by this same class's `parse()`.

        Implementations should use `httpx.AsyncClient` and respect
        `self.requests_per_minute` / `self.crawl_delay_seconds` for any
        internal pagination loops (the pipeline enforces delays between
        top-level calls, but a scraper that paginates internally is
        responsible for pacing its own follow-up requests).

        Must not raise for "this page had zero jobs" — return an empty
        result instead. Network/transport errors may propagate; the
        pipeline runner is responsible for catching and logging them per
        source so one broken source never blocks the others.
        """
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw: Any) -> list[dict]:
        """Turn raw fetched content into a list of raw record dicts.

        One dict per job posting found, in whatever shape is natural for
        this source (i.e. do NOT force-fit the canonical schema here —
        that's normalize()'s job). Keys are source-specific.

        Must be pure (no network/database access) and must never raise on
        a malformed/missing individual field within a listing — skip or
        null that field and keep going. It's fine to drop an entire
        listing here only if it is structurally unparseable (e.g. not a
        job posting at all).
        """
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw_record: dict) -> dict:
        """Convert one raw record into a canonical Job dict.

        Must return a dict compatible with `db.models.JobSchema`
        (see that module for the full field list and defaults).

        Hard rules:
        - Never raise because a field is missing. Missing = normal.
          Fall back to the field's documented default (None / False /
          empty list / "UNKNOWN" etc.) per db.models.JobSchema.
        - Populate `source_fields_missing` with the canonical field names
          this source could not extract for this record.
        - Only `title`, `company`, and `raw_apply_url` are truly required;
          if any of those three is unobtainable, the caller (pipeline
          runner) will drop the record rather than insert a broken one —
          but normalize() itself should still not raise; return the dict
          with those fields empty/None and let the pipeline decide.
        - Set `apply_type` (EXTERNAL | DIRECT | UNKNOWN) based on what this
          source tells you about the apply link. Do NOT set `is_external`
          — that's derived by pipeline/filter.py, not by the scraper.
        - Do NOT set `id`, `fingerprint`, or `scraped_at` — those are
          computed by the pipeline so the logic lives in exactly one place.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Optional convenience hook
    # ------------------------------------------------------------------
    async def run(self) -> list[dict]:
        """Convenience helper: fetch -> parse -> normalize each record.

        Sources generally never need to override this; it's provided so the
        pipeline runner (and quick manual testing of a single source) can
        call one method. Errors while normalizing a single raw record are
        swallowed with the record skipped, rather than aborting the whole
        source, so that one bad listing doesn't take down the batch.
        """
        raw = await self.fetch()
        raw_records = self.parse(raw)
        normalized: list[dict] = []
        for raw_record in raw_records:
            try:
                normalized.append(self.normalize(raw_record))
            except Exception:
                # A source's normalize() must not raise per the contract
                # above, but we guard here defensively so a bug in one
                # source can never take down the whole scrape run.
                #
                # Log it, though: a normalize() that raises on *every*
                # record is indistinguishable from "the site had nothing
                # new" in the run stats (both report fetched=0), which is
                # exactly how a real talentd breakage went unnoticed for a
                # day — see the employmentType-as-list handling in
                # scrapers/sources/talentd.py::normalize.
                logger.exception(
                    "%s.normalize() raised; skipping one record", type(self).__name__
                )
                continue
        return normalized
