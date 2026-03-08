"""Tests for alerting/escalation.py — policy matching, caching, email."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.alerting.escalation import (
    _extract_service_name,
    _matches_policy,
    _policy_cache,
    _render_escalation_email,
    _severity_index,
    notify_escalation_contacts,
)
from argus_agent.events.types import Event, EventSeverity, EventType

_MOD = "argus_agent.alerting.escalation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    severity: EventSeverity = EventSeverity.URGENT,
    event_type: str = EventType.CPU_HIGH,
    source: str = "system",
    data: dict | None = None,
    message: str = "test alert",
) -> Event:
    return Event(
        type=event_type,
        severity=severity,
        source=source,
        message=message,
        data=data or {},
    )


def _make_alert(
    *,
    severity: EventSeverity = EventSeverity.URGENT,
    rule_name: str = "CPU Critical",
    rule_id: str = "cpu_critical",
) -> MagicMock:
    alert = MagicMock()
    alert.severity = severity
    alert.rule_name = rule_name
    alert.rule_id = rule_id
    alert.timestamp = datetime(2025, 1, 15, 12, 0, 0)
    alert.id = "alert-123"
    return alert


def _make_policy(
    *,
    name: str = "On-call policy",
    service_name: str = "",
    min_severity: str = "",
    primary_contact_id: str = "user-1",
    backup_contact_id: str = "user-2",
) -> dict:
    return {
        "id": "policy-1",
        "name": name,
        "service_name": service_name,
        "min_severity": min_severity,
        "primary_contact_id": primary_contact_id,
        "backup_contact_id": backup_contact_id,
    }


# ---------------------------------------------------------------------------
# _severity_index
# ---------------------------------------------------------------------------


class TestSeverityIndex:
    def test_normal(self):
        assert _severity_index("NORMAL") == 0

    def test_notable(self):
        assert _severity_index("NOTABLE") == 1

    def test_urgent(self):
        assert _severity_index("URGENT") == 2

    def test_unknown(self):
        assert _severity_index("UNKNOWN") == -1

    def test_case_insensitive(self):
        assert _severity_index("notable") == 1


# ---------------------------------------------------------------------------
# _extract_service_name
# ---------------------------------------------------------------------------


class TestExtractServiceName:
    def test_service_name_key(self):
        event = _make_event(data={"service_name": "api-gw"})
        assert _extract_service_name(event) == "api-gw"

    def test_service_key(self):
        event = _make_event(data={"service": "payments"})
        assert _extract_service_name(event) == "payments"

    def test_fallback_to_source(self):
        event = _make_event(source="log_watcher", data={})
        assert _extract_service_name(event) == "log_watcher"

    def test_service_name_takes_precedence(self):
        event = _make_event(
            data={"service_name": "primary", "service": "secondary"},
        )
        assert _extract_service_name(event) == "primary"


# ---------------------------------------------------------------------------
# _matches_policy
# ---------------------------------------------------------------------------


class TestMatchesPolicy:
    def test_no_filters_matches_all(self):
        policy = _make_policy()
        event = _make_event()
        assert _matches_policy(policy, event, EventSeverity.URGENT)

    def test_service_match(self):
        policy = _make_policy(service_name="api-gw")
        event = _make_event(data={"service_name": "api-gw"})
        assert _matches_policy(policy, event, EventSeverity.NOTABLE)

    def test_service_reject(self):
        policy = _make_policy(service_name="api-gw")
        event = _make_event(data={"service_name": "payments"})
        assert not _matches_policy(policy, event, EventSeverity.NOTABLE)

    def test_service_case_insensitive(self):
        policy = _make_policy(service_name="API-GW")
        event = _make_event(data={"service_name": "api-gw"})
        assert _matches_policy(policy, event, EventSeverity.NOTABLE)

    def test_severity_match(self):
        policy = _make_policy(min_severity="NOTABLE")
        event = _make_event(severity=EventSeverity.URGENT)
        assert _matches_policy(policy, event, EventSeverity.URGENT)

    def test_severity_reject(self):
        policy = _make_policy(min_severity="URGENT")
        event = _make_event(severity=EventSeverity.NOTABLE)
        assert not _matches_policy(policy, event, EventSeverity.NOTABLE)

    def test_severity_exact_match(self):
        policy = _make_policy(min_severity="NOTABLE")
        event = _make_event(severity=EventSeverity.NOTABLE)
        assert _matches_policy(policy, event, EventSeverity.NOTABLE)

    def test_severity_above_min(self):
        policy = _make_policy(min_severity="NORMAL")
        event = _make_event(severity=EventSeverity.URGENT)
        assert _matches_policy(policy, event, EventSeverity.URGENT)


# ---------------------------------------------------------------------------
# _render_escalation_email
# ---------------------------------------------------------------------------


class TestRenderEscalationEmail:
    def test_returns_plain_and_html(self):
        alert = _make_alert()
        event = _make_event()
        plain, html = _render_escalation_email(
            alert, event, "On-call", "CPU high at 95%",
        )
        assert "[Argus Escalation]" in plain
        assert "On-call" in plain
        assert "CPU high at 95%" in plain
        assert "<html>" in html
        assert "On-call" in html

    def test_severity_color_urgent(self):
        alert = _make_alert(severity=EventSeverity.URGENT)
        event = _make_event(severity=EventSeverity.URGENT)
        _, html = _render_escalation_email(alert, event, "P", "msg")
        assert "#e74c3c" in html

    def test_severity_color_notable(self):
        alert = _make_alert(severity=EventSeverity.NOTABLE)
        event = _make_event(severity=EventSeverity.NOTABLE)
        _, html = _render_escalation_email(alert, event, "P", "msg")
        assert "#f39c12" in html


# ---------------------------------------------------------------------------
# notify_escalation_contacts (integration)
# ---------------------------------------------------------------------------

_SETTINGS = "argus_agent.config.get_settings"
_TENANT = "argus_agent.tenancy.context.get_tenant_id"
_SEND = "argus_agent.auth.email.send_email"


class TestNotifyEscalationContacts:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _policy_cache.clear()
        yield
        _policy_cache.clear()

    @pytest.mark.asyncio
    async def test_skips_self_hosted(self):
        """Should no-op in self-hosted mode."""
        alert = _make_alert()
        event = _make_event()

        with patch(_SETTINGS) as ms:
            ms.return_value.deployment.mode = "self_hosted"
            await notify_escalation_contacts(alert, event)

    @pytest.mark.asyncio
    async def test_skips_default_tenant(self):
        """Should no-op for default tenant."""
        alert = _make_alert()
        event = _make_event()

        with (
            patch(_SETTINGS) as ms,
            patch(_TENANT, return_value="default"),
        ):
            ms.return_value.deployment.mode = "saas"
            await notify_escalation_contacts(alert, event)

    @pytest.mark.asyncio
    async def test_sends_to_matching_contacts(self):
        """Should send emails to contacts from matching policies."""
        alert = _make_alert()
        event = _make_event()
        policy = _make_policy(
            primary_contact_id="u1", backup_contact_id="u2",
        )

        with (
            patch(_SETTINGS) as ms,
            patch(_TENANT, return_value="t1"),
            patch(
                f"{_MOD}._get_active_policies",
                new_callable=AsyncMock,
                return_value=[policy],
            ),
            patch(
                f"{_MOD}._resolve_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
            patch(
                _SEND,
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_send,
        ):
            ms.return_value.deployment.mode = "saas"
            mock_email.side_effect = lambda uid: f"{uid}@x.com"

            await notify_escalation_contacts(alert, event)

            assert mock_send.call_count == 2
            sent = {c.args[0] for c in mock_send.call_args_list}
            assert sent == {"u1@x.com", "u2@x.com"}

    @pytest.mark.asyncio
    async def test_deduplicates_contacts(self):
        """Same user in multiple policies → one email."""
        alert = _make_alert()
        event = _make_event()
        p1 = _make_policy(
            name="P1", primary_contact_id="u1",
            backup_contact_id="u2",
        )
        p2 = _make_policy(
            name="P2", primary_contact_id="u1",
            backup_contact_id="u3",
        )

        with (
            patch(_SETTINGS) as ms,
            patch(_TENANT, return_value="t1"),
            patch(
                f"{_MOD}._get_active_policies",
                new_callable=AsyncMock,
                return_value=[p1, p2],
            ),
            patch(
                f"{_MOD}._resolve_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
            patch(
                _SEND,
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_send,
        ):
            ms.return_value.deployment.mode = "saas"
            mock_email.side_effect = lambda uid: f"{uid}@x.com"

            await notify_escalation_contacts(alert, event)

            # u1 in both but deduped → 3 unique contacts
            assert mock_send.call_count == 3
            sent = {c.args[0] for c in mock_send.call_args_list}
            assert sent == {"u1@x.com", "u2@x.com", "u3@x.com"}

    @pytest.mark.asyncio
    async def test_no_op_when_no_policies_match(self):
        """No emails when no policies match."""
        alert = _make_alert(severity=EventSeverity.NOTABLE)
        event = _make_event(severity=EventSeverity.NOTABLE)
        policy = _make_policy(min_severity="URGENT")

        with (
            patch(_SETTINGS) as ms,
            patch(_TENANT, return_value="t1"),
            patch(
                f"{_MOD}._get_active_policies",
                new_callable=AsyncMock,
                return_value=[policy],
            ),
            patch(
                _SEND,
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            ms.return_value.deployment.mode = "saas"
            await notify_escalation_contacts(alert, event)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_html_kwarg_passed_to_send_email(self):
        """send_email should receive the html kwarg."""
        alert = _make_alert()
        event = _make_event()
        policy = _make_policy(
            primary_contact_id="u1", backup_contact_id="",
        )

        with (
            patch(_SETTINGS) as ms,
            patch(_TENANT, return_value="t1"),
            patch(
                f"{_MOD}._get_active_policies",
                new_callable=AsyncMock,
                return_value=[policy],
            ),
            patch(
                f"{_MOD}._resolve_user_email",
                new_callable=AsyncMock,
                return_value="u1@x.com",
            ),
            patch(
                _SEND,
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_send,
        ):
            ms.return_value.deployment.mode = "saas"
            await notify_escalation_contacts(alert, event)

            assert mock_send.call_count == 1
            _, kwargs = mock_send.call_args
            assert "html" in kwargs
            assert "<html>" in kwargs["html"]
