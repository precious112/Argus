"""Tests for webhook HMAC-SHA256 signing and verification."""

from __future__ import annotations

import time

from argus_agent.webhooks.signing import sign_payload, verify_signature

SECRET = "test-secret-key-abc123"


def test_sign_and_verify_roundtrip():
    """sign_payload output should pass verify_signature."""
    payload = b'{"tool_name":"system_metrics","arguments":{}}'
    headers = sign_payload(payload, SECRET)

    assert headers["X-Argus-Signature"].startswith("sha256=")
    assert headers["X-Argus-Timestamp"]
    assert headers["X-Argus-Nonce"]

    assert verify_signature(
        payload=payload,
        secret=SECRET,
        signature=headers["X-Argus-Signature"],
        timestamp=headers["X-Argus-Timestamp"],
        nonce=headers["X-Argus-Nonce"],
    )


def test_verify_rejects_wrong_secret():
    payload = b'{"hello":"world"}'
    headers = sign_payload(payload, SECRET)
    assert not verify_signature(
        payload=payload,
        secret="wrong-secret",
        signature=headers["X-Argus-Signature"],
        timestamp=headers["X-Argus-Timestamp"],
        nonce=headers["X-Argus-Nonce"],
    )


def test_verify_rejects_tampered_payload():
    payload = b'{"hello":"world"}'
    headers = sign_payload(payload, SECRET)
    assert not verify_signature(
        payload=b'{"hello":"tampered"}',
        secret=SECRET,
        signature=headers["X-Argus-Signature"],
        timestamp=headers["X-Argus-Timestamp"],
        nonce=headers["X-Argus-Nonce"],
    )


def test_verify_rejects_stale_timestamp():
    """Timestamps older than max_age should be rejected."""
    payload = b'{"hello":"world"}'
    headers = sign_payload(payload, SECRET)
    # Patch the timestamp to be old
    old_ts = str(int(time.time()) - 600)
    # Re-sign with old timestamp for a valid signature
    import hashlib
    import hmac as _hmac

    nonce = headers["X-Argus-Nonce"]
    message = f"{old_ts}.{nonce}.".encode() + payload
    sig = "sha256=" + _hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()

    assert not verify_signature(
        payload=payload,
        secret=SECRET,
        signature=sig,
        timestamp=old_ts,
        nonce=nonce,
        max_age=300,
    )


def test_verify_rejects_invalid_timestamp():
    payload = b'{"hello":"world"}'
    headers = sign_payload(payload, SECRET)
    assert not verify_signature(
        payload=payload,
        secret=SECRET,
        signature=headers["X-Argus-Signature"],
        timestamp="not-a-number",
        nonce=headers["X-Argus-Nonce"],
    )


def test_verify_accepts_within_max_age():
    """A fresh signature should be accepted."""
    payload = b"test"
    headers = sign_payload(payload, SECRET)
    assert verify_signature(
        payload=payload,
        secret=SECRET,
        signature=headers["X-Argus-Signature"],
        timestamp=headers["X-Argus-Timestamp"],
        nonce=headers["X-Argus-Nonce"],
        max_age=5,
    )


def test_sign_different_payloads_produce_different_signatures():
    h1 = sign_payload(b"payload1", SECRET)
    h2 = sign_payload(b"payload2", SECRET)
    assert h1["X-Argus-Signature"] != h2["X-Argus-Signature"]


def test_sign_different_nonces_each_call():
    h1 = sign_payload(b"same", SECRET)
    h2 = sign_payload(b"same", SECRET)
    assert h1["X-Argus-Nonce"] != h2["X-Argus-Nonce"]
