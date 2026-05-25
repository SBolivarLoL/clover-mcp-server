"""Token management: file-backed store and OAuth refresh-on-401.

For CLOVER_AUTH_MODE=oauth_refresh, the server automatically refreshes the
access token when Clover returns 401, persisting the new pair to a JSON file
owned by the operator (0600 permissions).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from clover_mcp.config import Config

_CLOVER_OAUTH_TOKEN_URL = "https://api.clover.com/oauth/v2/token"

_lock = asyncio.Lock()


class TokenStore:
    """File-backed token store for the oauth_refresh auth mode."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, str]:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def save(self, tokens: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file → rename, then set strict perms
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".tokens-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(tokens, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


async def refresh_access_token(config: "Config") -> str:
    """Exchange a refresh token for a new access token via Clover's OAuth endpoint.

    Thread/task-safe: only one refresh runs at a time via an asyncio.Lock.
    Updates the token store on success.

    Returns the new access token.
    """
    async with _lock:
        store = TokenStore(config.token_store)
        current = store.load()

        # Re-check: another coroutine may have already refreshed while we waited
        if current.get("access_token") and current.get("access_token") != config.access_token:
            return current["access_token"]

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _CLOVER_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": config.oauth_client_id,
                    "client_secret": config.oauth_client_secret,
                    "refresh_token": config.refresh_token,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()

        new_access = body["access_token"]
        new_refresh = body.get("refresh_token", config.refresh_token)

        store.save({"access_token": new_access, "refresh_token": new_refresh})
        return new_access
