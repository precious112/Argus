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


def _get_raw_session():
    """Get a raw session without RLS for webhook (system-level) operations."""
    from argus_agent.storage.postgres_operational import get_raw_session

    session = get_raw_session()
    if session is None:
        raise RuntimeError("PostgreSQL engine not initialized")
    return session


def _get_polar_client():  # type: ignore[no-untyped-def]
    from polar_sdk import Polar

    settings = get_settings()
    kwargs: dict[str, Any] = {"access_token": settings.deployment.polar_access_token}
    if settings.deployment.polar_server:
        kwargs["server"] = settings.deployment.polar_server
    return Polar(**kwargs)


def _get_product_id(plan_id: str, billing_interval: str) -> str:
    """Map (plan_id, billing_interval) → Polar product ID from config."""
    settings = get_settings()
    mapping: dict[tuple[str, str], str] = {
        ("teams", "month"): settings.deployment.polar_teams_product_id,
        ("teams", "year"): settings.deployment.polar_teams_annual_product_id,
        ("business", "month"): settings.deployment.polar_business_product_id,
        ("business", "year"): settings.deployment.polar_business_annual_product_id,
    }
    product_id = mapping.get((plan_id, billing_interval), "")
    if not product_id:
        # Fallback to Teams monthly if no specific product configured
        product_id = settings.deployment.polar_teams_product_id
    return product_id


def _product_id_to_plan(product_id: str) -> str:
    """Reverse-map a Polar product ID back to a plan name."""
    settings = get_settings()
    reverse: dict[str, str] = {}
    if settings.deployment.polar_teams_product_id:
        reverse[settings.deployment.polar_teams_product_id] = "teams"
    if settings.deployment.polar_teams_annual_product_id:
        reverse[settings.deployment.polar_teams_annual_product_id] = "teams"
    if settings.deployment.polar_business_product_id:
        reverse[settings.deployment.polar_business_product_id] = "business"
    if settings.deployment.polar_business_annual_product_id:
        reverse[settings.deployment.polar_business_annual_product_id] = "business"
    return reverse.get(product_id, "teams")


def _product_id_to_interval(product_id: str) -> str:
    """Reverse-map a Polar product ID back to a billing interval."""
    settings = get_settings()
    annual_ids = {
        settings.deployment.polar_teams_annual_product_id,
        settings.deployment.polar_business_annual_product_id,
    }
    return "year" if product_id in annual_ids else "month"


async def upgrade_subscription(
    tenant_id: str,
    new_plan_id: str,
    billing_interval: str = "month",
) -> dict[str, Any]:
    """Upgrade an existing subscription to a different plan via the Polar API.

    Instead of creating a new checkout, this updates the existing subscription's
    product, so Polar handles proration server-side.
    """
    new_product_id = _get_product_id(new_plan_id, billing_interval)
    polar = _get_polar_client()

    async with get_session() as session:
        # Find active subscription for this tenant
        result = await session.execute(
            select(Subscription)
            .where(Subscription.tenant_id == tenant_id, Subscription.status == "active")
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            raise ValueError("No active subscription found for tenant")

        # Call Polar to switch the product on the existing subscription
        try:
            polar.subscriptions.update(
                id=sub.polar_subscription_id,
                subscription_update={"product_id": new_product_id},
            )
        except Exception:
            logger.exception(
                "Polar subscription upgrade failed (sub=%s, product=%s)",
                sub.polar_subscription_id, new_product_id,
            )
            raise

        # Update local records
        sub.polar_product_id = new_product_id
        sub.plan_id = new_plan_id
        sub.billing_interval = billing_interval
        sub.updated_at = datetime.now(UTC).replace(tzinfo=None)

        tenant = await session.get(Tenant, tenant_id)
        if tenant:
            tenant.plan = new_plan_id
            tenant.updated_at = datetime.now(UTC).replace(tzinfo=None)

        await session.commit()

    logger.info(
        "Subscription upgraded for tenant %s (plan=%s, interval=%s)",
        tenant_id, new_plan_id, billing_interval,
    )
    return {"upgraded": True, "plan_id": new_plan_id}


async def create_checkout_session(
    tenant_id: str,
    success_url: str,
    plan_id: str = "teams",
    billing_interval: str = "month",
) -> dict[str, str]:
    """Create a Polar checkout session for the specified plan and interval."""
    polar = _get_polar_client()
    product_id = _get_product_id(plan_id, billing_interval)

    try:
        result = polar.checkouts.create(
            request={
                "products": [product_id],
                "success_url": success_url,
                "metadata": {
                    "tenant_id": tenant_id,
                    "plan_id": plan_id,
                    "billing_interval": billing_interval,
                },
            },
        )
    except Exception:
        logger.exception("Polar checkout creation failed (product=%s)", product_id)
        raise

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
            "plan_id": sub.plan_id,
            "billing_interval": sub.billing_interval,
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
    from polar_sdk.models import (
        WebhookSubscriptionActivePayload,
        WebhookSubscriptionCanceledPayload,
        WebhookSubscriptionRevokedPayload,
        WebhookSubscriptionUpdatedPayload,
    )
    from polar_sdk.webhooks import validate_event

    settings = get_settings()
    event = validate_event(
        body=payload,
        headers=headers,
        secret=settings.deployment.polar_webhook_secret,
    )

    # SDK returns typed pydantic models; field is 'TYPE' not 'type'
    event_type = getattr(event, "TYPE", None) or type(event).__name__
    logger.info("Polar webhook received: %s", event_type)

    if isinstance(event, WebhookSubscriptionActivePayload):
        await _handle_subscription_active(event.data)
        return {"status": "processed", "event": event_type}
    elif isinstance(event, WebhookSubscriptionCanceledPayload):
        await _handle_subscription_canceled(event.data)
        return {"status": "processed", "event": event_type}
    elif isinstance(event, WebhookSubscriptionRevokedPayload):
        await _handle_subscription_revoked(event.data)
        return {"status": "processed", "event": event_type}
    elif isinstance(event, WebhookSubscriptionUpdatedPayload):
        await _handle_subscription_updated(event.data)
        return {"status": "processed", "event": event_type}

    # Handle credit purchase completions
    try:
        from polar_sdk.models import WebhookCheckoutUpdatedPayload

        if isinstance(event, WebhookCheckoutUpdatedPayload):
            checkout_data = event.data
            status = getattr(checkout_data, "status", "")
            if status == "succeeded":
                metadata = getattr(checkout_data, "metadata", None) or {}
                if metadata.get("purchase_type") == "payg_credits":
                    await _handle_credit_purchase(metadata, checkout_data)
                    return {"status": "processed", "event": event_type}
    except ImportError:
        pass

    logger.debug("Unhandled Polar event type: %s", event_type)
    return {"status": "ignored", "event": event_type}


async def _handle_credit_purchase(metadata: dict[str, str], checkout_data: Any) -> None:
    """Process a completed credit purchase checkout."""
    tenant_id = metadata.get("tenant_id", "")
    amount_str = metadata.get("amount_cents", "0")
    try:
        amount_cents = int(amount_str)
    except (ValueError, TypeError):
        logger.warning("Invalid amount_cents in credit purchase metadata: %s", amount_str)
        return

    if not tenant_id or amount_cents <= 0:
        logger.warning("Invalid credit purchase: tenant=%s, amount=%d", tenant_id, amount_cents)
        return

    order_id = getattr(checkout_data, "id", "") or ""

    from argus_agent.billing.payg import add_credits

    await add_credits(
        tenant_id,
        amount_cents,
        polar_order_id=order_id,
        description=f"Polar checkout (${amount_cents / 100:.2f})",
    )
    logger.info("Credit purchase processed: tenant=%s, amount=%dc", tenant_id, amount_cents)


async def _handle_subscription_active(data: Any) -> None:
    """Activate or reactivate subscription: upsert sub + set plan."""
    sub_id = data.id
    customer_id = data.customer_id if hasattr(data, "customer_id") else ""
    product_id = data.product_id if hasattr(data, "product_id") else ""
    tenant_id = _extract_tenant_id(data)

    if not tenant_id:
        logger.warning("No tenant_id in subscription metadata for %s", sub_id)
        return

    # Determine plan from metadata or product_id
    metadata = getattr(data, "metadata", None) or {}
    plan_id = metadata.get("plan_id") or _product_id_to_plan(product_id)
    billing_interval = metadata.get("billing_interval") or _product_id_to_interval(product_id)

    # Use raw session (no RLS) — webhook has no user context
    async with _get_raw_session() as session:
        # Upsert subscription
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "active"
            sub.polar_customer_id = customer_id
            sub.polar_product_id = product_id
            sub.plan_id = plan_id
            sub.billing_interval = billing_interval
            sub.current_period_start = _parse_dt(data, "current_period_start")
            sub.current_period_end = _parse_dt(data, "current_period_end")
            sub.cancel_at_period_end = False
            sub.updated_at = datetime.now(UTC).replace(tzinfo=None)
        else:
            sub = Subscription(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                polar_subscription_id=sub_id,
                polar_customer_id=customer_id,
                polar_product_id=product_id,
                plan_id=plan_id,
                billing_interval=billing_interval,
                status="active",
                current_period_start=_parse_dt(data, "current_period_start"),
                current_period_end=_parse_dt(data, "current_period_end"),
            )
            session.add(sub)

        # Upgrade tenant plan
        tenant = await session.get(Tenant, tenant_id)
        if tenant:
            tenant.plan = plan_id
            tenant.polar_customer_id = customer_id
            tenant.updated_at = datetime.now(UTC).replace(tzinfo=None)

        await session.commit()

    logger.info(
        "Subscription activated for tenant %s (plan=%s, interval=%s)",
        tenant_id, plan_id, billing_interval,
    )


async def _handle_subscription_canceled(data: Any) -> None:
    """Mark subscription as canceled but keep plan until period end."""
    sub_id = data.id

    # Use raw session (no RLS) — webhook has no user context
    async with _get_raw_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "canceled"
            sub.cancel_at_period_end = True
            sub.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()

    logger.info("Subscription canceled (grace): %s", sub_id)


async def _handle_subscription_revoked(data: Any) -> None:
    """Immediately downgrade tenant to free."""
    sub_id = data.id

    # Use raw session (no RLS) — webhook has no user context
    async with _get_raw_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "revoked"
            sub.updated_at = datetime.now(UTC).replace(tzinfo=None)

            tenant = await session.get(Tenant, sub.tenant_id)
            if tenant:
                tenant.plan = "free"
                tenant.updated_at = datetime.now(UTC).replace(tzinfo=None)

            await session.commit()
            logger.info("Subscription revoked, tenant %s downgraded to free", sub.tenant_id)


async def _handle_subscription_updated(data: Any) -> None:
    """Update period dates on subscription renewal."""
    sub_id = data.id

    # Use raw session (no RLS) — webhook has no user context
    async with _get_raw_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == sub_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.current_period_start = _parse_dt(data, "current_period_start")
            sub.current_period_end = _parse_dt(data, "current_period_end")
            sub.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()

    logger.info("Subscription updated: %s", sub_id)


async def create_credit_checkout_session(
    tenant_id: str,
    amount_cents: int,
    success_url: str,
) -> dict[str, str]:
    """Create a Polar checkout for prepaid credit purchase."""
    settings = get_settings()
    product_id = settings.deployment.polar_payg_credits_product_id
    if not product_id:
        raise ValueError("Credit purchases not configured (no polar_payg_credits_product_id)")

    polar = _get_polar_client()

    # Look up Polar customer ID
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)

    metadata = {
        "tenant_id": tenant_id,
        "purchase_type": "payg_credits",
        "amount_cents": str(amount_cents),
    }
    checkout_kwargs: dict[str, Any] = {
        "products": [product_id],
        "success_url": success_url,
        "metadata": metadata,
        "amount": amount_cents,
    }
    if tenant and tenant.polar_customer_id:
        checkout_kwargs["customer_id"] = tenant.polar_customer_id

    try:
        result = polar.checkouts.create(request=checkout_kwargs)
    except Exception:
        logger.exception(
            "Polar credit checkout failed (product=%s, amount=%d)",
            product_id, amount_cents,
        )
        raise

    return {
        "checkout_url": result.url,
        "checkout_id": result.id,
    }


async def create_customer_portal_session(tenant_id: str) -> dict[str, str]:
    """Create a Polar customer portal session for managing the subscription."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant or not tenant.polar_customer_id:
            return {"portal_url": ""}

    polar = _get_polar_client()
    try:
        result = polar.customer_sessions.create(
            request={"customer_id": tenant.polar_customer_id},
        )
    except Exception:
        logger.exception("Polar customer portal session failed (tenant=%s)", tenant_id)
        raise
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
        return val.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None
