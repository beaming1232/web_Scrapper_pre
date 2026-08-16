"""Public-facing Pydantic response models for the read-only jobs API.

Deliberately a separate shape from db.models.JobSchema/JobModel, not a
straight passthrough:

- `description_original` is never serialized directly - it's the
  copyrighted scraped text pipeline/rewriter.py exists specifically to
  avoid republishing verbatim (see that module's docstring). `description`
  below is *derived* at serialization time (api/routers/jobs.py) as
  `rewritten_description or description_original` - i.e. it shows the
  original only as a fallback when no AI rewrite exists yet (rewriting
  currently disabled via REWRITE_ENABLED=false during frontend
  development - see .env). `description_is_ai_rewritten` tells the
  frontend which case it's looking at, so it can e.g. show a "draft
  description" badge instead of silently presenting scraped text as
  finished copy.
- Internal-only fields are dropped entirely: `fingerprint` and
  `resolved_domain` are pipeline bookkeeping with no meaning to a
  frontend user; `external_id` is the source site's own internal ID.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: str
    source: str
    title: str
    company: str
    location: str | None = None
    is_remote: bool

    employment_type: str | None = None
    seniority: str | None = None

    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str
    salary_period: str | None = None
    salary_raw: str | None = None
    has_salary: bool

    description: str | None = Field(
        default=None,
        description="rewritten_description if an AI rewrite exists yet, else "
        "description_original as a fallback. Check description_is_ai_rewritten "
        "to tell which one this is.",
    )
    description_is_ai_rewritten: bool

    tags: list[str]

    apply_type: str
    apply_url: str = Field(description="Resolved apply URL if available, else raw_apply_url.")

    posted_at: datetime | None = None
    scraped_at: datetime

    merged_sources: list[str] = Field(
        default_factory=list,
        description="Other sources (beyond `source`) that also reported this same job.",
    )


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class HealthOut(BaseModel):
    status: str
    database: str


class SocialDigestOut(BaseModel):
    """One ready-to-post message, plus the numbers needed to judge it.

    Deliberately a single `message` rather than one field per platform: the
    same plain text is posted verbatim to X, WhatsApp and Telegram (see
    social/digest.py for why per-platform variants don't work).
    """

    message: str | None = Field(
        default=None,
        description="Post text, or null when no jobs were stored in the window - "
        "a quiet run is normal and 'no new jobs' isn't worth posting.",
    )
    job_count: int = Field(description="Jobs stored in the window.")
    listed_count: int = Field(
        description="How many are named in the message; the rest are '+N more'."
    )
    x_character_count: int = Field(
        description="Length as X counts it (URLs billed at 23 chars). Must be <= 280."
    )
    fits_x_limit: bool
    window_hours: float
    site_url: str
