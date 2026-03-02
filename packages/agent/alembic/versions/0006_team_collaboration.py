"""Team collaboration: service configs, escalation policies, investigation assignment.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- service_configs table ---
    op.create_table(
        "service_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(20), server_default="production"),
        sa.Column("owner_user_id", sa.String(36), server_default=""),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_service_configs_tenant_service",
        "service_configs",
        ["tenant_id", "service_name"],
        unique=True,
    )

    # --- escalation_policies table ---
    op.create_table(
        "escalation_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("service_name", sa.String(255), server_default=""),
        sa.Column("min_severity", sa.String(20), server_default=""),
        sa.Column("primary_contact_id", sa.String(36), server_default=""),
        sa.Column("backup_contact_id", sa.String(36), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # --- Add assignment + service columns to investigations ---
    op.add_column("investigations", sa.Column("assigned_to", sa.String(36), server_default=""))
    op.add_column("investigations", sa.Column("assigned_by", sa.String(36), server_default=""))
    op.add_column("investigations", sa.Column("service_name", sa.String(255), server_default=""))

    # --- RLS policies (PostgreSQL only, no-op on SQLite) ---
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for table in ("service_configs", "escalation_policies"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING (tenant_id = current_setting('app.current_tenant', true))"
            )


def downgrade() -> None:
    op.drop_column("investigations", "service_name")
    op.drop_column("investigations", "assigned_by")
    op.drop_column("investigations", "assigned_to")

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for table in ("escalation_policies", "service_configs"):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("escalation_policies")
    op.drop_index("ix_service_configs_tenant_service", table_name="service_configs")
    op.drop_table("service_configs")
