"""Refresh-token concurrency grace: successor link + derivation nonce.

Revision ID: 0003_refresh_grace
Revises: 0002_auth
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_refresh_grace"
down_revision: str | None = "0002_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("refresh_tokens", sa.Column("successor_nonce", sa.LargeBinary(32), nullable=True))
    op.create_foreign_key(
        "fk_refresh_tokens_replaced_by_id_refresh_tokens",
        "refresh_tokens",
        "refresh_tokens",
        ["replaced_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_refresh_tokens_replaced_by_id_refresh_tokens", "refresh_tokens", type_="foreignkey"
    )
    op.drop_column("refresh_tokens", "successor_nonce")
    op.drop_column("refresh_tokens", "replaced_by_id")
