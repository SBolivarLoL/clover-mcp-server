"""Write-velocity guard: a tenant is capped at N write-tool calls per window,
refused before any HTTP call; reads are never counted."""

from __future__ import annotations

from dataclasses import replace

import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.config import Config
from clover_mcp.errors import WriteVelocityError
from tests.conftest import TEST_MERCHANT_ID

BASE = f"/v3/merchants/{TEST_MERCHANT_ID}"


@pytest.fixture
def capped_client(test_config: Config, mock_http: respx.Router) -> CloverClient:
    # Cap of 2 writes, huge window so nothing expires mid-test.
    return CloverClient(replace(test_config, write_limit_count=2, write_limit_window_s=3600))


@pytest.mark.asyncio
async def test_cap_refuses_third_write_before_http(
    capped_client: CloverClient, mock_http: respx.Router
) -> None:
    route = mock_http.post(f"{BASE}/orders").mock(
        return_value=respx.MockResponse(200, json={"id": "O1"})
    )
    await capped_client.post("/orders", json={})
    await capped_client.post("/orders", json={})
    assert route.call_count == 2
    with pytest.raises(WriteVelocityError):
        await capped_client.post("/orders", json={})
    assert route.call_count == 2  # third never reached HTTP


@pytest.mark.asyncio
async def test_reads_not_counted(capped_client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{BASE}/items").mock(return_value=respx.MockResponse(200, json={"elements": []}))
    for _ in range(5):
        await capped_client.get("/items")  # far over the write cap, never refused


@pytest.mark.asyncio
async def test_expired_writes_free_the_window(
    test_config: Config, mock_http: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deterministic clock: fill the cap, then jump past the window so old writes expire.
    clock = {"t": 0.0}
    monkeypatch.setattr("clover_mcp.client.time.monotonic", lambda: clock["t"])
    client = CloverClient(replace(test_config, write_limit_count=2, write_limit_window_s=100))
    mock_http.post(f"{BASE}/orders").mock(return_value=respx.MockResponse(200, json={"id": "O"}))

    clock["t"] = 0.0
    await client.post("/orders", json={})
    clock["t"] = 1.0
    await client.post("/orders", json={})  # now at cap
    with pytest.raises(WriteVelocityError):
        await client.post("/orders", json={})

    clock["t"] = 200.0  # past the window → both prior writes expired
    await client.post("/orders", json={})
    await client.post("/orders", json={})  # cap of 2 available again


@pytest.mark.asyncio
async def test_zero_count_disables_guard(test_config: Config, mock_http: respx.Router) -> None:
    client = CloverClient(replace(test_config, write_limit_count=0))
    mock_http.post(f"{BASE}/orders").mock(return_value=respx.MockResponse(200, json={"id": "O"}))
    for _ in range(20):
        await client.post("/orders", json={})
