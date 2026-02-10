"""Log search and tail tools."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from argus_agent.config import get_settings
from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.log")

MAX_RESULTS = 100
MAX_LINE_LENGTH = 500


def _resolve_path(file_path: str) -> Path:
    """Resolve a log file path, prepending host root if configured."""
    settings = get_settings()
    host_root = settings.collector.host_root
    if host_root and not file_path.startswith(host_root):
        return Path(host_root) / file_path.lstrip("/")
    return Path(file_path)


class LogSearchTool(Tool):
    """Search log files by pattern, time range, or severity."""

    @property
    def name(self) -> str:
        return "log_search"

    @property
    def description(self) -> str:
        return (
            "Search log files for lines matching a pattern (regex or plain text). "
            "Returns matching lines with context. Use this to investigate errors, "
            "find specific events, or analyze patterns in log files."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (regex supported)",
                },
                "file": {
                    "type": "string",
                    "description": "Log file path to search (e.g., /var/log/syslog)",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines before/after each match (default: 2)",
                    "default": 2,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 50)",
                    "default": 50,
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: true)",
                    "default": True,
                },
            },
            "required": ["pattern", "file"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        pattern = kwargs["pattern"]
        file_path = kwargs["file"]
        context_lines = min(kwargs.get("context_lines", 2), 10)
        max_results = min(kwargs.get("max_results", 50), MAX_RESULTS)
        case_insensitive = kwargs.get("case_insensitive", True)

        resolved = _resolve_path(file_path)

        if not resolved.exists():
            return {"error": f"File not found: {file_path}", "matches": []}

        if not resolved.is_file():
            return {"error": f"Not a file: {file_path}", "matches": []}

        try:
            flags = re.IGNORECASE if case_insensitive else 0
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return {"error": f"Invalid regex pattern: {e}", "matches": []}

        matches = []
        try:
            lines = resolved.read_text(errors="replace").splitlines()
            for i, line in enumerate(lines):
                if compiled.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    context = [
                        {
                            "line_number": start + j + 1,
                            "text": lines[start + j][:MAX_LINE_LENGTH],
                            "is_match": start + j == i,
                        }
                        for j in range(end - start)
                    ]
                    matches.append(
                        {
                            "line_number": i + 1,
                            "text": line[:MAX_LINE_LENGTH],
                            "context": context,
                        }
                    )
                    if len(matches) >= max_results:
                        break
        except PermissionError:
            return {"error": f"Permission denied: {file_path}", "matches": []}
        except OSError as e:
            return {"error": f"Error reading {file_path}: {e}", "matches": []}

        return {
            "file": file_path,
            "pattern": pattern,
            "total_matches": len(matches),
            "truncated": len(matches) >= max_results,
            "matches": matches,
            "display_type": "log_viewer",
        }


class LogTailTool(Tool):
    """Get the latest N lines from a log file."""

    @property
    def name(self) -> str:
        return "log_tail"

    @property
    def description(self) -> str:
        return (
            "Get the latest lines from a log file. Use this to see recent activity, "
            "check for current errors, or monitor what's happening right now."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Log file path (e.g., /var/log/syslog)",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default: 50, max: 200)",
                    "default": 50,
                },
            },
            "required": ["file"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        file_path = kwargs["file"]
        num_lines = min(kwargs.get("lines", 50), 200)

        resolved = _resolve_path(file_path)

        if not resolved.exists():
            return {"error": f"File not found: {file_path}", "lines": []}

        if not resolved.is_file():
            return {"error": f"Not a file: {file_path}", "lines": []}

        try:
            all_lines = resolved.read_text(errors="replace").splitlines()
            tail = all_lines[-num_lines:]
            result_lines = [
                {
                    "line_number": len(all_lines) - len(tail) + i + 1,
                    "text": line[:MAX_LINE_LENGTH],
                }
                for i, line in enumerate(tail)
            ]
        except PermissionError:
            return {"error": f"Permission denied: {file_path}", "lines": []}
        except OSError as e:
            return {"error": f"Error reading {file_path}: {e}", "lines": []}

        return {
            "file": file_path,
            "total_lines": len(all_lines),
            "returned": len(result_lines),
            "lines": result_lines,
            "display_type": "log_viewer",
        }


class FileReadTool(Tool):
    """Read a file's contents."""

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file. Use this for configuration files, scripts, "
            "or any text file on the system. Useful for reviewing config when debugging issues."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to read",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Starting line number (1-based, default: 1)",
                    "default": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": ("Ending line number (inclusive, default: read entire file)"),
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum lines to return (default: 200)",
                    "default": 200,
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        file_path = kwargs["path"]
        start_line = max(kwargs.get("start_line", 1), 1)
        max_lines = min(kwargs.get("max_lines", 200), 500)

        resolved = _resolve_path(file_path)

        if not resolved.exists():
            return {"error": f"File not found: {file_path}"}

        if not resolved.is_file():
            return {"error": f"Not a file: {file_path}"}

        # Check file size - refuse very large binary files
        size = resolved.stat().st_size
        if size > 10 * 1024 * 1024:  # 10MB
            return {"error": f"File too large ({size} bytes). Use log_search for large files."}

        try:
            all_lines = resolved.read_text(errors="replace").splitlines()
        except PermissionError:
            return {"error": f"Permission denied: {file_path}"}
        except OSError as e:
            return {"error": f"Error reading {file_path}: {e}"}

        end_line = kwargs.get("end_line", start_line + max_lines - 1)
        end_line = min(end_line, start_line + max_lines - 1, len(all_lines))

        selected = all_lines[start_line - 1 : end_line]
        content = "\n".join(selected)

        return {
            "path": file_path,
            "total_lines": len(all_lines),
            "start_line": start_line,
            "end_line": end_line,
            "content": content,
            "display_type": "code_block",
        }


def register_log_tools() -> None:
    """Register all log-related tools."""
    from argus_agent.tools.base import register_tool

    register_tool(LogSearchTool())
    register_tool(LogTailTool())
    register_tool(FileReadTool())
