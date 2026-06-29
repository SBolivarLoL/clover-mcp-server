"""Tests for inventory tools: list_items, get_item, list_low_stock_items,
set_item_price_cents, set_item_stock_quantity."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.inventory import (
    get_item,
    list_attributes,
    list_discounts,
    list_items,
    list_low_stock_items,
    list_tags,
    set_item_price_cents,
    set_item_stock_quantity,
)
from tests.conftest import TEST_MERCHANT_ID

ITEMS_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/items"
ITEM_STOCKS_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/item_stocks"

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


# ── set_item_price_cents ──────────────────────────────────────────────────────

# Fixture: raw item as returned by GET /items/{id}
ITEM_RAW_PRICE = {
    "id": "ITEM1",
    "name": "Latte",
    "price": 500,
    "priceType": "FIXED",
    "sku": "LAT001",
    "available": True,
    "hidden": False,
}

ITEM_RAW_PRICE_UPDATED = {**ITEM_RAW_PRICE, "price": 650}


@pytest.mark.asyncio
async def test_set_item_price_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    # GET pre-check returns current price 500
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW_PRICE))
    # PUT returns updated item
    mock_http.put(f"{ITEMS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=ITEM_RAW_PRICE_UPDATED)
    )
    result = await set_item_price_cents(
        client, "ITEM1", new_price_cents=650, expected_current_price_cents=500
    )
    assert result["ok"] is True
    assert "item" in result
    assert result["item"]["price"] == 650
    assert result["item"]["id"] == "ITEM1"


@pytest.mark.asyncio
async def test_set_item_price_dry_run(client: CloverClient, mock_http: respx.Router) -> None:
    # Only the GET pre-check fires; no PUT
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW_PRICE))
    result = await set_item_price_cents(
        client,
        "ITEM1",
        new_price_cents=650,
        expected_current_price_cents=500,
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_put_body"] == {"name": "Latte", "price": 650}
    assert "ITEM1" in result["would_put_path"]
    # Verify no PUT was sent
    assert not any(r.request.method == "PUT" for r in mock_http.calls)


@pytest.mark.asyncio
async def test_set_item_price_optimistic_lock_mismatch(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Current price is 500 but caller expects 400 → refuse
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW_PRICE))
    result = await set_item_price_cents(
        client, "ITEM1", new_price_cents=650, expected_current_price_cents=400
    )
    assert result["ok"] is False
    assert result["reason"] == "optimistic_lock_mismatch"
    assert result["expected"] == 400
    assert result["actual"] == 500
    assert "mismatch" in result["message"].lower()


@pytest.mark.asyncio
async def test_set_item_price_bounds_too_low(client: CloverClient, mock_http: respx.Router) -> None:
    # Negative price refused before any network call
    result = await set_item_price_cents(
        client, "ITEM1", new_price_cents=-1, expected_current_price_cents=500
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"
    assert not mock_http.calls  # zero network calls


@pytest.mark.asyncio
async def test_set_item_price_bounds_too_high(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Over $1M refused before any network call
    result = await set_item_price_cents(
        client, "ITEM1", new_price_cents=100_000_001, expected_current_price_cents=500
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"
    assert not mock_http.calls


@pytest.mark.asyncio
async def test_set_item_price_bounds_at_max(client: CloverClient, mock_http: respx.Router) -> None:
    # Exactly at $1M boundary should be accepted
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW_PRICE))
    mock_http.put(f"{ITEMS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json={**ITEM_RAW_PRICE, "price": 100_000_000})
    )
    result = await set_item_price_cents(
        client, "ITEM1", new_price_cents=100_000_000, expected_current_price_cents=500
    )
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_set_item_price_api_error(client: CloverClient, mock_http: respx.Router) -> None:
    # Pre-check GET returns 404
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(
        return_value=httpx.Response(404, json={"message": "invalid ID"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await set_item_price_cents(
            client, "ITEM1", new_price_cents=650, expected_current_price_cents=500
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_set_item_price_put_error(client: CloverClient, mock_http: respx.Router) -> None:
    # Pre-check succeeds but PUT returns 400
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW_PRICE))
    mock_http.put(f"{ITEMS_PATH}/ITEM1").mock(
        return_value=httpx.Response(400, json={"message": "Invalid price value"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await set_item_price_cents(
            client, "ITEM1", new_price_cents=650, expected_current_price_cents=500
        )
    assert exc_info.value.status_code == 400


# ── set_item_stock_quantity ───────────────────────────────────────────────────

STOCK_RAW = {"item": {"id": "ITEM1"}, "stockCount": 10, "quantity": 10.0}
STOCK_RAW_UPDATED = {"item": {"id": "ITEM1"}, "stockCount": 25, "quantity": 25.0}

# item_stocks PUT returns stock response; we then re-GET the item
ITEM_RAW_WITH_STOCK = {**ITEM_RAW_PRICE, "itemStock": {"quantity": 25}}


@pytest.mark.asyncio
async def test_set_item_stock_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    # GET /item_stocks/ITEM1 → current qty 10
    mock_http.get(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=STOCK_RAW)
    )
    # PUT /item_stocks/ITEM1 → updated qty 25
    mock_http.put(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=STOCK_RAW_UPDATED)
    )
    # GET /items/ITEM1 → re-fetch item (for shape_item)
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=ITEM_RAW_WITH_STOCK)
    )
    result = await set_item_stock_quantity(
        client, "ITEM1", new_quantity=25, expected_current_quantity=10
    )
    assert result["ok"] is True
    assert result["item"]["id"] == "ITEM1"
    assert result["item"]["stock_quantity"] == 25


@pytest.mark.asyncio
async def test_set_item_stock_dry_run(client: CloverClient, mock_http: respx.Router) -> None:
    # Only GET /item_stocks fires; no PUT, no re-GET of item
    mock_http.get(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=STOCK_RAW)
    )
    result = await set_item_stock_quantity(
        client,
        "ITEM1",
        new_quantity=25,
        expected_current_quantity=10,
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_put_body"] == {"quantity": 25}
    assert "ITEM1" in result["would_put_path"]
    # No PUT and no item GET should have been sent
    assert all(r.request.method == "GET" for r in mock_http.calls)


@pytest.mark.asyncio
async def test_set_item_stock_optimistic_lock_mismatch(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Current qty is 10 but caller expects 5 → refuse
    mock_http.get(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=STOCK_RAW)
    )
    result = await set_item_stock_quantity(
        client, "ITEM1", new_quantity=25, expected_current_quantity=5
    )
    assert result["ok"] is False
    assert result["reason"] == "optimistic_lock_mismatch"
    assert result["expected"] == 5
    assert result["actual"] == 10
    assert "mismatch" in result["message"].lower()


@pytest.mark.asyncio
async def test_set_item_stock_bounds_negative(
    client: CloverClient, mock_http: respx.Router
) -> None:
    result = await set_item_stock_quantity(
        client, "ITEM1", new_quantity=-1, expected_current_quantity=10
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"
    assert not mock_http.calls


@pytest.mark.asyncio
async def test_set_item_stock_bounds_too_high(
    client: CloverClient, mock_http: respx.Router
) -> None:
    result = await set_item_stock_quantity(
        client, "ITEM1", new_quantity=1_000_001, expected_current_quantity=10
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"
    assert not mock_http.calls


@pytest.mark.asyncio
async def test_set_item_stock_bounds_zero_allowed(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Zero is a valid quantity (clearing stock)
    mock_http.get(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=STOCK_RAW)
    )
    mock_http.put(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json={**STOCK_RAW, "stockCount": 0, "quantity": 0.0})
    )
    mock_http.get(f"{ITEMS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json={**ITEM_RAW_PRICE, "itemStock": {"quantity": 0}})
    )
    result = await set_item_stock_quantity(
        client, "ITEM1", new_quantity=0, expected_current_quantity=10
    )
    assert result["ok"] is True
    assert result["item"]["stock_quantity"] == 0


@pytest.mark.asyncio
async def test_set_item_stock_api_error_on_get(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # GET /item_stocks returns 404
    mock_http.get(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await set_item_stock_quantity(
            client, "ITEM1", new_quantity=25, expected_current_quantity=10
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_set_item_stock_api_error_on_put(
    client: CloverClient, mock_http: respx.Router
) -> None:
    # Pre-check OK but PUT fails with 403
    mock_http.get(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(200, json=STOCK_RAW)
    )
    mock_http.put(f"{ITEM_STOCKS_PATH}/ITEM1").mock(
        return_value=httpx.Response(403, json={"message": "No permission"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await set_item_stock_quantity(
            client, "ITEM1", new_quantity=25, expected_current_quantity=10
        )
    assert exc_info.value.status_code == 403


ATTRIBUTES_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/attributes"
TAGS_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/tags"


@pytest.mark.asyncio
async def test_list_attributes_with_options(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(ATTRIBUTES_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "id": "A1",
                        "name": "Size",
                        "options": {"elements": [{"id": "O1", "name": "Small"}]},
                        "href": "https://sandbox.dev.clover.com/x",
                    }
                ]
            },
        )
    )
    result = await list_attributes(client)
    assert result["count"] == 1
    attr = result["attributes"][0]
    assert attr["name"] == "Size"
    assert attr["options"] == [{"id": "O1", "name": "Small"}]
    assert "href" not in attr


@pytest.mark.asyncio
async def test_list_tags(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(TAGS_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "id": "T1",
                        "name": "Seasonal",
                        "showInReporting": True,
                        "href": "https://sandbox.dev.clover.com/x",
                    }
                ]
            },
        )
    )
    result = await list_tags(client)
    assert result["count"] == 1
    assert result["tags"][0]["name"] == "Seasonal"
    assert "href" not in result["tags"][0]


DISCOUNTS_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/discounts"


@pytest.mark.asyncio
async def test_list_discounts(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(DISCOUNTS_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "id": "D1",
                        "name": "Happy Hour",
                        "percentage": 15,
                        "href": "https://sandbox.dev.clover.com/x",
                    },
                    {"id": "D2", "name": "$5 off", "amount": 500},
                ]
            },
        )
    )
    result = await list_discounts(client)
    assert result["count"] == 2
    assert result["discounts"][0]["name"] == "Happy Hour"
    assert result["discounts"][0]["percentage"] == 15
    assert result["discounts"][1]["amount"] == 500
    assert "href" not in result["discounts"][0]


@pytest.mark.asyncio
async def test_list_discounts_403(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(DISCOUNTS_PATH).mock(
        return_value=httpx.Response(403, json={"message": "Inventory not authorized"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await list_discounts(client)
    assert exc_info.value.status_code == 403
