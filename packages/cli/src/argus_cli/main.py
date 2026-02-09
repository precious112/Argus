"""Argus CLI entry point."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="argus",
    help="Argus - AI-Native Observability Platform CLI",
    no_args_is_help=True,
)


@app.command()
def status(
    server: str = typer.Option("http://localhost:7600", help="Argus server URL"),
) -> None:
    """Show current system status."""
    typer.echo("Status command not yet implemented (Phase 6)")


@app.command()
def chat(
    server: str = typer.Option("ws://localhost:7600", help="Argus server URL"),
) -> None:
    """Start interactive chat with Argus agent."""
    typer.echo("Chat command not yet implemented (Phase 6)")


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines"),
) -> None:
    """View and search logs."""
    typer.echo("Logs command not yet implemented (Phase 6)")


@app.command()
def alerts() -> None:
    """View active alerts."""
    typer.echo("Alerts command not yet implemented (Phase 6)")


@app.command()
def ps() -> None:
    """List monitored processes."""
    typer.echo("Process list not yet implemented (Phase 6)")


@app.command()
def ask(question: str = typer.Argument(..., help="Question to ask the agent")) -> None:
    """Ask the agent a one-off question."""
    typer.echo("Ask command not yet implemented (Phase 6)")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
