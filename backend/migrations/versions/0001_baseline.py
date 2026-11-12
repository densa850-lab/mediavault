"""Baseline: enable extensions the Phase 2+ schema relies on.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # citext gives case-insensitive emails for the users table (Phase 5).
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS citext")
