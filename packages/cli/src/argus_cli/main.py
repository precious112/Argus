"""Argus CLI entry point."""

from __future__ import annotations

import asyncio
import os

import typer

app = typer.Typer(
    name="argus",
    help="Argus - AI-Native Observability Platform CLI",
    no_args_is_help=False,
    invoke_without_command=True,
)

from rich.prompt import Confirm, Prompt

_DEFAULT_SERVER = os.environ.get("ARGUS_URL", "http://localhost:7600")

_PROVIDERS = ["openai", "anthropic", "gemini"]
_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5-20250929",
    "gemini": "gemini-2.0-flash",
}


@app.callback()
def callback(
    ctx: typer.Context,
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Disable interactive mode"),
) -> None:
    """Argus - AI-Native Observability Platform CLI.

    Running `argus` with no subcommand starts an interactive chat session.
    """
    ctx.ensure_object(dict)
    ctx.obj["server"] = server
    # If no subcommand was invoked, start interactive chat
    if ctx.invoked_subcommand is None:
        if no_interactive:
            typer.echo(ctx.get_help())
            raise typer.Exit(0)
        from argus_cli.chat import start_chat

        asyncio.run(start_chat(server))


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
    from argus_cli.display import print_metrics, print_status

    api = ArgusAPI(server)
    try:
        # Show system metrics from status endpoint
        status_data = api.status()
        print_status(status_data)

        # Show token budget metrics
        data = api.metrics()
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
def services(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """List SDK-instrumented services."""
    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_services

    api = ArgusAPI(server)
    try:
        data = api.services()
        print_services(data.get("services", []))
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


@app.command(name="login")
def login_cmd(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
    username: str = typer.Option("", "-u", "--username", help="Username"),
    password: str = typer.Option("", "-p", "--password", help="Password"),
) -> None:
    """Authenticate with the Argus server."""
    from argus_cli.auth import login

    if not username:
        username = Prompt.ask("Username")
    if not password:
        import getpass
        password = getpass.getpass("Password: ")

    try:
        login(server, username, password)
        typer.echo("Login successful. Session token saved.")
    except Exception as e:
        typer.echo(f"Login failed: {e}", err=True)
        raise typer.Exit(1)


@app.command(name="logout")
def logout_cmd(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """Clear stored session token."""
    from argus_cli.auth import clear_token

    clear_token(server)
    typer.echo("Logged out. Session token cleared.")


config_app = typer.Typer(help="View and update LLM configuration.")
app.add_typer(config_app, name="config")


@config_app.callback(invoke_without_command=True)
def config_show(
    ctx: typer.Context,
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
) -> None:
    """Show current LLM configuration."""
    if ctx.invoked_subcommand is not None:
        return

    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_config

    api = ArgusAPI(server)
    try:
        data = api.settings()
        print_config(data)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


@config_app.command(name="set")
def config_set_cmd(
    server: str = typer.Option(_DEFAULT_SERVER, help="Argus server URL"),
    provider: str | None = typer.Option(None, "-p", "--provider", help="LLM provider"),
    model: str | None = typer.Option(None, "-m", "--model", help="Model name"),
    api_key: str | None = typer.Option(None, "-k", "--api-key", help="API key"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
) -> None:
    """Update LLM settings (interactive or via flags)."""
    # If no flags provided, use interactive prompts
    if provider is None and model is None and api_key is None:
        provider = Prompt.ask(
            "Select LLM provider",
            choices=_PROVIDERS,
            default="openai",
        )
        default_model = _DEFAULT_MODELS.get(provider, "")
        model = Prompt.ask("Model name", default=default_model)
        api_key = Prompt.ask(
            "API key (leave blank to keep current)",
            default="",
            password=True,
        )
        if not api_key:
            api_key = None

        # Confirmation
        typer.echo(f"\n  Provider: {provider}")
        typer.echo(f"  Model:    {model}")
        typer.echo(f"  API key:  {'(will update)' if api_key else '(unchanged)'}")
        if not Confirm.ask("\nSave these settings?", default=True):
            raise typer.Exit(0)

    elif not yes:
        parts = []
        if provider:
            parts.append(f"provider={provider}")
        if model:
            parts.append(f"model={model}")
        if api_key:
            parts.append("api_key=(hidden)")
        typer.echo(f"Updating: {', '.join(parts)}")
        if not Confirm.ask("Continue?", default=True):
            raise typer.Exit(0)

    from argus_cli.api import ArgusAPI
    from argus_cli.display import print_config_update

    api = ArgusAPI(server)
    try:
        data = api.update_llm_settings(provider=provider, model=model, api_key=api_key)
        print_config_update(data)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        api.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
