"""Argus CLI entry point."""

from __future__ import annotations

import asyncio
import os

import typer

app = typer.Typer(
    name="argus",
    help="Argus - AI-Native Observability Platform CLI",
    no_args_is_help=True,
)

_DEFAULT_SERVER = os.environ.get("ARGUS_URL", "http://localhost:7600")


@app.command()
def status(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """Show current system status."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_status

    api = ArgusAPI(server)
    try:
        data = api.status()
        print_status(data)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


@app.command()
def chat(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """Start interactive chat with Argus agent."""
    from argus_cli.chat import start_chat

    asyncio.run(start_chat(server))


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines"),
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """View and search logs."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_logs

    api = ArgusAPI(server)
    try:
        data = api.logs(limit=lines)
        entries = data.get("entries", [])
        print_logs(entries)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


@app.command()
def alerts(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """View active alerts."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_alerts

    api = ArgusAPI(server)
    try:
        data = api.alerts()
        print_alerts(data.get("alerts", []))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


@app.command()
def ps(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """List monitored processes."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_processes

    api = ArgusAPI(server)
    try:
        data = api.status()
        # Process list comes from the system snapshot
        system = data.get("system", {})
        procs = system.get("top_processes", [])
        print_processes(procs)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


@app.command(name="metrics")
def metrics_cmd(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """Show latest metrics."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_metrics

    api = ArgusAPI(server)
    try:
        data = api.metrics()
        # Budget endpoint returns token usage, show it as metrics
        print_metrics({
            "hourly_used": data.get("hourly_used", 0),
            "hourly_limit": data.get("hourly_limit", 0),
            "daily_used": data.get("daily_used", 0),
            "daily_limit": data.get("daily_limit", 0),
        })
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to ask the agent"),
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """Ask the agent a one-off question."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_answer

    api = ArgusAPI(server)
    try:
        data = api.ask(question)
        answer = data.get("answer", data.get("error", "No response"))
        print_answer(answer)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
