"""Interactive chat mode via WebSocket with rich rendering."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

console = Console()

SLASH_COMMANDS = {
    "/help": "Show available commands",
    "/status": "Show system status",
    "/alerts": "Show active alerts",
    "/logs": "Show recent logs",
    "/ps": "Show top processes",
    "/services": "Show SDK services",
    "/quit": "Exit the chat session",
    "/exit": "Exit the chat session",
}


def _print_help() -> None:
    """Print available slash commands."""
    table = Table(title="Slash Commands", show_header=True, header_style="bold cyan")
    table.add_column("Command", style="bold")
    table.add_column("Description")
    for cmd, desc in SLASH_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)


async def _handle_slash_command(cmd: str, server_url: str) -> bool:
    """Handle a slash command. Returns True if handled."""
    cmd = cmd.strip().lower()

    if cmd in ("/quit", "/exit"):
        console.print("[dim]Goodbye![/dim]")
        return True  # signals exit

    if cmd == "/help":
        _print_help()
        return False

    from argus_cli.api import ArgusAPI

    api = ArgusAPI(server_url)
    try:
        if cmd == "/status":
            from argus_cli.display import print_status
            data = api.status()
            print_status(data)
        elif cmd == "/alerts":
            from argus_cli.display import print_alerts
            data = api.alerts()
            print_alerts(data.get("alerts", []))
        elif cmd == "/logs":
            from argus_cli.display import print_logs
            data = api.logs(limit=20)
            print_logs(data.get("entries", []))
        elif cmd == "/ps":
            from argus_cli.display import print_processes
            data = api.status()
            procs = data.get("system", {}).get("top_processes", [])
            print_processes(procs)
        elif cmd == "/services":
            from argus_cli.display import print_services
            data = api.services()
            print_services(data.get("services", []))
        else:
            console.print(f"[yellow]Unknown command: {cmd}[/yellow]")
            _print_help()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
    finally:
        api.close()

    return False


def _render_status_line(snapshot: dict[str, Any], mode: str = "") -> None:
    """Render a compact status line on connect."""
    if mode == "sdk_only":
        console.print(
            "[dim]Mode:[/dim] [cyan]SDK-only[/cyan]  "
            "[dim]Type /help for commands[/dim]"
        )
        return

    cpu = snapshot.get("cpu_percent", "?")
    mem = snapshot.get("memory_percent", "?")
    disk = snapshot.get("disk_percent", "?")
    console.print(
        f"[dim]CPU:[/dim] {cpu}%  "
        f"[dim]MEM:[/dim] {mem}%  "
        f"[dim]Disk:[/dim] {disk}%  "
        f"[dim]Type /help for commands[/dim]"
    )


def _ensure_token(server_url: str) -> str | None:
    """Ensure we have a valid auth token, prompting for login if needed."""
    from argus_cli.auth import clear_token, load_token, login

    token = load_token(server_url)
    if token:
        return token

    console.print("[yellow]Authentication required.[/yellow]")
    try:
        username = input("  Username: ").strip()
        import getpass
        password = getpass.getpass("  Password: ")
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Login cancelled.[/dim]")
        return None

    try:
        token = login(server_url, username, password)
        console.print("[green]Login successful.[/green]")
        return token
    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")
        return None


async def start_chat(server_url: str) -> None:
    """Connect to Argus WebSocket and run an interactive chat loop."""
    try:
        import websockets
    except ImportError:
        console.print("[red]websockets package required for chat mode[/red]")
        return

    ws_url = server_url.replace("http://", "ws://").replace("https://", "wss://")
    if not ws_url.endswith("/ws"):
        ws_url = ws_url.rstrip("/") + "/api/v1/ws"

    # Add client=cli query parameter
    ws_url += "?client=cli"

    _BANNER_LINES = [
        r" █████╗ ██████╗  ██████╗ ██╗   ██╗███████╗",
        r"██╔══██╗██╔══██╗██╔════╝ ██║   ██║██╔════╝",
        r"███████║██████╔╝██║  ███╗██║   ██║███████╗",
        r"██╔══██║██╔══██╗██║   ██║██║   ██║╚════██║",
        r"██║  ██║██║  ██║╚██████╔╝╚██████╔╝███████║",
        r"╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝",
    ]
    _BANNER_COLORS = [
        "#FFFFFF",
        "#CCE0FF",
        "#99C2FF",
        "#5599FF",
        "#2266CC",
        "#0044AA",
    ]
    styled_banner = "\n".join(
        f"[bold {color}]{line}[/bold {color}]"
        for line, color in zip(_BANNER_LINES, _BANNER_COLORS)
    )
    styled_banner += "\n[dim]v0.1.0[/dim]"
    console.print(Panel(
        styled_banner,
        subtitle="Ctrl+C to quit",
        border_style="cyan",
    ))

    # Authenticate before connecting
    token = _ensure_token(server_url)
    if not token:
        return

    console.print(f"[dim]Connecting to {server_url}...[/dim]")

    try:
        extra_headers = {"Cookie": f"argus_token={token}"}
        async with websockets.connect(
            ws_url,
            additional_headers=extra_headers,
            ping_interval=30,
            ping_timeout=120,
        ) as ws:
            # Read the connected message
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") == "connected":
                console.print("[green]Connected to Argus agent[/green]")

            # Read system status if sent
            snapshot: dict[str, Any] = {}
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                msg = json.loads(raw)
                if msg.get("type") == "system_status":
                    snapshot = msg.get("data", {})
            except asyncio.TimeoutError:
                pass

            _render_status_line(snapshot)
            console.print()

            # Set up prompt_toolkit session
            session: PromptSession[str] = PromptSession(
                history=InMemoryHistory(),
            )

            while True:
                try:
                    with patch_stdout():
                        user_input = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: session.prompt("You> "),
                        )
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Goodbye![/dim]")
                    break

                if not user_input.strip():
                    continue

                # Handle slash commands
                if user_input.strip().startswith("/"):
                    should_exit = await _handle_slash_command(user_input.strip(), server_url)
                    if should_exit:
                        break
                    continue

                # Send user message
                await ws.send(json.dumps({
                    "type": "user_message",
                    "id": "",
                    "data": {"content": user_input},
                }))

                # Stream response with spinner then markdown
                await _stream_response(ws, server_url)

    except Exception as e:
        err_str = str(e)
        if "403" in err_str or "4001" in err_str or "Authentication" in err_str:
            from argus_cli.auth import clear_token

            clear_token(server_url)
            console.print("[yellow]Session expired or invalid. Please log in again.[/yellow]")
            token = _ensure_token(server_url)
            if token:
                console.print("[dim]Reconnecting...[/dim]")
                await start_chat(server_url)
        else:
            console.print(f"[red]Connection failed: {e}[/red]")


async def _stream_response(ws: Any, server_url: str) -> None:
    """Stream and render the agent response with live markdown."""
    segment_content = ""  # Current text segment (reset on tool interruptions)
    done = False
    streaming = False

    def _new_live(renderable: Any = None) -> Live:
        r = renderable or Spinner("dots", text="Thinking...")
        return Live(r, console=console, refresh_per_second=8, transient=False)

    live = _new_live()
    live.start()

    while not done:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "assistant_message_delta":
                content = msg.get("data", {}).get("content", "")
                if content:
                    streaming = True
                    segment_content += content
                    live.update(Markdown(segment_content))

            elif msg_type == "assistant_message_end":
                done = True

            elif msg_type == "tool_call":
                name = msg.get("data", {}).get("name", "")
                if streaming:
                    live.stop()
                    segment_content = ""
                    streaming = False
                    live = _new_live(Spinner("dots", text=f"Calling {name}..."))
                    live.start()
                else:
                    live.update(Spinner("dots", text=f"Calling {name}..."))

            elif msg_type == "tool_result":
                data = msg.get("data", {})
                display_type = data.get("display_type", "")
                name = data.get("name", "")
                result = data.get("result", {})

                live.stop()
                _render_tool_result(name, result, display_type)
                segment_content = ""
                streaming = False
                live = _new_live(Spinner("dots", text="Processing..."))
                live.start()

            elif msg_type == "action_request":
                live.stop()
                segment_content = ""
                streaming = False

                data = msg.get("data", {})
                risk = data.get("risk_level", "")
                desc = data.get("description", "")
                cmd = data.get("command", [])
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

                risk_color = "red" if risk in ("HIGH", "CRITICAL") else "yellow"
                console.print()
                console.print(Panel(
                    f"[bold]{desc}[/bold]\n"
                    f"Command: [code]{cmd_str}[/code]\n"
                    f"Risk: [{risk_color}]{risk}[/{risk_color}]",
                    title="Action Approval Required",
                    border_style=risk_color,
                ))

                approve = input("  Approve? (y/n): ").strip().lower()
                action_id = data.get("id", "")
                await ws.send(json.dumps({
                    "type": "action_response",
                    "id": action_id,
                    "data": {
                        "action_id": action_id,
                        "approved": approve == "y",
                    },
                }))

                live = _new_live(Spinner("dots", text="Executing..."))
                live.start()

            elif msg_type == "action_complete":
                live.stop()
                ec = msg.get("data", {}).get("exit_code", "")
                console.print(f"  [dim]Action complete (exit code: {ec})[/dim]")
                live = _new_live(Spinner("dots", text="Processing..."))
                live.start()

            elif msg_type == "error":
                live.stop()
                err = msg.get("data", {}).get("message", "")
                console.print(f"\n[red]Error: {err}[/red]")
                return

            elif msg_type in ("thinking_start", "thinking_end", "pong",
                              "assistant_message_start", "system_status"):
                pass  # ignore

        except asyncio.TimeoutError:
            live.stop()
            console.print("\n[yellow]Response timed out[/yellow]")
            return

    # Stop live — the last frame (rendered markdown) stays on screen
    live.stop()
    console.print()


def _render_tool_result(name: str, result: dict[str, Any], display_type: str) -> None:
    """Render a tool result inline with formatting."""
    if "error" in result:
        console.print(f"  [red]Tool error: {result['error']}[/red]")
        return

    # For table display types, try to format as a table
    if display_type == "table" and isinstance(result, dict):
        # Try to find a list of items to tabulate
        for key in ("events", "entries", "processes", "services", "results"):
            items = result.get(key, [])
            if items and isinstance(items, list) and isinstance(items[0], dict):
                table = Table(title=f"Tool: {name}", show_header=True, header_style="dim")
                headers = list(items[0].keys())[:6]  # limit columns
                for h in headers:
                    table.add_column(h)
                for item in items[:15]:
                    table.add_row(*[str(item.get(h, ""))[:60] for h in headers])
                console.print(table)
                count = result.get("count", len(items))
                if count > 15:
                    console.print(f"  [dim]... and {count - 15} more[/dim]")
                return

    # Default: show summary
    console.print(f"  [dim]Tool result: {name} ({display_type})[/dim]")
