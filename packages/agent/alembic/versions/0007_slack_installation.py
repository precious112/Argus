"""Slack OAuth installation per tenant.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slack_installations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(20), nullable=False),
        sa.Column("team_name", sa.String(255), server_default=""),
        sa.Column("bot_token", sa.Text(), server_default=""),
        sa.Column("bot_user_id", sa.String(30), server_default=""),
        sa.Column("default_channel_id", sa.String(20), server_default=""),
        sa.Column("default_channel_name", sa.String(255), server_default=""),
        sa.Column("installed_by", sa.String(36), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_slack_installations_tenant",
        "slack_installations",
        ["tenant_id"],
        unique=True,
    )

    # RLS policy (PostgreSQL only, no-op on SQLite)
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE slack_installations ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON slack_installations "
            "USING (tenant_id = current_setting('app.current_tenant', true))"
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON slack_installations")

    op.drop_index("ix_slack_installations_tenant", table_name="slack_installations")
    op.drop_table("slack_installations")
