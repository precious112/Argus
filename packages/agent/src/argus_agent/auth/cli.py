"""CLI for Argus user management."""

from __future__ import annotations

import uuid

import click

from argus_agent.auth.password import hash_password
from argus_agent.config import load_config


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
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from argus_agent.storage.models import Base, User

    settings = load_config()
    db_url = f"sqlite:///{settings.storage.sqlite_path}"
    engine = create_engine(db_url)

    # Create all tables from the ORM models (no-op if they exist)
    Base.metadata.create_all(engine)

    pw_hash = hash_password(password)

    with Session(engine) as session:
        existing = session.query(User).filter_by(username=username).first()
        if existing:
            click.echo(f"Error: User '{username}' already exists.", err=True)
            raise SystemExit(1)

        user = User(
            id=str(uuid.uuid4()),
            tenant_id="default",
            username=username,
            password_hash=pw_hash,
        )
        session.add(user)
        session.commit()

    click.echo(f"User '{username}' created successfully.")


if __name__ == "__main__":
    cli()
