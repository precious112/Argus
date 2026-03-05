"""Add dedup_key column to alert_history table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alert_history",
        sa.Column("dedup_key", sa.String(255), server_default="", nullable=False),
    )
    op.create_index("ix_alert_history_dedup_key", "alert_history", ["dedup_key"])


def downgrade() -> None:
    op.drop_index("ix_alert_history_dedup_key", table_name="alert_history")
    op.drop_column("alert_history", "dedup_key")
