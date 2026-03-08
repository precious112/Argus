"""Prepaid credit balance management for PAYG overages."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import CreditTransaction, Tenant

logger = logging.getLogger("argus.billing.credits")


def _get_raw_session():
    """Get a raw session without RLS for system-level credit operations."""
    from argus_agent.storage.postgres_operational import get_raw_session

    session = get_raw_session()
    if session is None:
        raise RuntimeError("PostgreSQL engine not initialized")
    return session


async def get_credit_status(tenant_id: str) -> dict[str, Any]:
    """Return current credit balance and recent transactions."""
    async with get_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant:
            return {
                "balance_cents": 0,
                "balance_dollars": 0.0,
                "recent_transactions": [],
            }

        result = await session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.tenant_id == tenant_id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(10)
        )
        txns = result.scalars().all()

    return {
        "balance_cents": tenant.payg_credit_balance_cents,
        "balance_dollars": tenant.payg_credit_balance_cents / 100,
        "recent_transactions": [
            {
                "id": tx.id,
                "amount_cents": tx.amount_cents,
                "balance_after_cents": tx.balance_after_cents,
                "tx_type": tx.tx_type,
                "description": tx.description,
                "polar_order_id": tx.polar_order_id,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx in txns
        ],
    }


async def add_credits(
    tenant_id: str,
    amount_cents: int,
    polar_order_id: str = "",
    description: str = "",
) -> int:
    """Add credits to tenant balance. Returns new balance."""
    async with _get_raw_session() as session:
        result = await session.execute(
            text(
                "UPDATE tenants "
                "SET payg_credit_balance_cents = payg_credit_balance_cents + :amount, "
                "    updated_at = :now "
                "WHERE id = :tid "
                "RETURNING payg_credit_balance_cents"
            ),
            {
                "amount": amount_cents,
                "now": datetime.now(UTC).replace(tzinfo=None),
                "tid": tenant_id,
            },
        )
        row = result.fetchone()
        if not row:
            logger.warning("add_credits: tenant %s not found", tenant_id)
            return 0
        new_balance = row[0]

        session.add(CreditTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            amount_cents=amount_cents,
            balance_after_cents=new_balance,
            tx_type="purchase",
            description=description or f"Credit purchase (${amount_cents / 100:.2f})",
            polar_order_id=polar_order_id,
        ))
        await session.commit()

    logger.info(
        "Added %d cents to tenant %s (new balance: %d cents, order: %s)",
        amount_cents, tenant_id, new_balance, polar_order_id,
    )
    return new_balance


async def deduct_credits(
    tenant_id: str, cost_cents: int, overage_events: int,
) -> bool:
    """Deduct credits for overage events. Returns True on success, False if insufficient."""
    async with _get_raw_session() as session:
        result = await session.execute(
            text(
                "UPDATE tenants "
                "SET payg_credit_balance_cents = payg_credit_balance_cents - :cost, "
                "    updated_at = :now "
                "WHERE id = :tid AND payg_credit_balance_cents >= :cost "
                "RETURNING payg_credit_balance_cents"
            ),
            {"cost": cost_cents, "now": datetime.now(UTC).replace(tzinfo=None), "tid": tenant_id},
        )
        row = result.fetchone()
        if not row:
            return False
        new_balance = row[0]

        session.add(CreditTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            amount_cents=-cost_cents,
            balance_after_cents=new_balance,
            tx_type="overage_deduction",
            description=f"{overage_events} overage events ({cost_cents}c)",
        ))
        await session.commit()

    return True
