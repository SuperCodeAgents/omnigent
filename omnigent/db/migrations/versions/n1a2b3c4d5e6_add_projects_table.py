"""add projects table

Revision ID: n1a2b3c4d5e6
Revises: m1a2b3c4d5e6
Create Date: 2026-06-15 00:00:00.000000

Adds the ``projects`` table: per-user named projects pinning a default
workspace and default agent/harness/model for new sessions. One row per
``(owner, name)``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n1a2b3c4d5e6"
down_revision: str | None = "m1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``projects`` table."""
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner", sa.String(length=256), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("workspace", sa.String(length=2048), nullable=False),
        sa.Column("agent", sa.String(length=512), nullable=True),
        sa.Column("harness", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner", "name", name="uq_projects_owner_name"),
    )
    op.create_index("ix_projects_owner", "projects", ["owner"], unique=False)


def downgrade() -> None:
    """Drop the ``projects`` table."""
    op.drop_index("ix_projects_owner", table_name="projects")
    op.drop_table("projects")
