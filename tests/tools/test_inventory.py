"""Tests for inventory tools: list_items, get_item, list_low_stock_items."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.inventory import get_item, list_items, list_low_stock_items
from tests.conftest import TEST_MERCHANT_ID

ITEMS_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/items"

ITEM_RAW = {
    "id": "ITEM1",
    "name": "Latte",
    "price": 500,
    "priceType": "FIXED",
    "sku": "LAT001",
    "code": "8901234567890",
    "cost": 150,
    "available": True,
    "hidden": False,
    "isRevenue": True,
    "href": "https://api.clover.com/v3/merchants/M1/items/ITEM1",
    "internalSecret": "strip-me",
    "categories": {"elements": [{"id": "CAT1", "name": "Drinks"}]},
    "itemStock": {"quantity": 10},
}

ITEM_RAW_LOW = {
    "id": "ITEM2",
    "name": "Espresso Shot",
    "price": 200,
    "priceType": "FIXED",
    "sku": "ESP001",
    "available": True,
    "hidden": False,
    "itemStock": {"quantity": 3},
}

ITEM_RAW_NO_STOCK = {
    "id": "ITEM3",
    "name": "Bagel",
    "price": 300,
    "priceType": "FIXED",
    "sku": "BAG001",
    "available": True,
    "hidden": False,
    # no itemStock key — not tracked
}


# ── list_items ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_items_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": [ITEM_RAW]}))
    result = await list_items(client)

    assert result["count"] == 1
    assert result["offset"] == 0
    assert result["limit"] == 100
    items = result["items"]
    assert len(items) == 1
    assert items[0]["id"] == "ITEM1"
    assert items[0]["name"] == "Latte"
    assert items[0]["price"] == 500
    assert items[0]["categories"] == ["CAT1"]
    assert items[0]["stock_quantity"] == 10
    # Shaping: banned fields must be stripped
    assert "href" not in items[0]
    assert "internalSecret" not in items[0]


@pytest.mark.asyncio
async def test_list_items_with_query(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    result = await list_items(client, query="Latte")

    assert result["count"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_items_with_category_id(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": [ITEM_RAW]}))
    result = await list_items(client, category_id="CAT1")

    assert result["count"] == 1


@pytest.mark.asyncio
async def test_list_items_pagination(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": [ITEM_RAW]}))
    result = await list_items(client, limit=10, offset=20)

    assert result["limit"] == 10
    assert result["offset"] == 20


@pytest.mark.asyncio
async def test_list_items_empty(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    result = await list_items(client)
    assert result["count"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_items_401(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(
        return_value=httpx.Response(401, json={"message": "401 Unauthorized"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await list_items(client)
    assert exc_info.value.status_code == 401
    assert "token" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_list_items_403(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(
        return_value=httpx.Response(403, json={"message": "No permission"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await list_items(client)
    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.message.lower()


# ── get_item ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_item_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW))
    result = await get_item(client, "ITEM1")

    assert result["id"] == "ITEM1"
    assert result["name"] == "Latte"
    assert result["price"] == 500
    assert result["sku"] == "LAT001"
    assert result["stock_quantity"] == 10
    # Banned fields stripped
    assert "href" not in result
    assert "internalSecret" not in result


@pytest.mark.asyncio
async def test_get_item_no_stock(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{ITEMS_PATH}/ITEM3").mock(
        return_value=httpx.Response(200, json=ITEM_RAW_NO_STOCK)
    )
    result = await get_item(client, "ITEM3")
    # Items without itemStock should not have stock_quantity key
    assert "stock_quantity" not in result


@pytest.mark.asyncio
async def test_get_item_404(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{ITEMS_PATH}/BADID").mock(
        return_value=httpx.Response(404, json={"message": "invalid ID"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await get_item(client, "BADID")
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.message.lower()


# ── list_low_stock_items ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_low_stock_items_happy_path(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # iterate() calls get() which goes to /items?limit=200&offset=0
    # Items: ITEM1 (qty=10, above threshold), ITEM2 (qty=3, below), ITEM3 (no stock)
    page = [ITEM_RAW, ITEM_RAW_LOW, ITEM_RAW_NO_STOCK]
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": page}))
    result = await list_low_stock_items(client, threshold=5)

    assert result["threshold"] == 5
    assert result["count"] == 1
    assert result["items"][0]["id"] == "ITEM2"
    assert result["items"][0]["stock_quantity"] == 3


@pytest.mark.asyncio
async def test_list_low_stock_items_threshold_inclusive(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Items at exactly the threshold should be included
    item_at_threshold = {**ITEM_RAW_LOW, "itemStock": {"quantity": 5}}
    mock_http.get(ITEMS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [item_at_threshold]})
    )
    result = await list_low_stock_items(client, threshold=5)
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_list_low_stock_items_excludes_no_stock_tracking(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Items with no itemStock should be excluded (not tracked)
    mock_http.get(ITEMS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [ITEM_RAW_NO_STOCK]})
    )
    result = await list_low_stock_items(client, threshold=5)
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_low_stock_items_empty(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    result = await list_low_stock_items(client)
    assert result["count"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_low_stock_items_429(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ITEMS_PATH).mock(
        return_value=httpx.Response(
            429, json={"message": "Too many requests"}, headers={"Retry-After": "60"}
        )
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await list_low_stock_items(client)
    assert exc_info.value.status_code == 429
