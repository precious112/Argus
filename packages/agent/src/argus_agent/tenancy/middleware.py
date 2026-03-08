"""FastAPI middleware that extracts tenant_id from JWT and sets it in context."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from argus_agent.tenancy.context import set_tenant_id

logger = logging.getLogger("argus.tenancy")


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from the JWT and set it in the request context.

    In self-hosted mode this always sets "default".
    In SaaS mode it reads the ``tenant_id`` claim from the decoded JWT.
    """

    def __init__(self, app, *, is_saas: bool = False):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.is_saas = is_saas

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if not self.is_saas:
            set_tenant_id("default")
            return await call_next(request)

        # In SaaS mode, extract tenant_id from the decoded JWT.
        # The auth middleware runs before this and stores the decoded
        # payload in request.state.user (will be wired in Phase 2).
        user = getattr(request.state, "user", None)
        if user and isinstance(user, dict):
            tenant_id = user.get("tenant_id", "default")
        else:
            tenant_id = "default"

        set_tenant_id(tenant_id)
        return await call_next(request)
