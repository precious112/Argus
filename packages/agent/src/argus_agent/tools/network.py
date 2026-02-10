"""Network connection tools."""

from __future__ import annotations

import logging
from typing import Any

import psutil

from argus_agent.tools.base import Tool, ToolRisk

logger = logging.getLogger("argus.tools.network")


class NetworkConnectionsTool(Tool):
    """Show active network connections and listening ports."""

    @property
    def name(self) -> str:
        return "network_connections"

    @property
    def description(self) -> str:
        return (
            "List active network connections and listening ports. "
            "Useful for debugging connectivity issues or finding what's using a port."
        )

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.READ_ONLY

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Connection type: all, tcp, udp, listening (default: all)",
                    "default": "all",
                },
                "filter_port": {
                    "type": "integer",
                    "description": "Filter by port number",
                },
                "filter_status": {
                    "type": "string",
                    "description": "Filter by status: ESTABLISHED, LISTEN, TIME_WAIT, etc.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max connections to return (default: 50)",
                    "default": 50,
                },
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kind = kwargs.get("kind", "all")
        filter_port = kwargs.get("filter_port")
        filter_status = kwargs.get("filter_status", "")
        limit = min(kwargs.get("limit", 50), 200)

        # Map our "kind" to psutil kinds
        psutil_kind = "inet"
        if kind == "tcp":
            psutil_kind = "tcp"
        elif kind == "udp":
            psutil_kind = "udp"

        connections: list[dict[str, Any]] = []
        try:
            for conn in psutil.net_connections(kind=psutil_kind):
                entry: dict[str, Any] = {
                    "status": conn.status,
                    "type": "TCP" if conn.type == 1 else "UDP",
                }

                if conn.laddr:
                    entry["local_addr"] = conn.laddr.ip
                    entry["local_port"] = conn.laddr.port
                if conn.raddr:
                    entry["remote_addr"] = conn.raddr.ip
                    entry["remote_port"] = conn.raddr.port

                entry["pid"] = conn.pid

                # Try to get process name
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        entry["process"] = proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        entry["process"] = ""

                connections.append(entry)
        except psutil.AccessDenied:
            return {"error": "Access denied. May need elevated privileges."}

        # Apply filters
        if kind == "listening":
            connections = [c for c in connections if c["status"] == "LISTEN"]
        if filter_port:
            connections = [
                c
                for c in connections
                if c.get("local_port") == filter_port or c.get("remote_port") == filter_port
            ]
        if filter_status:
            status_upper = filter_status.upper()
            connections = [c for c in connections if c.get("status") == status_upper]

        connections = connections[:limit]

        # Separate listening ports for summary
        listening = [c for c in connections if c.get("status") == "LISTEN"]

        return {
            "total_connections": len(connections),
            "listening_ports": len(listening),
            "connections": connections,
            "display_type": "process_table",
        }


def register_network_tools() -> None:
    """Register network tools."""
    from argus_agent.tools.base import register_tool

    register_tool(NetworkConnectionsTool())
