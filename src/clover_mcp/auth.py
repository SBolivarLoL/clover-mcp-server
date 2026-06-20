"""Token management: file-backed store and OAuth refresh-on-401.

For CLOVER_AUTH_MODE=oauth_refresh, the server automatically refreshes the
access token when Clover returns 401, persisting the new pair to a JSON file
owned by the operator (0600 permissions).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from clover_mcp.config import Config

_lock = asyncio.Lock()


def _refresh_url(config: Config) -> str:
    """Clover OAuth v2 refresh endpoint — same host as the REST API.

    base_url already resolves sandbox vs region (na/eu/la), so the refresh
    endpoint follows automatically.
    """
    return f"{config.base_url}/oauth/v2/refresh"


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
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


async def refresh_access_token(config: Config, failed_token: str) -> str:
    """Exchange the current refresh token for a new access token (Clover OAuth v2).

    Task-safe: only one refresh runs at a time via an asyncio.Lock. Persists the
    new (access_token, refresh_token) pair to the token store and returns the new
    access token.

    Clover refresh tokens are SINGLE-USE — each refresh invalidates the old
    refresh token and issues a new one, so we always read the latest refresh
    token from the store and write the new pair back.

    `failed_token` is the access token that just received a 401. If the store
    already holds a different (newer) access token, another coroutine refreshed
    while we waited for the lock — we reuse it rather than spending the
    single-use refresh token a second time.
    """
    async with _lock:
        store = TokenStore(config.token_store)
        current = store.load()

        stored_access = current.get("access_token")
        if stored_access and stored_access != failed_token:
            return stored_access

        # Latest refresh token wins (store, then env seed for the first refresh)
        refresh_token = current.get("refresh_token") or config.refresh_token

        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                _refresh_url(config),
                json={"client_id": config.oauth_client_id, "refresh_token": refresh_token},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()

        new_access = str(body["access_token"])
        new_refresh = str(body.get("refresh_token", refresh_token))

        store.save({"access_token": new_access, "refresh_token": new_refresh})
        return new_access
