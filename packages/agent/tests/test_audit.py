"""Tests for audit logger."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_agent.actions.audit import AuditLogger


class TestAuditLogger:
    def setup_method(self):
        self.logger = AuditLogger()

    @pytest.mark.asyncio
    async def test_log_action(self):
        mock_entry = MagicMock()
        mock_entry.id = 1

        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        # Make the entry's id accessible after add
        def set_id(entry):
            entry.id = 1
        mock_session.add.side_effect = set_id

        with patch("argus_agent.actions.audit.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            entry_id = await self.logger.log_action(
                action="test_action",
                command="echo hello",
                result="ok",
                success=True,
            )
            assert entry_id == 1
            mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_audit_log(self):
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.timestamp = MagicMock()
        mock_row.timestamp.isoformat.return_value = "2024-01-01T00:00:00"
        mock_row.action = "test"
        mock_row.command = "echo"
        mock_row.result = "ok"
        mock_row.success = True
        mock_row.user_approved = False
        mock_row.ip_address = ""
        mock_row.conversation_id = ""

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("argus_agent.actions.audit.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            entries = await self.logger.get_audit_log(limit=10, offset=0)
            assert len(entries) == 1
            assert entries[0]["action"] == "test"

    @pytest.mark.asyncio
    async def test_log_action_with_all_fields(self):
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock(side_effect=lambda e: setattr(e, 'id', 42))

        with patch("argus_agent.actions.audit.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            entry_id = await self.logger.log_action(
                action="restart_nginx",
                command="systemctl restart nginx",
                result="success",
                success=True,
                user_approved=True,
                ip_address="127.0.0.1",
                conversation_id="conv-123",
            )
            assert entry_id == 42

    @pytest.mark.asyncio
    async def test_get_audit_log_empty(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("argus_agent.actions.audit.get_session") as mock_get:
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=False)

            entries = await self.logger.get_audit_log()
            assert entries == []
