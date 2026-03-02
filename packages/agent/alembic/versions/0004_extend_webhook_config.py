"""Extend webhook_configs with tool execution fields.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhook_configs",
        sa.Column("name", sa.String(255), server_default=""),
    )
    op.add_column(
        "webhook_configs",
        sa.Column("mode", sa.String(30), server_default="alerts_only"),
    )
    op.add_column(
        "webhook_configs",
        sa.Column("remote_tools", sa.Text, server_default="*"),
    )
    op.add_column(
        "webhook_configs",
        sa.Column("timeout_seconds", sa.Integer, server_default="30"),
    )
    op.add_column(
        "webhook_configs",
        sa.Column("last_ping_at", sa.DateTime, nullable=True),
    )
    op.add_column(
        "webhook_configs",
        sa.Column("last_ping_status", sa.String(20), server_default=""),
    )
    op.add_column(
        "webhook_configs",
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column("webhook_configs", "updated_at")
    op.drop_column("webhook_configs", "last_ping_status")
    op.drop_column("webhook_configs", "last_ping_at")
    op.drop_column("webhook_configs", "timeout_seconds")
    op.drop_column("webhook_configs", "remote_tools")
    op.drop_column("webhook_configs", "mode")
    op.drop_column("webhook_configs", "name")
