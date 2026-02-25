"""FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import Cookie, HTTPException, status

from argus_agent.auth.jwt import decode_access_token


async def get_current_user(argus_token: str = Cookie(default="")) -> dict:
    """Extract and verify the JWT from the argus_token cookie.

    Returns the decoded token payload or raises 401.
    """
    if not argus_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        return decode_access_token(argus_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
