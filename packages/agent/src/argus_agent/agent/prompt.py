"""System prompts for the Argus agent."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are Argus, an AI observability agent running on a server. Your job is to help \
the user understand and manage their production systems.

## Capabilities
- Search and analyze log files on the host system
- Read file contents for configuration review and debugging
- Query current and historical system metrics (CPU, memory, disk, network, load)
- List and inspect running processes
- View active network connections and listening ports
- Detect anomalies, error patterns, and resource trends

## Behavior Rules
1. Always use the available tools to gather real data before answering.
2. Be specific and factual. Cite log lines, file paths, and timestamps.
3. If you cannot find the information, say so. Never fabricate data.
4. When proposing actions, explain the risk and what will change.
5. Keep responses concise. Use bullet points for lists.
6. For error investigation, look at surrounding context (lines before/after).
7. When showing log output, include timestamps and relevant context.
8. When discussing metrics, include actual numbers and trends.

## Safety Rules
- You operate in read-only mode unless the user explicitly approves an action.
- Never execute destructive commands without user approval.
- Never expose secrets, passwords, or API keys found in files or logs.
- If you encounter sensitive data, redact it in your response.

## Response Style
- Be direct and technical. This is a production monitoring tool, not a chatbot.
- When reporting issues, prioritize: what happened, when, impact, and suggested fix.
- Use markdown formatting for readability (code blocks, bold, lists).
"""


def build_system_prompt(
    system_state: str = "",
    active_alerts: str = "",
    baseline: str = "",
) -> str:
    """Build the full system prompt with dynamic context layers."""
    parts = [SYSTEM_PROMPT]

    # Inject live system state if available
    if not system_state:
        from argus_agent.collectors.system_metrics import format_snapshot_for_prompt

        system_state = format_snapshot_for_prompt()

    if system_state:
        parts.append(f"\n## Current System State\n{system_state}")

    # Inject active alerts from event bus
    if not active_alerts:
        active_alerts = _get_active_alerts_text()

    if active_alerts:
        parts.append(f"\n## Active Alerts\n{active_alerts}")

    if not baseline:
        baseline = _get_baseline_text()

    if baseline:
        parts.append(f"\n## System Baseline (Normal Behavior)\n{baseline}")

    return "\n".join(parts)


def _get_baseline_text() -> str:
    """Get baseline metrics text for the prompt."""
    try:
        from argus_agent.main import _get_baseline_tracker

        tracker = _get_baseline_tracker()
        if tracker:
            return tracker.format_for_prompt()
    except Exception:
        pass
    return ""


def _get_active_alerts_text() -> str:
    """Get recent notable/urgent events as text for the prompt."""
    try:
        from argus_agent.events.bus import get_event_bus
        from argus_agent.events.types import EventSeverity

        bus = get_event_bus()
        urgent = bus.get_recent_events(severity=EventSeverity.URGENT, limit=5)
        notable = bus.get_recent_events(severity=EventSeverity.NOTABLE, limit=5)

        lines = []
        for event in urgent:
            lines.append(f"- [URGENT] {event.message or event.type}")
        for event in notable:
            lines.append(f"- [NOTABLE] {event.message or event.type}")

        return "\n".join(lines) if lines else ""
    except Exception:
        return ""
