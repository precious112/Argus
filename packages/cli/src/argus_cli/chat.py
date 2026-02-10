"""Interactive chat mode via WebSocket."""

from __future__ import annotations

import asyncio
import json
import sys

from rich.console import Console

console = Console()


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

    console.print(f"[cyan]Connecting to {ws_url}...[/cyan]")

    try:
        async with websockets.connect(ws_url) as ws:
            console.print("[green]Connected. Type your message (Ctrl+C to quit).[/green]\n")

            # Read the connected message
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") == "connected":
                console.print("[dim]Connected to Argus agent[/dim]")

            # Read system status if sent
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                msg = json.loads(raw)
            except asyncio.TimeoutError:
                pass

            while True:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("\n[bold cyan]You:[/bold cyan] " if False else "You: ")
                    )
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Goodbye![/dim]")
                    break

                if not user_input.strip():
                    continue

                # Send user message
                await ws.send(json.dumps({
                    "type": "user_message",
                    "id": "",
                    "data": {"content": user_input},
                }))

                # Stream response
                console.print("[cyan]Argus:[/cyan] ", end="")
                done = False
                while not done:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        msg = json.loads(raw)
                        msg_type = msg.get("type", "")

                        if msg_type == "assistant_message_delta":
                            content = msg.get("data", {}).get("content", "")
                            sys.stdout.write(content)
                            sys.stdout.flush()

                        elif msg_type == "assistant_message_end":
                            print()  # newline
                            done = True

                        elif msg_type == "tool_call":
                            name = msg.get("data", {}).get("name", "")
                            console.print(f"\n  [dim]Calling tool: {name}[/dim]")

                        elif msg_type == "tool_result":
                            display = msg.get("data", {}).get("display_type", "")
                            console.print(f"  [dim]Tool result ({display})[/dim]")

                        elif msg_type == "action_request":
                            data = msg.get("data", {})
                            risk = data.get("risk_level", "")
                            desc = data.get("description", "")
                            cmd = data.get("command", [])
                            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

                            console.print(f"\n  [yellow]Action: {desc}[/yellow]")
                            console.print(f"  [yellow]Command: {cmd_str}[/yellow]")
                            console.print(f"  [yellow]Risk: {risk}[/yellow]")

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

                        elif msg_type == "action_complete":
                            ec = msg.get("data", {}).get("exit_code", "")
                            console.print(f"  [dim]Action complete (exit code: {ec})[/dim]")

                        elif msg_type == "error":
                            err = msg.get("data", {}).get("message", "")
                            console.print(f"\n[red]Error: {err}[/red]")
                            done = True

                        elif msg_type in ("thinking_start", "thinking_end", "pong"):
                            pass  # ignore

                    except asyncio.TimeoutError:
                        console.print("\n[yellow]Response timed out[/yellow]")
                        done = True

    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/red]")
