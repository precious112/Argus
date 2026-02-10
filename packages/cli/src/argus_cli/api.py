"""HTTP client for Argus REST API."""

from __future__ import annotations

from typing import Any

import httpx


class ArgusAPI:
    """Wraps httpx for Argus REST API calls."""

    def __init__(self, base_url: str = "http://localhost:7600") -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(base_url=f"{self._base}/api/v1", timeout=15)

    def health(self) -> dict[str, Any]:
        return self._client.get("/health").json()

    def status(self) -> dict[str, Any]:
        return self._client.get("/status").json()

    def alerts(self, resolved: bool | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if resolved is not None:
            params["resolved"] = resolved
        return self._client.get("/alerts", params=params).json()

    def processes(self) -> dict[str, Any]:
        """Get process list from the status endpoint system data."""
        status = self.status()
        return status.get("system", {})

    def metrics(self) -> dict[str, Any]:
        return self._client.get("/budget").json()

    def audit_log(self, limit: int = 20) -> dict[str, Any]:
        return self._client.get("/audit", params={"limit": limit}).json()

    def logs(self, limit: int = 50) -> dict[str, Any]:
        return self._client.get("/logs", params={"limit": limit}).json()

    def ask(self, question: str) -> dict[str, Any]:
        return self._client.post("/ask", json={"question": question}).json()

    def settings(self) -> dict[str, Any]:
        return self._client.get("/settings").json()

    def close(self) -> None:
        self._client.close()
