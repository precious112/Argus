"""Initial schema with RLS policies for multi-tenancy.

Revision ID: 0001
Revises: None
Create Date: 2026-02-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables that need RLS tenant isolation
_TENANT_TABLES = [
    "conversations",
    "messages",
    "users",
    "sessions",
    "audit_log",
    "alert_history",
    "investigations",
    "app_config",
    "notification_channel_configs",
    "token_usage",
    "alert_acknowledgments",
    "alert_rule_mutes",
    # SaaS-only tables
    "tenants",
    "webhook_configs",
    "team_members",
    "team_invitations",
]

# api_keys needs a special policy: allow lookup without tenant context
_API_KEYS_TABLE = "api_keys"


def upgrade() -> None:
    # --- Existing operational tables (13) ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("title", sa.String(255), server_default=""),
        sa.Column("source", sa.String(50), server_default="user"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("conversation_id", sa.String(36), index=True),
        sa.Column("role", sa.String(20)),
        sa.Column("content", sa.Text, server_default=""),
        sa.Column("tool_calls", sa.JSON, nullable=True),
        sa.Column("tool_result", sa.JSON, nullable=True),
        sa.Column("token_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("username", sa.String(150), unique=True, index=True),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("user_id", sa.String(36), server_default=""),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("ip_address", sa.String(45), server_default=""),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("timestamp", sa.DateTime, index=True),
        sa.Column("action", sa.String(100)),
        sa.Column("command", sa.Text, server_default=""),
        sa.Column("result", sa.Text, server_default=""),
        sa.Column("success", sa.Boolean, server_default="true"),
        sa.Column("user_approved", sa.Boolean, server_default="false"),
        sa.Column("ip_address", sa.String(45), server_default=""),
        sa.Column("conversation_id", sa.String(36), server_default=""),
    )

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("alert_id", sa.String(36), index=True, server_default=""),
        sa.Column("rule_id", sa.String(100), server_default=""),
        sa.Column("rule_name", sa.String(255), server_default=""),
        sa.Column("timestamp", sa.DateTime, index=True),
        sa.Column("severity", sa.String(20)),
        sa.Column("title", sa.String(255)),
        sa.Column("message", sa.Text, server_default=""),
        sa.Column("event_type", sa.String(50), server_default=""),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("source", sa.String(100), server_default=""),
        sa.Column("resolved", sa.Boolean, server_default="false"),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("investigation_id", sa.String(36), server_default=""),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("acknowledged_at", sa.DateTime, nullable=True),
        sa.Column("acknowledged_by", sa.String(100), server_default=""),
    )

    op.create_table(
        "investigations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("trigger", sa.Text, server_default=""),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("tokens_used", sa.Integer, server_default="0"),
        sa.Column("conversation_id", sa.String(36), server_default=""),
        sa.Column("alert_id", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "app_config",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("value", sa.Text, server_default=""),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "notification_channel_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("channel_type", sa.String(50), unique=True, index=True),
        sa.Column("enabled", sa.Boolean, server_default="false"),
        sa.Column("config", sa.JSON),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "token_usage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("timestamp", sa.DateTime, index=True),
        sa.Column("provider", sa.String(50)),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_tokens", sa.Integer, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, server_default="0"),
        sa.Column("source", sa.String(50), server_default=""),
        sa.Column("conversation_id", sa.String(36), server_default=""),
    )

    op.create_table(
        "alert_acknowledgments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("dedup_key", sa.String(255), unique=True, index=True),
        sa.Column("rule_id", sa.String(100)),
        sa.Column("source", sa.String(100), server_default=""),
        sa.Column("acknowledged_by", sa.String(100), server_default="user"),
        sa.Column("reason", sa.Text, server_default=""),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "alert_rule_mutes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default", index=True),
        sa.Column("rule_id", sa.String(100), index=True),
        sa.Column("muted_by", sa.String(100), server_default="user"),
        sa.Column("reason", sa.Text, server_default=""),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    # --- SaaS-only tables (5) ---
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("slug", sa.String(100), unique=True, index=True),
        sa.Column("plan", sa.String(50), server_default="free"),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), index=True),
        sa.Column("name", sa.String(255), server_default=""),
        sa.Column("key_prefix", sa.String(20), index=True),
        sa.Column("key_hash", sa.String(64), unique=True, index=True),
        sa.Column("environment", sa.String(20), server_default="production"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), index=True),
        sa.Column("url", sa.Text),
        sa.Column("secret", sa.String(255), server_default=""),
        sa.Column("events", sa.Text, server_default="*"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), index=True),
        sa.Column("user_id", sa.String(36), index=True),
        sa.Column("role", sa.String(20), server_default="member"),
        sa.Column("joined_at", sa.DateTime),
    )

    op.create_table(
        "team_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), index=True),
        sa.Column("email", sa.String(255)),
        sa.Column("role", sa.String(20), server_default="member"),
        sa.Column("invited_by", sa.String(36), server_default=""),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("accepted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime),
    )

    # --- Row-Level Security policies ---
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('app.current_tenant', true)) "
            f"WITH CHECK (tenant_id = current_setting('app.current_tenant', true))"
        )

    # api_keys: RLS with special bypass for key validation (no tenant context yet)
    op.execute(f"ALTER TABLE {_API_KEYS_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_API_KEYS_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_API_KEYS_TABLE} "
        f"USING (tenant_id = current_setting('app.current_tenant', true)) "
        f"WITH CHECK (tenant_id = current_setting('app.current_tenant', true))"
    )
    # Allow lookup by key_hash without tenant context (for validation during ingest)
    op.execute(
        f"CREATE POLICY api_key_lookup ON {_API_KEYS_TABLE} FOR SELECT "
        f"USING (current_setting('app.current_tenant', true) = '' OR "
        f"tenant_id = current_setting('app.current_tenant', true))"
    )


def downgrade() -> None:
    # Drop RLS policies
    all_tables = _TENANT_TABLES + [_API_KEYS_TABLE]
    for table in all_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"DROP POLICY IF EXISTS api_key_lookup ON {_API_KEYS_TABLE}")

    # Drop tables in reverse dependency order
    for table in reversed([
        "conversations", "messages", "users", "sessions",
        "audit_log", "alert_history", "investigations", "app_config",
        "notification_channel_configs", "token_usage",
        "alert_acknowledgments", "alert_rule_mutes",
        "tenants", "api_keys", "webhook_configs",
        "team_members", "team_invitations",
    ]):
        op.drop_table(table)
