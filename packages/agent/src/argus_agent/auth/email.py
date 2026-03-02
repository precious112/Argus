"""Email sending utilities for verification, password reset, etc."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

import aiosmtplib
from sqlalchemy import select, update

from argus_agent.config import get_settings
from argus_agent.storage.models import User
from argus_agent.storage.repositories import get_session
from argus_agent.storage.saas_models import EmailVerificationToken, PasswordResetToken

logger = logging.getLogger("argus.auth.email")


async def send_email(to: str, subject: str, body: str) -> bool:
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
    msg["From"] = settings.alerting.email_from or f"noreply@{host}"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

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
        logger.exception("Failed to send email to %s", to)
        return False


async def send_verification_email(user_id: str, email: str) -> str | None:
    """Generate a verification token and send the email. Returns token on success."""
    settings = get_settings()
    token = secrets.token_urlsafe(32)

    async with get_session() as session:
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
    async with get_session() as session:
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

    async with get_session() as session:
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
    async with get_session() as session:
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
    async with get_session() as session:
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
