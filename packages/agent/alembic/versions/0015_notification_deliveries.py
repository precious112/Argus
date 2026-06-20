"""Add notification_deliveries table for delivery failure tracking.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, server_default="default"),
        sa.Column("alert_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("channel", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="alert"),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="failed"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_notification_deliveries_tenant_id", "notification_deliveries", ["tenant_id"]
    )
    op.create_index(
        "ix_notification_deliveries_alert_id", "notification_deliveries", ["alert_id"]
    )
    op.create_index(
        "ix_notification_deliveries_status", "notification_deliveries", ["status"]
    )
    op.create_index(
        "ix_notification_deliveries_created_at", "notification_deliveries", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_notification_deliveries_created_at", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_status", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_alert_id", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_tenant_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
