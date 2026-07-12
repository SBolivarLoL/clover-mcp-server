"""Read-only kill switch (CLOVER_READ_ONLY=true): every write is refused before
any HTTP call, reads still work."""

from __future__ import annotations

from dataclasses import replace

import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.config import Config
from clover_mcp.errors import ReadOnlyError
from tests.conftest import TEST_MERCHANT_ID

BASE = f"/v3/merchants/{TEST_MERCHANT_ID}"


@pytest.fixture
def ro_client(test_config: Config, mock_http: respx.Router) -> CloverClient:
    return CloverClient(replace(test_config, read_only=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["post", "put", "delete"])
async def test_writes_refused_without_http(
    ro_client: CloverClient, mock_http: respx.Router, verb: str
) -> None:
    # Route the write to a 500 so the test fails loudly if it ever reaches HTTP.
    route = mock_http.route(path__regex=r".*").mock(return_value=respx.MockResponse(500))
    method = getattr(ro_client, verb)
    with pytest.raises(ReadOnlyError):
        await method("/items/X") if verb == "delete" else await method("/items/X", json={})
    assert not route.called


@pytest.mark.asyncio
async def test_reads_still_work(ro_client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{BASE}/items").mock(return_value=respx.MockResponse(200, json={"elements": []}))
    assert await ro_client.get("/items") == {"elements": []}
