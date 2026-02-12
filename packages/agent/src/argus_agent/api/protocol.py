"""WebSocket chat protocol message type definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# --- Client → Server Messages ---


class ClientMessageType(StrEnum):
    USER_MESSAGE = "user_message"
    ACTION_RESPONSE = "action_response"
    CANCEL = "cancel"
    PING = "ping"


class ClientMessage(BaseModel):
    type: ClientMessageType
    id: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# --- Server → Client Messages ---


class ServerMessageType(StrEnum):
    CONNECTED = "connected"
    SYSTEM_STATUS = "system_status"
    THINKING_START = "thinking_start"
    THINKING_END = "thinking_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ASSISTANT_MESSAGE_START = "assistant_message_start"
    ASSISTANT_MESSAGE_DELTA = "assistant_message_delta"
    ASSISTANT_MESSAGE_END = "assistant_message_end"
    ACTION_REQUEST = "action_request"
    ACTION_EXECUTING = "action_executing"
    ACTION_COMPLETE = "action_complete"
    ALERT = "alert"
    INVESTIGATION_START = "investigation_start"
    INVESTIGATION_UPDATE = "investigation_update"
    INVESTIGATION_END = "investigation_end"
    BUDGET_UPDATE = "budget_update"
    ERROR = "error"
    PONG = "pong"


class ToolResultDisplayType(StrEnum):
    """Rich display types for tool results in the chat UI."""

    LOG_VIEWER = "log_viewer"
    METRICS_CHART = "metrics_chart"
    PROCESS_TABLE = "process_table"
    JSON_TREE = "json_tree"
    CODE_BLOCK = "code_block"
    DIFF_VIEW = "diff_view"
    TABLE = "table"
    TEXT = "text"
    CHART = "chart"


class ServerMessage(BaseModel):
    type: ServerMessageType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class ActionRequest(BaseModel):
    """A proposed action that needs user approval."""

    id: str
    tool: str
    description: str
    command: list[str] | str
    risk_level: str  # READ_ONLY, LOW, MEDIUM, HIGH, CRITICAL
    reversible: bool = False
    requires_password: bool = False


class AlertMessage(BaseModel):
    """An alert notification sent to the client."""

    id: str
    severity: str  # CRITICAL, WARNING, INFO
    title: str
    summary: str
    source: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    investigation_thread_id: str | None = None
