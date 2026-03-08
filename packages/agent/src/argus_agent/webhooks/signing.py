"""HMAC-SHA256 signing and verification for webhook payloads."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid


def sign_payload(payload: bytes, secret: str) -> dict[str, str]:
    """Generate signature headers for an outbound webhook payload.

    Returns a dict of HTTP headers to include in the request.
    """
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex[:16]
    message = f"{timestamp}.{nonce}.".encode() + payload
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "X-Argus-Signature": f"sha256={signature}",
        "X-Argus-Timestamp": timestamp,
        "X-Argus-Nonce": nonce,
    }


def verify_signature(
    payload: bytes,
    secret: str,
    signature: str,
    timestamp: str,
    nonce: str,
    max_age: int = 300,
) -> bool:
    """Verify an incoming webhook signature.

    Returns False if the signature is invalid, the timestamp is stale
    (older than *max_age* seconds), or any input is malformed.
    """
    # Validate timestamp is a number and within max_age
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    if abs(time.time() - ts) > max_age:
        return False

    # Recompute expected signature
    message = f"{timestamp}.{nonce}.".encode() + payload
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    expected_full = f"sha256={expected}"

    # Constant-time comparison
    return hmac.compare_digest(expected_full, signature)
