"""Email sending utilities for verification, password reset, etc."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

import aiosmtplib
import resend
from sqlalchemy import select, update

from argus_agent.config import get_settings
from argus_agent.storage.models import User
from argus_agent.storage.postgres_operational import get_raw_session
from argus_agent.storage.saas_models import EmailVerificationToken, PasswordResetToken

logger = logging.getLogger("argus.auth.email")


async def _send_via_resend(to: str, subject: str, body: str, *, html: str = "") -> bool:
    """Send an email via Resend API. Returns True on success."""
    settings = get_settings()
    resend.api_key = settings.deployment.resend_api_key

    try:
        params: resend.Emails.SendParams = {
            "from": settings.deployment.email_from,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        if html:
            params["html"] = html
        await asyncio.to_thread(resend.Emails.send, params)
        return True
    except Exception:
        logger.exception("Resend API failed for %s", to)
        return False


async def _send_via_smtp(to: str, subject: str, body: str, *, html: str = "") -> bool:
    """Send an email via SMTP. Returns True on success."""
    settings = get_settings()
    smtp_url = settings.deployment.smtp_url

    if not smtp_url:
        logger.warning("SMTP not configured, email to %s not sent: %s", to, subject)
        return False

    # Parse smtp_url: smtp://user:pass@host:port or smtps://user:pass@host:port
    from urllib.parse import urlparse

    parsed = urlparse(smtp_url)
    use_tls = parsed.scheme == "smtps"
    host = parsed.hostname or "localhost"
    port = parsed.port or (465 if use_tls else 587)
    username = parsed.username or ""
    password = parsed.password or ""

    msg = EmailMessage()
    msg["From"] = settings.deployment.email_from or f"noreply@{host}"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=username or None,
            password=password or None,
            use_tls=use_tls,
            start_tls=not use_tls and port == 587,
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s via SMTP", to)
        return False


async def send_email(to: str, subject: str, body: str, *, html: str = "") -> bool:
    """Send an email. Uses Resend API in SaaS mode (with SMTP fallback), SMTP only otherwise."""
    settings = get_settings()

    if settings.deployment.mode == "saas" and settings.deployment.resend_api_key:
        if await _send_via_resend(to, subject, body, html=html):
            return True
        logger.warning("Resend failed, falling back to SMTP for %s", to)

    return await _send_via_smtp(to, subject, body, html=html)


async def send_verification_email(user_id: str, email: str) -> str | None:
    """Generate a verification token and send the email. Returns token on success."""
    settings = get_settings()
    token = secrets.token_urlsafe(32)

    raw = get_raw_session()
    if not raw:
        return None
    async with raw as session:
        # Deactivate any existing tokens for this user
        await session.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC).replace(tzinfo=None))
        )

        vt = EmailVerificationToken(
            user_id=user_id,
            email=email,
            token=token,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
        )
        session.add(vt)
        await session.commit()

    verify_url = (
        f"{settings.deployment.frontend_url}/verify-email?"
        + urlencode({"token": token})
    )

    body = (
        f"Welcome to Argus!\n\n"
        f"Please verify your email by clicking the link below:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in 24 hours.\n\n"
        f"If you didn't create an account, you can safely ignore this email."
    )

    sent = await send_email(email, "Verify your Argus email", body)
    return token if sent else None


async def verify_email_token(token: str) -> dict:
    """Verify an email token. Returns ok/error dict."""
    raw = get_raw_session()
    if not raw:
        return {"ok": False, "error": "Database not initialized"}
    async with raw as session:
        result = await session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token == token,
                EmailVerificationToken.used_at.is_(None),
            )
        )
        vt = result.scalar_one_or_none()

        if not vt:
            return {"ok": False, "error": "Invalid or already used token"}

        if vt.expires_at < datetime.now(UTC).replace(tzinfo=None):
            return {"ok": False, "error": "Token has expired"}

        # Mark token as used
        vt.used_at = datetime.now(UTC).replace(tzinfo=None)

        # Mark user email as verified
        await session.execute(
            update(User).where(User.id == vt.user_id).values(email_verified=True)
        )

        await session.commit()

    return {"ok": True, "user_id": vt.user_id}


async def send_password_reset_email(email: str) -> bool:
    """Generate a password reset token and send the email."""
    settings = get_settings()

    raw = get_raw_session()
    if not raw:
        return True  # Fail silently — don't reveal DB status
    async with raw as session:
        result = await session.execute(
            select(User).where(User.email == email, User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()

        if not user:
            # Don't reveal whether email exists
            return True

        token = secrets.token_urlsafe(32)

        # Deactivate existing tokens
        await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC).replace(tzinfo=None))
        )

        prt = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        session.add(prt)
        await session.commit()

    reset_url = (
        f"{settings.deployment.frontend_url}/reset-password?"
        + urlencode({"token": token})
    )

    body = (
        f"You requested a password reset for your Argus account.\n\n"
        f"Click the link below to reset your password:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )

    await send_email(email, "Reset your Argus password", body)
    return True


async def verify_reset_token(token: str) -> dict:
    """Verify a password reset token. Returns {"ok": True, "user_id": ...} or error."""
    raw = get_raw_session()
    if not raw:
        return {"ok": False, "error": "Database not initialized"}
    async with raw as session:
        result = await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.used_at.is_(None),
            )
        )
        prt = result.scalar_one_or_none()

        if not prt:
            return {"ok": False, "error": "Invalid or already used token"}

        if prt.expires_at < datetime.now(UTC).replace(tzinfo=None):
            return {"ok": False, "error": "Token has expired"}

    return {"ok": True, "user_id": prt.user_id, "token": token}


async def consume_reset_token(token: str, new_password_hash: str) -> dict:
    """Use a reset token to change the user's password."""
    raw = get_raw_session()
    if not raw:
        return {"ok": False, "error": "Database not initialized"}
    async with raw as session:
        result = await session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.used_at.is_(None),
            )
        )
        prt = result.scalar_one_or_none()

        if not prt:
            return {"ok": False, "error": "Invalid or already used token"}

        if prt.expires_at < datetime.now(UTC).replace(tzinfo=None):
            return {"ok": False, "error": "Token has expired"}

        # Mark token as used
        prt.used_at = datetime.now(UTC).replace(tzinfo=None)

        # Update password
        await session.execute(
            update(User).where(User.id == prt.user_id).values(password_hash=new_password_hash)
        )

        await session.commit()

    return {"ok": True, "user_id": prt.user_id}


async def send_usage_notification_email(
    to: str, tenant_name: str, threshold: str, **kwargs: str | int | float | bool
) -> bool:
    """Send a usage threshold notification email.

    *threshold* is one of: quota_80, quota_100, credits_low, credits_near_zero.
    Extra keyword args are interpolated into the message body.
    """
    subjects: dict[str, str] = {
        "quota_80": f"[Argus] {tenant_name}: 80% of monthly event quota used",
        "quota_100": f"[Argus] {tenant_name}: Monthly event quota exceeded",
        "credits_low": f"[Argus] {tenant_name}: Credit balance below $1.00",
        "credits_near_zero": f"[Argus] {tenant_name}: Credit balance nearly exhausted",
    }

    current = kwargs.get("current", 0)
    limit = kwargs.get("limit", 0)
    has_credits = kwargs.get("has_credits", False)
    balance_cents = kwargs.get("balance_cents", 0)

    bodies: dict[str, str] = {
        "quota_80": (
            f"You've used 80% of your monthly event quota "
            f"({current:,}/{limit:,}).\n\n"
            "Consider purchasing prepaid credits to avoid disruption when "
            "you reach your limit."
        ),
        "quota_100": (
            f"You've exceeded your plan quota ({current:,}/{limit:,} events).\n\n"
            + (
                "Prepaid credits are being used for overage events "
                "at $0.30 per 1,000 events."
                if has_credits
                else "Event ingestion is now blocked. Purchase credits or "
                "upgrade your plan to continue ingesting events."
            )
        ),
        "credits_low": (
            f"Your credit balance is below $1.00 "
            f"(${int(balance_cents) / 100:.2f} remaining).\n\n"
            "Purchase more credits to avoid event rejection when your "
            "balance runs out."
        ),
        "credits_near_zero": (
            f"Your credit balance is nearly exhausted "
            f"(${int(balance_cents) / 100:.2f} remaining).\n\n"
            "Events will be rejected once your credits run out. "
            "Purchase more credits now to continue ingesting."
        ),
    }

    subject = subjects.get(threshold, f"[Argus] {tenant_name}: Usage notification")
    body = bodies.get(threshold, "You have a usage notification from Argus.")

    return await send_email(to, subject, body)
