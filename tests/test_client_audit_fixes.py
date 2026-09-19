"""Offline regressions for client URL, refresh, audit, and currency guards."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest

from clover_mcp.client import CloverClient


async def _client(config, handler):
    client = CloverClient(config)
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        base_url=config.base_url, transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.parametrize(
    "path",
    [
        "/items/../../OTHER/items",
        "/items/%2e%2e/%2e%2e/OTHER/items",
        "/items/%2F%2E%2E%2FOTHER/items",
        "/items/ITEM?expand=orders",
        "https://example.invalid/v3/merchants/OTHER/items",
        "/v3/merchants/OTHER/items",
    ],
)
def test_url_rejects_traversal_foreign_and_query_paths(test_config, path):
    client = CloverClient(test_config)
    with pytest.raises(ValueError):
        client._url(path)


def test_url_allows_configured_full_merchant_url(test_config):
    client = CloverClient(test_config)
    expected = f"/v3/merchants/{test_config.merchant_id}/"
    assert client._url(expected) == expected
    assert client._url(test_config.base_url + expected) == expected


async def test_delayed_401_refresh_uses_each_request_token(test_config, monkeypatch):
    seen = []

    async def refresh(config, failed_token):
        seen.append(failed_token)
        return "new"

    async def handler(request):
        if request.headers["Authorization"] == "Bearer old":
            await asyncio.sleep(0.01)
            return httpx.Response(401)
        return httpx.Response(200, json={"id": "I"})

    monkeypatch.setattr("clover_mcp.client.refresh_access_token", refresh)
    config = replace(test_config, auth_mode="oauth_refresh", access_token="old")
    async with await _client(config, handler) as client:
        await asyncio.gather(client.get("/items"), client.get("/items"))
    assert seen == ["old", "old"]


async def test_transport_failure_audits_uncertain_write_without_exception_text(
    test_config, monkeypatch
):
    records = []
    audit = Mock(side_effect=lambda event, **fields: records.append((event, fields)))
    monkeypatch.setattr("clover_mcp.client.audit", audit)

    def handler(request):
        raise httpx.ReadTimeout("token-secret should not be logged", request=request)

    async with await _client(test_config, handler) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.post("/items", json={"name": "item"})
    assert len(records) == 1
    event, fields = records[0]
    assert event == "write_uncertain"
    assert fields["outcome"] == "uncertain"
    assert fields["merchant"] == test_config.merchant_id
    assert "token-secret" not in str(fields)
    assert "exception" not in fields


async def test_cancelled_write_audits_uncertain_without_retry(test_config, monkeypatch):
    audit = Mock()
    monkeypatch.setattr("clover_mcp.client.audit", audit)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    async with await _client(test_config, handler) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.post("/items", json={"name": "item"})
    assert calls == 1
    assert audit.call_args.args == ("write_uncertain",)


async def test_missing_currency_raises_actionable_error(test_config):
    async with await _client(
        test_config, lambda request: httpx.Response(200, json={"id": "M"})
    ) as client:
        with pytest.raises(ValueError, match="currency"):
            await client.merchant_currency()


@pytest.mark.parametrize("body", [b"", b"not-json"])
async def test_post_empty_success_is_empty_but_malformed_body_fails(test_config, body):
    async with await _client(
        test_config, lambda request: httpx.Response(200, content=body)
    ) as client:
        if body:
            with pytest.raises(ValueError):
                await client.post("/items", json={"name": "item"})
        else:
            assert await client.post("/items", json={"name": "item"}) == {}
