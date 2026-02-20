"""Rich terminal output formatting."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_status(data: dict[str, Any]) -> None:
    """Print system status as a rich panel with tables."""
    system = data.get("system", {})
    collectors = data.get("collectors", {})

    table = Table(title="System Status", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    if system:
        table.add_row("CPU", f"{system.get('cpu_percent', 'N/A')}%")
        table.add_row("Memory", f"{system.get('memory_percent', 'N/A')}%")
        table.add_row("Disk", f"{system.get('disk_percent', 'N/A')}%")
        table.add_row("Load Avg", str(system.get("load_avg", "N/A")))

    console.print(table)

    if collectors:
        ct = Table(title="Collectors", show_header=True, header_style="bold green")
        ct.add_column("Collector")
        ct.add_column("Status")
        for name, status in collectors.items():
            color = "green" if status == "running" else "red"
            ct.add_row(name, f"[{color}]{status}[/{color}]")
        console.print(ct)

    agent = data.get("agent", {})
    if agent:
        console.print(f"\nLLM Provider: [bold]{agent.get('llm_provider', 'N/A')}[/bold]")


def print_alerts(alerts: list[dict[str, Any]]) -> None:
    """Print alerts as a color-coded table."""
    if not alerts:
        console.print("[dim]No active alerts.[/dim]")
        return

    table = Table(title="Alerts", show_header=True, header_style="bold yellow")
    table.add_column("ID", style="dim")
    table.add_column("Severity")
    table.add_column("Message")
    table.add_column("Source")
    table.add_column("Time")

    for a in alerts:
        sev = a.get("severity", "")
        if "URGENT" in sev or "CRITICAL" in sev:
            color = "red"
        elif "NOTABLE" in sev or "WARNING" in sev:
            color = "yellow"
        else:
            color = "white"

        table.add_row(
            str(a.get("id", ""))[:8],
            f"[{color}]{sev}[/{color}]",
            a.get("message", a.get("rule_name", "")),
            a.get("source", ""),
            a.get("timestamp", "")[:19],
        )

    console.print(table)


def print_processes(procs: list[dict[str, Any]]) -> None:
    """Print process list as a table."""
    if not procs:
        console.print("[dim]No processes found.[/dim]")
        return

    table = Table(title="Processes", show_header=True, header_style="bold magenta")
    table.add_column("PID", justify="right")
    table.add_column("Name")
    table.add_column("CPU %", justify="right")
    table.add_column("MEM %", justify="right")
    table.add_column("User")

    for p in procs[:25]:
        table.add_row(
            str(p.get("pid", "")),
            p.get("name", ""),
            f"{p.get('cpu_percent', 0):.1f}",
            f"{p.get('memory_percent', 0):.1f}",
            p.get("username", ""),
        )

    console.print(table)


def print_logs(entries: list[dict[str, Any]]) -> None:
    """Print log entries."""
    if not entries:
        console.print("[dim]No log entries found.[/dim]")
        return

    for entry in entries:
        sev = entry.get("severity", "INFO")
        color = "red" if sev == "ERROR" else "yellow" if sev == "WARNING" else "white"
        ts = entry.get("timestamp", "")[:19]
        msg = entry.get("message_preview", "")
        console.print(f"[dim]{ts}[/dim] [{color}]{sev:>7}[/{color}] {msg}")


def print_metrics(data: dict[str, float]) -> None:
    """Print latest metrics as a table."""
    if not data:
        console.print("[dim]No metrics available.[/dim]")
        return

    table = Table(title="Metrics", show_header=True, header_style="bold blue")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    for name, value in sorted(data.items()):
        table.add_row(name, f"{value:.2f}")

    console.print(table)


def print_services(services: list[dict[str, Any]]) -> None:
    """Print SDK services as a table."""
    if not services:
        console.print("[dim]No SDK services found.[/dim]")
        return

    table = Table(title="SDK Services", show_header=True, header_style="bold green")
    table.add_column("Service", style="bold")
    table.add_column("Events", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Invocations", justify="right")
    table.add_column("Last Seen")

    for s in services:
        error_count = s.get("error_count", 0)
        error_style = "red" if error_count > 0 else "green"
        table.add_row(
            s.get("service", ""),
            str(s.get("event_count", 0)),
            f"[{error_style}]{error_count}[/{error_style}]",
            str(s.get("invocation_count", 0)),
            s.get("last_seen", "")[:19],
        )

    console.print(table)


def print_answer(text: str) -> None:
    """Print an agent response."""
    console.print(Panel(text, title="Argus", border_style="cyan"))


def print_config(data: dict[str, Any]) -> None:
    """Print LLM configuration as a rich table."""
    llm = data.get("llm", {})

    table = Table(title="LLM Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Provider", llm.get("provider", "N/A"))
    table.add_row("Model", llm.get("model", "N/A"))

    key_set = llm.get("api_key_set", False)
    key_status = "[green]configured[/green]" if key_set else "[red]not set[/red]"
    table.add_row("API Key", key_status)

    table.add_row("Status", llm.get("status", "unknown"))

    source = llm.get("source", "unknown")
    source_style = "green" if source == "db" else "yellow"
    table.add_row("Source", f"[{source_style}]{source}[/{source_style}]")

    console.print(table)

    providers = llm.get("providers", [])
    if providers:
        console.print(f"\nAvailable providers: [bold]{', '.join(providers)}[/bold]")


def print_config_update(data: dict[str, Any]) -> None:
    """Print confirmation after LLM settings update."""
    console.print("[bold green]LLM settings updated successfully.[/bold green]")
    table = Table(show_header=False)
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("Provider", data.get("provider", ""))
    table.add_row("Model", data.get("model", ""))
    key_set = data.get("api_key_set", False)
    table.add_row("API Key", "[green]configured[/green]" if key_set else "[red]not set[/red]")
    console.print(table)
