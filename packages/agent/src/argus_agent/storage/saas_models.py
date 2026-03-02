"""SaaS-only ORM models — tenants, API keys, webhooks, teams."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from argus_agent.storage.models import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    """A SaaS tenant / organisation."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    polar_customer_id: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ApiKey(Base):
    """Hashed API key for SDK ingest authentication."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    key_prefix: Mapped[str] = mapped_column(String(20), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(20), default="production")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebhookConfig(Base):
    """Tenant webhook endpoint configuration."""

    __tablename__ = "webhook_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(255), default="")
    events: Mapped[str] = mapped_column(Text, default="*")  # comma-separated event types
    # alerts_only | tool_execution | both
    mode: Mapped[str] = mapped_column(String(30), default="alerts_only")
    # comma-separated tool names or "*" for all
    remote_tools: Mapped[str] = mapped_column(Text, default="*")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ping_status: Mapped[str] = mapped_column(String(20), default="")  # ok | error | timeout
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class TeamMember(Base):
    """Maps a user to a tenant with a role."""

    __tablename__ = "team_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner, admin, member
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class TeamInvitation(Base):
    """Pending invitation to join a tenant."""

    __tablename__ = "team_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")
    invited_by: Mapped[str] = mapped_column(String(36), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EmailVerificationToken(Base):
    """Token for email verification."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    email: Mapped[str] = mapped_column(String(255))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PasswordResetToken(Base):
    """Token for password reset."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class TenantLLMConfig(Base):
    """Per-tenant BYOK LLM key configuration."""

    __tablename__ = "tenant_llm_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), default="openai")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ServiceConfig(Base):
    """Per-service configuration with ownership and environment."""

    __tablename__ = "service_configs"
    __table_args__ = (
        Index("ix_service_configs_tenant_service", "tenant_id", "service_name", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    service_name: Mapped[str] = mapped_column(String(255))
    environment: Mapped[str] = mapped_column(String(20), default="production")
    owner_user_id: Mapped[str] = mapped_column(String(36), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EscalationPolicy(Base):
    """Escalation routing policy — who to contact for alerts."""

    __tablename__ = "escalation_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # Filter: specific service or severity (empty = match all)
    service_name: Mapped[str] = mapped_column(String(255), default="")
    min_severity: Mapped[str] = mapped_column(String(20), default="")  # NOTABLE, URGENT, etc.
    # Contacts
    primary_contact_id: Mapped[str] = mapped_column(String(36), default="")
    backup_contact_id: Mapped[str] = mapped_column(String(36), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Subscription(Base):
    """Polar subscription tied to a tenant."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_polar_sub", "polar_subscription_id"),
        Index("ix_subscriptions_polar_cust", "polar_customer_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    polar_subscription_id: Mapped[str] = mapped_column(String(100), unique=True)
    polar_customer_id: Mapped[str] = mapped_column(String(100), default="")
    polar_product_id: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(30), default="active")
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
