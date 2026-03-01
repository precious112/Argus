"""Add subscription table and polar_customer_id to tenants.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add polar_customer_id to tenants
    op.add_column(
        "tenants",
        sa.Column("polar_customer_id", sa.String(100), server_default=""),
    )

    # Create subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("polar_subscription_id", sa.String(100), nullable=False, unique=True),
        sa.Column("polar_customer_id", sa.String(100), server_default=""),
        sa.Column("polar_product_id", sa.String(100), server_default=""),
        sa.Column("status", sa.String(30), server_default="active"),
        sa.Column("current_period_start", sa.DateTime, nullable=True),
        sa.Column("current_period_end", sa.DateTime, nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_polar_sub", "subscriptions", ["polar_subscription_id"])
    op.create_index("ix_subscriptions_polar_cust", "subscriptions", ["polar_customer_id"])

    # RLS policy for subscriptions
    op.execute(
        "ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY subscriptions_tenant_isolation ON subscriptions "
        "USING (tenant_id = current_setting('app.current_tenant', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS subscriptions_tenant_isolation ON subscriptions")
    op.drop_index("ix_subscriptions_polar_cust", "subscriptions")
    op.drop_index("ix_subscriptions_polar_sub", "subscriptions")
    op.drop_index("ix_subscriptions_tenant_id", "subscriptions")
    op.drop_table("subscriptions")
    op.drop_column("tenants", "polar_customer_id")
