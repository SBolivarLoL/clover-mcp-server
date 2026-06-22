"""Contract: the startup permission self-check fails fast on auth/permission
problems but does not crash on transient errors."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from clover_mcp import server
from clover_mcp.client import CloverClient
from clover_mcp.config import Config
from tests.conftest import TEST_MERCHANT_ID, TEST_TOKEN

_M = f"/v3/merchants/{TEST_MERCHANT_ID}"
_PROBES = [_M, f"{_M}/payments", f"{_M}/orders", f"{_M}/items", f"{_M}/customers"]


def _cfg() -> Config:
    return Config(
        merchant_id=TEST_MERCHANT_ID,
        access_token=TEST_TOKEN,
        region="na",
        sandbox=True,
        auth_mode="token",
        refresh_token="",
        oauth_client_id="",
        oauth_client_secret="",
        token_store=Path("/tmp/clover-mcp-test-perm.json"),
    )


@pytest.fixture
def wired(mock_http: respx.Router) -> Iterator[None]:
    cfg = _cfg()
    server._config = cfg
    server._client = CloverClient(cfg)
    yield
    server._client = None
    server._config = None


@pytest.mark.asyncio
async def test_all_scopes_ok_does_not_exit(wired: None, mock_http: respx.Router) -> None:
    for p in _PROBES:
        mock_http.get(p).mock(return_value=httpx.Response(200, json={"elements": []}))
    await server._check_permissions()  # must not raise SystemExit


@pytest.mark.asyncio
async def test_missing_scope_exits(wired: None, mock_http: respx.Router) -> None:
    for p in _PROBES:
        mock_http.get(p).mock(return_value=httpx.Response(200, json={"elements": []}))
    # items returns 403 → missing INVENTORY_R → exit
    mock_http.get(f"{_M}/items").mock(
        return_value=httpx.Response(403, json={"message": "Missing INVENTORY_R"})
    )
    with pytest.raises(SystemExit):
        await server._check_permissions()


@pytest.mark.asyncio
async def test_bad_token_exits(wired: None, mock_http: respx.Router) -> None:
    mock_http.get(_M).mock(return_value=httpx.Response(401, json={"message": "bad token"}))
    with pytest.raises(SystemExit):
        await server._check_permissions()


@pytest.mark.asyncio
async def test_transient_error_does_not_crash(wired: None, mock_http: respx.Router) -> None:
    for p in _PROBES:
        mock_http.get(p).mock(return_value=httpx.Response(200, json={"elements": []}))
    # one probe hits a network error — should warn and continue, not exit
    mock_http.get(f"{_M}/orders").mock(side_effect=httpx.ConnectError("boom"))
    await server._check_permissions()  # must not raise
