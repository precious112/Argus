"""Security scanning tools."""

from __future__ import annotations

from typing import Any

from argus_agent.tools.base import Tool, ToolRisk


class SecurityScanTool(Tool):
    """Run a security scan and return findings."""

    @property
    def name(self) -> str:
        return "security_scan"

    @property
    def description(self) -> str:
        return (
            "Run a security scan of the system. Checks open ports, failed SSH attempts, "
            "file permissions, suspicious processes, new executables in temp dirs, "
            "process lineage anomalies, and outbound connections. All checks are read-only."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific checks to run (default: all). Options: "
                        "open_ports, failed_ssh, file_permissions, "
                        "suspicious_processes, new_executables, "
                        "process_lineage, outbound_connections"
                    ),
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        try:
            from argus_agent.main import _get_security_scanner

            scanner = _get_security_scanner()
            if scanner is None:
                return {"error": "Security scanner not initialized"}

            results = await scanner.scan_once()
            results["display_type"] = "json_tree"
            return results
        except Exception as e:
            return {"error": f"Security scan failed: {e}"}


def register_security_tools() -> None:
    """Register security tools."""
    from argus_agent.tools.base import register_tool

    register_tool(SecurityScanTool())
