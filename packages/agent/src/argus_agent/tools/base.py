"""Tool base class and registry for agent tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from argus_agent.llm.base import ToolDefinition


def resolve_time_range(
    since_minutes: int = 60,
    since: str | None = None,
    until: str | None = None,
) -> tuple[datetime, datetime | None]:
    """Convert since_minutes / since / until params to datetime objects.

    When ``since`` (ISO datetime string) is provided it replaces the
    ``since_minutes`` look-back computation.  ``until`` independently adds
    an upper-bound.  Both are optional.
    """
    if since:
        since_dt = datetime.fromisoformat(since)
    else:
        since_dt = datetime.now(UTC) - timedelta(minutes=since_minutes)
    until_dt = datetime.fromisoformat(until) if until else None
    return since_dt, until_dt


class ToolRisk(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Tool(ABC):
    """Base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def risk(self) -> ToolRisk: ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]: ...

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )


_tools: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    _tools[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _tools.get(name)


def get_all_tools() -> list[Tool]:
    return list(_tools.values())


def get_tool_definitions() -> list[ToolDefinition]:
    return [t.to_definition() for t in _tools.values()]
