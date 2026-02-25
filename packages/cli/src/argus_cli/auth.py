"""Login and session management for the Argus CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


def _token_path() -> Path:
    """Return the path to the stored session token file."""
    config_dir = Path(os.environ.get("ARGUS_CLI_CONFIG_DIR", Path.home() / ".argus"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "session.json"


def save_token(server_url: str, token: str) -> None:
    """Persist the JWT token to disk."""
    path = _token_path()
    data: dict[str, dict[str, str]] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data[server_url] = {"token": token}
    path.write_text(json.dumps(data, indent=2))
    # Restrict permissions (owner read/write only)
    path.chmod(0o600)


def load_token(server_url: str) -> str | None:
    """Load a previously saved JWT token for the given server."""
    path = _token_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get(server_url, {}).get("token")
    except (json.JSONDecodeError, OSError):
        return None


def clear_token(server_url: str) -> None:
    """Remove the stored token for a server."""
    path = _token_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        data.pop(server_url, None)
        path.write_text(json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError):
        pass


def login(server_url: str, username: str, password: str) -> str:
    """Authenticate with the Argus server and return the JWT token.

    Raises httpx.HTTPStatusError on auth failure.
    """
    url = f"{server_url.rstrip('/')}/api/v1/auth/login"
    resp = httpx.post(url, json={"username": username, "password": password}, timeout=10)
    resp.raise_for_status()

    # The server sets the token in an httpOnly cookie
    token = resp.cookies.get("argus_token")
    if not token:
        raise RuntimeError("Login succeeded but no token cookie was returned")

    save_token(server_url, token)
    return token
