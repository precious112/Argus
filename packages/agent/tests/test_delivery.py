"""Tests for the reliable notification delivery wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from argus_agent.alerting import delivery
from argus_agent.alerting.delivery import channel_name, deliver


class _Slack:
    pass


class _WebhookChannel:
    pass


class _EmailChannel:
    pass


def test_channel_name_maps_known_types():
    assert channel_name(_Slack()) == "slack"
    assert channel_name(_WebhookChannel()) == "webhook"
    assert channel_name(_EmailChannel()) == "email"


@pytest.mark.asyncio
async def test_deliver_succeeds_first_try():
    send = AsyncMock(return_value=True)
    with patch.object(delivery, "_record_failure", new_callable=AsyncMock) as rec:
        result = await deliver(send, channel="slack", kind="urgent", delays=[0])
    assert result is True
    assert send.call_count == 1
    rec.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_retries_then_succeeds():
    # Fails (raises) twice, then succeeds on the third attempt.
    send = AsyncMock(side_effect=[RuntimeError("boom"), RuntimeError("boom"), True])
    with (
        patch.object(delivery.asyncio, "sleep", new_callable=AsyncMock),
        patch.object(delivery, "_record_failure", new_callable=AsyncMock) as rec,
    ):
        result = await deliver(send, channel="slack", kind="urgent", delays=[0, 0])
    assert result is True
    assert send.call_count == 3
    rec.assert_not_called()  # no failure recorded — it eventually delivered


@pytest.mark.asyncio
async def test_deliver_records_failure_after_exhausting_retries():
    send = AsyncMock(side_effect=RuntimeError("smtp down"))
    with (
        patch.object(delivery.asyncio, "sleep", new_callable=AsyncMock),
        patch.object(delivery, "_record_failure", new_callable=AsyncMock) as rec,
    ):
        result = await deliver(
            send, channel="email", kind="urgent", alert_id="a1",
            severity="URGENT", delays=[0, 0],
        )
    assert result is None  # never returned a successful value
    assert send.call_count == 3
    rec.assert_called_once()
    kwargs = rec.call_args.kwargs
    assert kwargs["channel"] == "email"
    assert kwargs["alert_id"] == "a1"
    assert kwargs["attempts"] == 3
    assert "smtp down" in kwargs["error"]


@pytest.mark.asyncio
async def test_deliver_treats_false_return_as_failure():
    # Channel returns False (its failure convention) on every attempt.
    send = AsyncMock(return_value=False)
    with (
        patch.object(delivery.asyncio, "sleep", new_callable=AsyncMock),
        patch.object(delivery, "_record_failure", new_callable=AsyncMock) as rec,
    ):
        result = await deliver(send, channel="webhook", kind="digest", delays=[0, 0])
    assert result is False
    assert send.call_count == 3
    rec.assert_called_once()


@pytest.mark.asyncio
async def test_deliver_preserves_dict_metadata_as_success():
    # send_urgent returns a thread-metadata dict — that's success, returned as-is.
    send = AsyncMock(return_value={"slack:C1": "123.45"})
    with patch.object(delivery, "_record_failure", new_callable=AsyncMock) as rec:
        result = await deliver(send, channel="slack", kind="urgent", delays=[0])
    assert result == {"slack:C1": "123.45"}
    assert send.call_count == 1
    rec.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_empty_dict_is_success_not_failure():
    # An empty dict (no thread metadata) is still a successful send, not a failure.
    send = AsyncMock(return_value={})
    with patch.object(delivery, "_record_failure", new_callable=AsyncMock) as rec:
        result = await deliver(send, channel="slack", kind="urgent", delays=[0])
    assert result == {}
    assert send.call_count == 1
    rec.assert_not_called()
