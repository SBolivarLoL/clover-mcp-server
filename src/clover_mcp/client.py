"""Clover REST API HTTP client.

Wraps httpx.AsyncClient with:
  - Automatic Authorization / User-Agent / Accept headers
  - /v3/merchants/{mId} path prefix for relative paths
  - 401 → token refresh (oauth_refresh mode only)
  - 429 → single auto-retry if Retry-After ≤ 5s
  - 5xx → single retry on reads; NO retry on writes
  - Pagination helper: iterate()
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from clover_mcp import __version__
from clover_mcp.auth import TokenStore, refresh_access_token
from clover_mcp.config import Config
from clover_mcp.errors import raise_for_status

_USER_AGENT = f"clover-mcp/{__version__} (+https://github.com/SBolivarLoL/clover-mcp-server)"


class CloverClient:
    """Async HTTP client for the Clover REST API."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._access_token = self._load_initial_token()
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=30,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def _load_initial_token(self) -> str:
        """Load token from store (oauth_refresh) or config (token mode)."""
        if self._config.auth_mode == "oauth_refresh":
            stored = TokenStore(self._config.token_store).load()
            if stored.get("access_token"):
                return stored["access_token"]
        return self._config.access_token

    def _url(self, path: str) -> str:
        """Expand a relative path to the full merchant path."""
        if path.startswith("http"):
            return path
        if not path.startswith("/v3"):
            path = f"/v3/merchants/{self._config.merchant_id}{path}"
        return path

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _refresh_and_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Refresh the OAuth access token and retry the request once."""
        self._access_token = await refresh_access_token(self._config, self._access_token)
        return await self._http.request(method, url, headers=self._auth_headers(), **kwargs)

    async def _send(
        self,
        method: str,
        path: str,
        is_write: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        url = self._url(path)
        context = f"{method} {path}"

        # oauth_refresh may start with no access token (e.g. a tenant configured
        # with only a refresh token, or an ephemeral host with an empty store).
        # Bootstrap one first — an empty `Bearer ` header is rejected before it's
        # even sent, so the 401→refresh path below would never get a chance.
        if not self._access_token and self._config.auth_mode == "oauth_refresh":
            self._access_token = await refresh_access_token(self._config, "")

        resp = await self._http.request(method, url, headers=self._auth_headers(), **kwargs)

        # 401 → refresh once (oauth_refresh only)
        if resp.status_code == 401 and self._config.auth_mode == "oauth_refresh":
            resp = await self._refresh_and_retry(method, url, **kwargs)

        # 429 → single auto-retry if short wait
        if resp.status_code == 429:
            raw = resp.headers.get("Retry-After", "")
            wait = int(raw) if raw.isdigit() else None
            if wait is not None and wait <= 5:
                await asyncio.sleep(wait)
                resp = await self._http.request(method, url, headers=self._auth_headers(), **kwargs)

        # 5xx reads → single retry with 1s backoff; writes never retry
        if resp.status_code >= 500 and not is_write:
            await asyncio.sleep(1)
            resp = await self._http.request(method, url, headers=self._auth_headers(), **kwargs)

        raise_for_status(resp, context=context)
        return resp

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        resp = await self._send("GET", path, params=params)
        return resp.json()  # type: ignore[no-any-return]

    async def post(self, path: str, json: Any = None, **params: Any) -> dict[str, Any]:
        resp = await self._send("POST", path, is_write=True, json=json, params=params)
        return resp.json()  # type: ignore[no-any-return]

    async def put(self, path: str, json: Any = None, **params: Any) -> dict[str, Any]:
        resp = await self._send("PUT", path, is_write=True, json=json, params=params)
        try:
            return resp.json()  # type: ignore[no-any-return]
        except Exception:
            return {}  # Clover sometimes returns 200 with empty body on PUT

    async def delete(self, path: str, **params: Any) -> None:
        await self._send("DELETE", path, is_write=True, params=params)

    async def iterate(
        self, path: str, *, limit: int = 100, **params: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every element across paginated Clover list responses."""
        offset = 0
        while True:
            body = await self.get(path, limit=limit, offset=offset, **params)
            elements: list[dict[str, Any]] = body.get("elements", [])
            for el in elements:
                yield el
            if len(elements) < limit:
                break
            offset += limit

    async def close(self) -> None:
        await self._http.aclose()

    # Context manager support
    async def __aenter__(self) -> CloverClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Merchant info cache ───────────────────────────────────────────────────

    _merchant_cache: dict[str, Any] | None = None

    async def get_merchant_info(self) -> dict[str, Any]:
        """Fetch and cache merchant info (currency, timezone, country)."""
        if self._merchant_cache is None:
            self._merchant_cache = await self.get(f"/v3/merchants/{self._config.merchant_id}")
        return self._merchant_cache

    async def merchant_currency(self) -> str:
        info = await self.get_merchant_info()
        return str(info.get("defaultCurrency") or info.get("currency") or "USD")

    async def merchant_timezone(self) -> str:
        info = await self.get_merchant_info()
        return str(info.get("timezone") or "UTC")
