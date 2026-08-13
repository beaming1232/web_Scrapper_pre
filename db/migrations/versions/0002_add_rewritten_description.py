"""add rewritten_description column

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

Adds db/models.py::JobModel.rewritten_description (Phase 2: AI-rewritten
job descriptions — see pipeline/rewriter.py). Nullable: a job can have
description_original set but no rewrite yet (rewriting disabled/failed),
or no description at all.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("rewritten_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "rewritten_description")
