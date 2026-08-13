"""
Canonical Job schema and its Postgres table.

This module holds two representations of the same data on purpose:

1. `JobSchema` (Pydantic) — the contract every scraper's normalize()
   output is validated against before it's allowed further into the
   pipeline. This is what "the canonical schema" means operationally.
2. `JobModel` (SQLAlchemy 2.0 ORM) — the Postgres table the pipeline
   writes validated jobs into.

Keeping both in one file is deliberate: the two must never drift apart,
and having them side by side makes that easy to verify at a glance. If
you add/rename/remove a field, you must update both classes together.

Only `title`, `company`, `source`, and the apply-link fields
(raw_apply_url required; apply_url/resolved_domain/is_external/apply_type
derived) are guaranteed. Every other field is optional and defaults to
None / False / empty list — never raise for a missing field.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ==========================================================================
# Pydantic canonical schema — validated output of BaseSource.normalize()
# (after the pipeline fills in id / fingerprint / scraped_at)
# ==========================================================================
class ApplyType(str, enum.Enum):
    """Classification of how a listing's apply link behaves."""

    EXTERNAL = "EXTERNAL"  # sends the applicant to the hiring company's own site/ATS
    DIRECT = "DIRECT"  # apply happens in-platform (on the source site itself)
    UNKNOWN = "UNKNOWN"  # source didn't give the scraper enough info to tell


class JobSchema(BaseModel):
    """Canonical job posting schema.

    Every scraper must normalize its source-specific data into this shape.
    Only `title`, `company`, `source`, and `raw_apply_url` are required;
    everything else defaults to None / False / empty list when a source
    doesn't provide it. Missing data is the expected case, not an error —
    nothing in this model should ever be a reason for normalize() to raise.
    """

    model_config = {"use_enum_values": True}

    # --- identity -------------------------------------------------------
    id: str = Field(..., description="Hash of source + external_id. Computed by the pipeline.")
    source: str = Field(..., description="Registry key of the scraper this job came from.")
    external_id: str = Field(
        default="", description="Source's own ID for this listing, if it has one."
    )

    # --- required core fields -------------------------------------------
    title: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)

    # --- location / work mode --------------------------------------------
    location: str | None = None
    is_remote: bool = False

    # --- classification ---------------------------------------------------
    employment_type: str | None = None  # full-time | part-time | contract | internship
    seniority: str | None = None  # fresher | junior | mid | senior | lead

    # --- salary -------------------------------------------------------------
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "INR"
    salary_period: str | None = None  # annual | monthly | hourly
    salary_raw: str | None = None
    has_salary: bool = False

    # --- description ---------------------------------------------------------
    description_original: str | None = None
    description_available: bool = False
    # AI-rewritten version of description_original (pipeline/rewriter.py),
    # written once at insert time (never re-rewritten on a dedup merge).
    # None means "not yet rewritten" — either there was nothing to rewrite,
    # rewriting is disabled, or the DeepSeek call failed; safe to retry
    # later from a backfill job since nothing here is stateful beyond this
    # column.
    rewritten_description: str | None = None

    # --- misc ------------------------------------------------------------------
    tags: list[str] = Field(default_factory=list)

    # --- apply link ----------------------------------------------------------
    apply_type: ApplyType = ApplyType.UNKNOWN
    raw_apply_url: str = Field(..., min_length=1)
    apply_url: str | None = None
    resolved_domain: str | None = None
    is_external: bool = False  # HARD FILTER: only True records reach the public table

    # --- timestamps / lifecycle ------------------------------------------------
    posted_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

    # --- dedup / data-quality ----------------------------------------------------
    fingerprint: str = Field(
        ..., description="Hash of slugify(title)+slugify(company)+slugify(location or 'unknown')."
    )
    source_fields_missing: list[str] = Field(default_factory=list)


# ==========================================================================
# SQLAlchemy ORM model — the Postgres `jobs` table
# ==========================================================================
class Base(DeclarativeBase):
    pass


class JobModel(Base):
    """Postgres table storing every canonical job posting.

    Nullable per-column exactly matches JobSchema's optionality above:
    only title, company, source, and raw_apply_url are NOT NULL.
    """

    __tablename__ = "jobs"

    # --- identity ---------------------------------------------------------
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    # --- required core fields ----------------------------------------------
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)

    # --- location / work mode -----------------------------------------------
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- classification --------------------------------------------------------
    employment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- salary ------------------------------------------------------------------
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    salary_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    salary_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_salary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- description ---------------------------------------------------------------
    description_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rewritten_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- misc --------------------------------------------------------------------------
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # --- apply link ---------------------------------------------------------------------
    apply_type: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    raw_apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # --- timestamps / lifecycle -----------------------------------------------------------
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # --- dedup / data-quality ---------------------------------------------------------------
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_fields_missing: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Additional sources (beyond `source`, the original one) that have also
    # reported a job matching this row's fingerprint/URL. Populated by
    # pipeline/dedup.py when a duplicate is merged instead of inserted.
    merged_sources: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<JobModel id={self.id!r} source={self.source!r} title={self.title!r}>"
