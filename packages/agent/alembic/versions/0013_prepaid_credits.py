"""Replace PAYG budget with prepaid credit balance + audit table.

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add credit balance column
    op.add_column(
        "tenants",
        sa.Column("payg_credit_balance_cents", sa.Integer(), server_default="0", nullable=False),
    )

    # Create credit_transactions table
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("balance_after_cents", sa.Integer(), nullable=False),
        sa.Column("tx_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("polar_order_id", sa.String(100), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_credit_tx_tenant_created",
        "credit_transactions",
        ["tenant_id", "created_at"],
    )

    # RLS policy for credit_transactions
    op.execute(
        "ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON credit_transactions "
        "USING (tenant_id = current_setting('app.current_tenant', true))"
    )

    # Migrate existing PAYG budgets to credit balance
    op.execute(
        "UPDATE tenants SET payg_credit_balance_cents = payg_monthly_budget_cents "
        "WHERE payg_enabled = true AND payg_monthly_budget_cents > 0"
    )

    # Drop old PAYG columns
    op.drop_column("tenants", "payg_enabled")
    op.drop_column("tenants", "payg_monthly_budget_cents")


def downgrade() -> None:
    # Restore old PAYG columns
    op.add_column(
        "tenants",
        sa.Column("payg_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column("payg_monthly_budget_cents", sa.Integer(), server_default="0", nullable=False),
    )

    # Migrate credit balance back to budget
    op.execute(
        "UPDATE tenants SET payg_enabled = true, payg_monthly_budget_cents = payg_credit_balance_cents "
        "WHERE payg_credit_balance_cents > 0"
    )

    # Drop credit_transactions table
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON credit_transactions")
    op.drop_index("ix_credit_tx_tenant_created", table_name="credit_transactions")
    op.drop_table("credit_transactions")

    # Drop credit balance column
    op.drop_column("tenants", "payg_credit_balance_cents")
