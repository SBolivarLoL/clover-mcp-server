"""Regression checks for the eight repaired audit concerns.
All HTTP uses an in-memory transport and all credentials are synthetic.
"""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest

from clover_mcp.auth import TokenStore
from clover_mcp.client import CloverClient
from clover_mcp.remote import tenant_config
from clover_mcp.shaping import shape_customer
from clover_mcp.tools.inventory import get_item, set_item_price_cents, set_item_stock_quantity


async def mock_client(config, handler):
    client = CloverClient(config)
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        base_url=config.base_url, transport=httpx.MockTransport(handler)
    )
    return client


async def test_tenant_credentials_remain_isolated(test_config, tmp_path):
    base = replace(test_config, merchant_store=tmp_path / "merchants.json")
    tenants = {
        key: {
            "merchant_id": merchant,
            "auth_mode": "oauth_refresh",
            "access_token": token,
            "refresh_token": "fake-refresh",
            "oauth_client_id": "APP",
        }
        for key, merchant, token in [
            ("a+b@example.com", "MA", "fake-A"),
            ("a-b@example.com", "MB", "fake-B"),
        ]
    }
    a = tenant_config(base, tenants, "a+b@example.com")
    b = tenant_config(base, tenants, "a-b@example.com")
    TokenStore(a.token_store).save({"access_token": "fake-A-rotated"})
    async with CloverClient(b) as client:
        assert client._access_token == "fake-B"


@pytest.mark.parametrize(
    "item_id",
    [
        "ITEM1",
        "../../MA/items",
        "%2e%2e/%2e%2e/MA/items",
        "%252e%252e%252f%252e%252e%252fMA/items",
        "I?filter=name=secret",
        "I#fragment",
        "I\\..\\..\\MA",
        "I\n",
    ],
)
async def test_public_item_lookup_stays_in_merchant(test_config, item_id):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"id": "ITEM1", "name": "Sample"})

    async with await mock_client(test_config, handler) as client:
        if item_id != "ITEM1":
            with pytest.raises(ValueError):
                await get_item(client, item_id)
            assert paths == []
        else:
            await get_item(client, item_id)
            assert paths == [f"/v3/merchants/{test_config.merchant_id}/items/ITEM1"]


async def test_fractional_stock_blocks_real_write(test_config):
    methods = []

    def handler(request):
        methods.append(request.method)
        if "item_stocks" in request.url.path:
            return httpx.Response(200, json={"quantity": 10.9 if request.method == "GET" else 20})
        return httpx.Response(200, json={"id": "I", "name": "Sample"})

    async with await mock_client(test_config, handler) as client:
        result = await set_item_stock_quantity(client, "I", 20, 10)
    assert "PUT" not in methods, (methods, result)
    assert result["reason"] == "optimistic_lock_mismatch"


@pytest.mark.parametrize("include", [None, ["orders"]])
def test_customer_nested_sensitive_fields_removed(include):
    raw = {
        "id": "C",
        "cards": [{"token": "fake-card"}],
        "orders": {
            "elements": [
                {"id": "O", "payments": {"elements": [{"cardTransaction": {"token": "fake-card"}}]}}
            ]
        },
    }
    shaped = shape_customer(raw, include=include)
    assert "fake-card" not in str(shaped), shaped


async def test_parallel_401_refreshes_only_failed_credential(test_config, monkeypatch):
    both_old_sent = asyncio.Event()
    first_retry_done = asyncio.Event()
    old_count = 0
    failed_tokens = []
    stored_token = "old"
    rotations = 0

    async def refresh(config, failed_token):
        nonlocal stored_token, rotations
        failed_tokens.append(failed_token)
        # Model auth.refresh_access_token's stored-token deduplication contract.
        if stored_token != failed_token:
            return stored_token
        rotations += 1
        stored_token = f"new{rotations}"
        return stored_token

    async def handler(request):
        nonlocal old_count
        if request.headers.get("Authorization") == "Bearer old":
            old_count += 1
            if old_count == 1:
                await both_old_sent.wait()
            else:
                both_old_sent.set()
                await first_retry_done.wait()
            return httpx.Response(401, json={})
        first_retry_done.set()
        return httpx.Response(200, json={"id": "I"})

    monkeypatch.setattr("clover_mcp.client.refresh_access_token", refresh)
    # No actual store is read: token mode initializes, then enables refresh semantics.
    async with await mock_client(replace(test_config, access_token="old"), handler) as client:
        client._config = replace(test_config, auth_mode="oauth_refresh")
        await asyncio.wait_for(asyncio.gather(client.get("/items"), client.get("/items")), 3)
    assert rotations == 1, (rotations, failed_tokens)


async def test_uncertain_write_is_audited(test_config, monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("synthetic lost response", request=request)

    audit = Mock()
    monkeypatch.setattr("clover_mcp.client.audit", audit)
    async with await mock_client(test_config, handler) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.post("/items", json={"name": "Sample"})
    assert audit.call_count >= 1


async def test_empty_success_does_not_report_old_price(test_config):
    def handler(request):
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(200, json={"id": "I", "name": "Sample", "price": 100})

    async with await mock_client(test_config, handler) as client:
        result = await set_item_price_cents(client, "I", 200, 100)
    assert result["item"]["price"] == 200, result


async def test_missing_currency_is_not_assumed_usd(test_config):
    async with await mock_client(
        test_config, lambda request: httpx.Response(200, json={"id": "M"})
    ) as client:
        with pytest.raises(ValueError, match="currency"):
            await client.merchant_currency()
