"""CLI for Argus user management."""

from __future__ import annotations

import uuid

import click
from sqlalchemy import create_engine, inspect, text

from argus_agent.auth.password import hash_password
from argus_agent.config import load_config


def _ensure_users_table(engine) -> None:  # type: ignore[no-untyped-def]
    """Create the users table if it doesn't exist."""
    insp = inspect(engine)
    if not insp.has_table("users"):
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE users ("
                "  id VARCHAR(36) PRIMARY KEY,"
                "  username VARCHAR(150) UNIQUE NOT NULL,"
                "  password_hash VARCHAR(255) NOT NULL,"
                "  is_active BOOLEAN DEFAULT 1,"
                "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))


@click.group()
def cli() -> None:
    """Argus CLI for user management."""


@cli.command("create-user")
@click.option("--username", prompt=True, help="Username for the new account")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="Password for the new account",
)
def create_user(username: str, password: str) -> None:
    """Create a new Argus user."""
    settings = load_config()
    db_url = f"sqlite:///{settings.storage.sqlite_path}"
    engine = create_engine(db_url)

    _ensure_users_table(engine)

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(password)

    with engine.begin() as conn:
        # Check if user already exists
        result = conn.execute(
            text("SELECT id FROM users WHERE username = :u"),
            {"u": username},
        )
        if result.fetchone():
            click.echo(f"Error: User '{username}' already exists.", err=True)
            raise SystemExit(1)

        conn.execute(
            text(
                "INSERT INTO users (id, username, password_hash, is_active, created_at) "
                "VALUES (:id, :username, :password_hash, 1, CURRENT_TIMESTAMP)"
            ),
            {"id": user_id, "username": username, "password_hash": pw_hash},
        )

    click.echo(f"User '{username}' created successfully.")


if __name__ == "__main__":
    cli()
