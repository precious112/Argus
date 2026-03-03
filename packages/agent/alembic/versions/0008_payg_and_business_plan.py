"""PAYG billing, Business plan, and usage notifications.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Tenant PAYG columns ---
    op.add_column("tenants", sa.Column("payg_enabled", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("tenants", sa.Column("payg_monthly_budget_cents", sa.Integer(), server_default=sa.text("0")))

    # --- Subscription billing interval + plan_id ---
    op.add_column("subscriptions", sa.Column("billing_interval", sa.String(20), server_default="month"))
    op.add_column("subscriptions", sa.Column("plan_id", sa.String(50), server_default="teams"))

    # --- Usage notifications table ---
    op.create_table(
        "usage_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("billing_period_start", sa.DateTime(), nullable=False),
        sa.Column("threshold", sa.String(50), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_usage_notifications_tenant_id", "usage_notifications", ["tenant_id"])
    op.create_index(
        "ix_usage_notif_tenant_period",
        "usage_notifications",
        ["tenant_id", "billing_period_start"],
    )

    # RLS policy (PostgreSQL only)
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE usage_notifications ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON usage_notifications "
            "USING (tenant_id = current_setting('app.current_tenant', true))"
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON usage_notifications")

    op.drop_index("ix_usage_notif_tenant_period", table_name="usage_notifications")
    op.drop_index("ix_usage_notifications_tenant_id", table_name="usage_notifications")
    op.drop_table("usage_notifications")

    op.drop_column("subscriptions", "plan_id")
    op.drop_column("subscriptions", "billing_interval")
    op.drop_column("tenants", "payg_monthly_budget_cents")
    op.drop_column("tenants", "payg_enabled")
