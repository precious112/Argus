"""Contextvars-based tenant context that flows through every request.

In self-hosted mode, tenant_id is always "default".
In SaaS mode, tenant_id is extracted from the JWT by the tenancy middleware.
"""

from __future__ import annotations

from contextvars import ContextVar

_tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="default")


def get_tenant_id() -> str:
    """Get the current tenant ID from context."""
    return _tenant_id_var.get()


def set_tenant_id(tenant_id: str) -> None:
    """Set the current tenant ID in context."""
    _tenant_id_var.set(tenant_id)
