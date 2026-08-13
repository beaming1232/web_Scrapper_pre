"""create jobs table

Revision ID: 0001
Revises:
Create Date: 2026-08-07

Hand-written to match db/models.py::JobModel exactly. Future schema
changes should be generated with `alembic revision --autogenerate -m "..."`
against a running Postgres instance, then reviewed before committing.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        # --- identity ---------------------------------------------------
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False, server_default=""),
        # --- required core fields ---------------------------------------
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        # --- location / work mode ----------------------------------------
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("is_remote", sa.Boolean(), nullable=False, server_default=sa.false()),
        # --- classification ------------------------------------------------
        sa.Column("employment_type", sa.String(length=32), nullable=True),
        sa.Column("seniority", sa.String(length=32), nullable=True),
        # --- salary ----------------------------------------------------------
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("salary_period", sa.String(length=16), nullable=True),
        sa.Column("salary_raw", sa.Text(), nullable=True),
        sa.Column("has_salary", sa.Boolean(), nullable=False, server_default=sa.false()),
        # --- description ---------------------------------------------------------
        sa.Column("description_original", sa.Text(), nullable=True),
        sa.Column("description_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        # --- misc ------------------------------------------------------------------
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        # --- apply link ----------------------------------------------------------------
        sa.Column("apply_type", sa.String(length=16), nullable=False, server_default="UNKNOWN"),
        sa.Column("raw_apply_url", sa.Text(), nullable=False),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("resolved_domain", sa.String(length=256), nullable=True),
        sa.Column("is_external", sa.Boolean(), nullable=False, server_default=sa.false()),
        # --- timestamps / lifecycle -------------------------------------------------------
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        # --- dedup / data-quality -----------------------------------------------------------
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source_fields_missing",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "merged_sources",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
    )

    op.create_index("ix_jobs_source", "jobs", ["source"])
    op.create_index("ix_jobs_is_external", "jobs", ["is_external"])
    op.create_index("ix_jobs_is_active", "jobs", ["is_active"])
    op.create_index("ix_jobs_fingerprint", "jobs", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_jobs_fingerprint", table_name="jobs")
    op.drop_index("ix_jobs_is_active", table_name="jobs")
    op.drop_index("ix_jobs_is_external", table_name="jobs")
    op.drop_index("ix_jobs_source", table_name="jobs")
    op.drop_table("jobs")
