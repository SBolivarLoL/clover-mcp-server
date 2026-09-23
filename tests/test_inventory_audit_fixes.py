"""Regression coverage for inventory audit findings A03 and A11."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.tools.inventory import (
    set_item_price_cents,
    set_item_stock_quantity,
    update_item_name,
)
from tests.conftest import TEST_MERCHANT_ID

BASE = f"/v3/merchants/{TEST_MERCHANT_ID}"
ITEM = {"id": "I", "name": "Old", "price": 100, "sku": "SKU-1", "available": True}


@pytest.mark.asyncio
async def test_fractional_stock_does_not_match_integer_expectation(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/item_stocks/I").mock(
        return_value=httpx.Response(200, json={"quantity": 10.9})
    )

    result = await set_item_stock_quantity(client, "I", 20, 10)

    assert result["ok"] is False
    assert result["reason"] == "optimistic_lock_mismatch"
    assert result["actual"] == 10.9
    assert not any(call.request.method == "PUT" for call in mock_http.calls)


@pytest.mark.asyncio
async def test_integral_float_stock_matches_integer_expectation(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/item_stocks/I").mock(
        return_value=httpx.Response(200, json={"quantity": 10.0})
    )
    mock_http.put(f"{BASE}/item_stocks/I").mock(
        return_value=httpx.Response(200, json={"quantity": 20})
    )
    mock_http.get(f"{BASE}/items/I").mock(return_value=httpx.Response(200, json=ITEM))

    result = await set_item_stock_quantity(client, "I", 20, 10)

    assert result["ok"] is True
    assert result["item"]["stock_quantity"] == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [None, True, "10"])
async def test_invalid_stock_quantity_refuses_without_write(
    quantity: object, client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/item_stocks/I").mock(
        return_value=httpx.Response(200, json={"quantity": quantity})
    )

    result = await set_item_stock_quantity(client, "I", 20, 10)

    assert result["ok"] is False
    assert result["reason"] == "optimistic_lock_mismatch"
    assert not any(call.request.method == "PUT" for call in mock_http.calls)


@pytest.mark.asyncio
async def test_empty_price_success_reports_new_price_and_preserves_snapshot(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/I").mock(return_value=httpx.Response(200, json=ITEM))
    mock_http.put(f"{BASE}/items/I").mock(return_value=httpx.Response(200))

    result = await set_item_price_cents(client, "I", 200, 100)

    assert result["ok"] is True
    assert result["item"]["price"] == 200
    assert result["item"]["name"] == "Old"
    assert result["item"]["sku"] == "SKU-1"


@pytest.mark.asyncio
async def test_price_response_value_wins_over_requested_overlay(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/I").mock(return_value=httpx.Response(200, json=ITEM))
    mock_http.put(f"{BASE}/items/I").mock(
        return_value=httpx.Response(200, json={**ITEM, "price": 225})
    )

    result = await set_item_price_cents(client, "I", 200, 100)

    assert result["item"]["price"] == 225


@pytest.mark.asyncio
async def test_empty_name_success_reports_new_name_and_preserves_snapshot(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/I").mock(return_value=httpx.Response(200, json=ITEM))
    mock_http.post(f"{BASE}/items/I").mock(return_value=httpx.Response(200))

    result = await update_item_name(
        client, None, "I", "New", expected_current_name="Old", confirm=True
    )

    assert result["ok"] is True
    assert result["item"]["name"] == "New"
    assert result["item"]["price"] == 100
    assert result["item"]["sku"] == "SKU-1"


@pytest.mark.asyncio
async def test_name_response_value_wins_over_requested_overlay(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/I").mock(return_value=httpx.Response(200, json=ITEM))
    mock_http.post(f"{BASE}/items/I").mock(
        return_value=httpx.Response(200, json={**ITEM, "name": "Server Name"})
    )

    result = await update_item_name(
        client, None, "I", "New", expected_current_name="Old", confirm=True
    )

    assert result["item"]["name"] == "Server Name"
