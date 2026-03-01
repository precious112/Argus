"""Polar SDK integration for checkout, webhooks, and customer portal."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from argus_agent.config import get_settings
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import Subscription, Tenant

logger = logging.getLogger("argus.billing.polar")


def _get_polar_client():  # type: ignore[no-untyped-def]
    from polar_sdk import Polar

    settings = get_settings()
    return Polar(access_token=settings.deployment.polar_access_token)


async def create_checkout_session(
    tenant_id: str, success_url: str, cancel_url: str
) -> dict[str, str]:
    """Create a Polar checkout session for the Teams plan."""
    settings = get_settings()
    polar = _get_polar_client()

    # Attach tenant_id as metadata so the webhook can link the subscription
    result = polar.checkouts.custom.create(
        request={
            "product_id": settings.deployment.polar_teams_product_id,
            "success_url": success_url,
            "metadata": {"tenant_id": tenant_id},
        },
    )

    return {
        "checkout_url": result.url,
        "checkout_id": result.id,
    }


async def get_subscription_status(tenant_id: str) -> dict[str, Any] | None:
    """Return the latest subscription for *tenant_id*, or None."""
    async with get_session() as session:
        result = await session.execute(
            select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return None
        return {
            "id": sub.id,
            "polar_subscription_id": sub.polar_subscription_id,
            "status": sub.status,
            "current_period_start": (
                sub.current_period_start.isoformat() if sub.current_period_start else None
            ),
            "current_period_end": (
                sub.current_period_end.isoformat() if sub.current_period_end else None
            ),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        }


async def handle_webhook_event(payload: bytes, headers: dict[str, str]) -> dict[str, str]:
    """Validate signature, parse event, and dispatch to handler."""
    from polar_sdk.webhooks import validate_event

    settings = get_settings()
    event = validate_event(
        payload=payload,
        headers=headers,
        secret=settings.deployment.polar_webhook_secret,
    )

    event_type = event.type
    logger.info("Polar webhook received: %s", event_type)

    handlers: dict[str, Any] = {
        "subscription.active": _handle_subscription_active,
        "subscription.canceled": _handle_subscription_canceled,
        "subscription.revoked": _handle_subscription_revoked,
        "subscription.updated": _handle_subscription_updated,
    }

    handler = handlers.get(event_type)
    if handler:
        await handler(event.data)
        return {"status": "processed", "event": event_type}

    logger.debug("Unhandled Polar event type: %s", event_type)
    return {"status": "ignored", "event": event_type}


async def _handle_subscription_active(data: Any) -> None:
    """Activate or reactivate subscription: upsert sub + set plan=teams."""
    sub_id = data.id
    customer_id = data.customer_id if hasattr(data, "customer_id") else ""
    product_id = data.product_id if hasattr(data, "product_id") else ""
    tenant_id = _extract_tenant_id(data)

    if not tenant_id:
        logger.warning("No tenant_id in subscription metadata for %s", sub_id)
        return

    async with get_session() as session:
        # Upsert subscription
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "active"
            sub.polar_customer_id = customer_id
            sub.polar_product_id = product_id
            sub.current_period_start = _parse_dt(data, "current_period_start")
            sub.current_period_end = _parse_dt(data, "current_period_end")
            sub.cancel_at_period_end = False
            sub.updated_at = datetime.now(UTC)
        else:
            sub = Subscription(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                polar_subscription_id=sub_id,
                polar_customer_id=customer_id,
                polar_product_id=product_id,
                status="active",
                current_period_start=_parse_dt(data, "current_period_start"),
                current_period_end=_parse_dt(data, "current_period_end"),
            )
            session.add(sub)

        # Upgrade tenant plan
        tenant = await session.get(Tenant, tenant_id)
        if tenant:
            tenant.plan = "teams"
            tenant.polar_customer_id = customer_id
            tenant.updated_at = datetime.now(UTC)

        await session.commit()

    logger.info("Subscription activated for tenant %s", tenant_id)


async def _handle_subscription_canceled(data: Any) -> None:
    """Mark subscription as canceled but keep plan until period end."""
    sub_id = data.id

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "canceled"
            sub.cancel_at_period_end = True
            sub.updated_at = datetime.now(UTC)
            await session.commit()

    logger.info("Subscription canceled (grace): %s", sub_id)


async def _handle_subscription_revoked(data: Any) -> None:
    """Immediately downgrade tenant to free."""
    sub_id = data.id

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "revoked"
            sub.updated_at = datetime.now(UTC)

            tenant = await session.get(Tenant, sub.tenant_id)
            if tenant:
                tenant.plan = "free"
                tenant.updated_at = datetime.now(UTC)

            await session.commit()
            logger.info("Subscription revoked, tenant %s downgraded to free", sub.tenant_id)


async def _handle_subscription_updated(data: Any) -> None:
    """Update period dates on subscription renewal."""
    sub_id = data.id

    async with get_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.current_period_start = _parse_dt(data, "current_period_start")
            sub.current_period_end = _parse_dt(data, "current_period_end")
            sub.updated_at = datetime.now(UTC)
            await session.commit()

    logger.info("Subscription updated: %s", sub_id)


async def create_customer_portal_session(tenant_id: str) -> dict[str, str]:
    """Create a Polar customer portal session for managing the subscription."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant or not tenant.polar_customer_id:
            return {"portal_url": ""}

    polar = _get_polar_client()
    result = polar.customer_sessions.create(
        request={"customer_id": tenant.polar_customer_id},
    )
    return {"portal_url": result.customer_portal_url}


def _extract_tenant_id(data: Any) -> str:
    """Extract tenant_id from subscription metadata."""
    metadata = getattr(data, "metadata", None) or {}
    return metadata.get("tenant_id", "")


def _parse_dt(data: Any, field: str) -> datetime | None:
    """Safely parse a datetime field from webhook data."""
    val = getattr(data, field, None)
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None
