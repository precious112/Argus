"""Auth enhancements: OAuth fields, email verification, password reset, BYOK LLM.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User model: OAuth + email verification fields
    op.add_column("users", sa.Column("email_verified", sa.Boolean, server_default="false"))
    op.add_column("users", sa.Column("oauth_provider", sa.String(20), server_default=""))
    op.add_column("users", sa.Column("oauth_id", sa.String(255), server_default=""))

    # Email verification tokens
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), index=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Password reset tokens
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), index=True, nullable=False),
        sa.Column("token", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Tenant LLM configs (BYOK)
    op.create_table(
        "tenant_llm_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), unique=True, index=True, nullable=False),
        sa.Column("provider", sa.String(50), server_default="openai"),
        sa.Column("encrypted_api_key", sa.Text, server_default=""),
        sa.Column("model", sa.String(100), server_default=""),
        sa.Column("base_url", sa.String(500), server_default=""),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # RLS policies for new tables
    for table in ("email_verification_tokens", "password_reset_tokens"):
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"
        )
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
                USING (user_id IN (
                    SELECT id FROM users
                    WHERE tenant_id = current_setting('app.current_tenant', true)
                ));"""
        )

    op.execute("ALTER TABLE tenant_llm_configs ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """CREATE POLICY tenant_isolation ON tenant_llm_configs
           USING (tenant_id = current_setting('app.current_tenant', true));"""
    )


def downgrade() -> None:
    op.drop_table("tenant_llm_configs")
    op.drop_table("password_reset_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_column("users", "oauth_id")
    op.drop_column("users", "oauth_provider")
    op.drop_column("users", "email_verified")
