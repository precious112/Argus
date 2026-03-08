"""Add event_quota_usage table for unified billing counter.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_quota_usage",
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "period_start",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("event_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "period_start"),
    )

    # Seed from existing sdk_events so current tenants don't lose their count
    op.execute("""
        INSERT INTO event_quota_usage (tenant_id, period_start, event_count)
        SELECT
            tenant_id,
            date_trunc('month', NOW()) AS period_start,
            COUNT(*) AS event_count
        FROM sdk_events
        WHERE timestamp >= date_trunc('month', NOW())
        GROUP BY tenant_id
        ON CONFLICT (tenant_id, period_start) DO NOTHING
    """)

    # RLS
    op.execute("ALTER TABLE event_quota_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE event_quota_usage FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON event_quota_usage")
    op.execute(
        "CREATE POLICY tenant_isolation ON event_quota_usage "
        "USING (tenant_id = current_setting('app.current_tenant', true)) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON event_quota_usage")
    op.drop_table("event_quota_usage")
