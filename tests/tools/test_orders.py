"""Tests for the orders tools: list_orders, get_order, list_open_orders."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.orders import get_order, list_open_orders, list_orders
from tests.conftest import TEST_MERCHANT_ID

# ── Shared fixtures / helpers ─────────────────────────────────────────────────


def _orders_path() -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}/orders"


def _order_path(order_id: str) -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}/orders/{order_id}"


ORDER_OPEN = {
    "id": "ORD_OPEN1",
    "state": "open",
    "total": 1500,
    "taxAmount": 75,
    "currency": "USD",
    "createdTime": 1700000100000,
    "modifiedTime": 1700000200000,
    "employee": {"id": "EMP1"},
    "customers": {"elements": [{"id": "CUST1", "cards": {"elements": [{"token": "tok_secret"}]}}]},
    "href": "https://api.clover.com/v3/merchants/M1/orders/ORD_OPEN1",
}

ORDER_PAID = {
    "id": "ORD_PAID1",
    "state": "paid",
    "total": 2000,
    "taxAmount": 100,
    "currency": "USD",
    "createdTime": 1700000500000,
    "modifiedTime": 1700000600000,
    "employee": {"id": "EMP2"},
    "lineItems": {
        "elements": [
            {
                "id": "LI1",
                "name": "Latte",
                "price": 500,
                "unitQty": 2,
                "unitName": "each",
                "refunded": False,
            }
        ]
    },
    "href": "https://api.clover.com/v3/merchants/M1/orders/ORD_PAID1",
}

ORDER_WITH_SERVICE_CHARGE = {
    "id": "ORD_SC1",
    "state": "paid",
    "total": 2200,
    "taxAmount": 100,
    "currency": "USD",
    "createdTime": 1700001000000,
    "modifiedTime": 1700001100000,
    "serviceCharge": {"name": "Gratuity", "amount": 200},
    "employee": {"id": "EMP1"},
}


# ── list_orders tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_orders_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    """Returns shaped orders with href and card data stripped."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(200, json={"elements": [ORDER_OPEN, ORDER_PAID]})
    )

    results = await list_orders(client, date_from="2024-01-01", date_to="2024-01-01")

    assert len(results) == 2
    assert results[0]["id"] == "ORD_OPEN1"
    assert results[0]["state"] == "open"
    assert "href" not in results[0]
    # Customer IDs only — no full customer objects with card data
    assert results[0]["customer_ids"] == ["CUST1"]
    assert results[1]["id"] == "ORD_PAID1"
    assert results[1]["state"] == "paid"


@pytest.mark.asyncio
async def test_list_orders_with_line_items(client: CloverClient, mock_http: respx.Router) -> None:
    """Line items are projected with lean fields only."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(200, json={"elements": [ORDER_PAID]})
    )

    results = await list_orders(client, date_from="2024-01-01", date_to="2024-01-01")

    assert "line_items" in results[0]
    li = results[0]["line_items"][0]
    assert li["name"] == "Latte"
    assert li["price"] == 500


@pytest.mark.asyncio
async def test_list_orders_with_service_charge(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Service charge is extracted from nested dict."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(200, json={"elements": [ORDER_WITH_SERVICE_CHARGE]})
    )

    results = await list_orders(client, date_from="2024-01-01", date_to="2024-01-01")

    assert results[0]["service_charge"] == 200


@pytest.mark.asyncio
async def test_list_orders_state_filter_valid(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Valid state filter is accepted."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(200, json={"elements": [ORDER_OPEN]})
    )

    results = await list_orders(client, date_from="2024-01-01", date_to="2024-01-01", state="open")

    assert results[0]["state"] == "open"


@pytest.mark.asyncio
async def test_list_orders_state_filter_invalid(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Invalid state raises ValueError before any HTTP call."""
    with pytest.raises(ValueError, match="state must be one of"):
        await list_orders(client, date_from="2024-01-01", date_to="2024-01-01", state="canceled")


@pytest.mark.asyncio
async def test_list_orders_defaults_to_today(client: CloverClient, mock_http: respx.Router) -> None:
    """No date args is valid and hits orders endpoint."""
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    results = await list_orders(client)
    assert results == []


@pytest.mark.asyncio
async def test_list_orders_inverted_dates_raises(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """date_from > date_to raises ValueError."""
    with pytest.raises(ValueError, match="must be ≤"):
        await list_orders(client, date_from="2024-12-31", date_to="2024-01-01")


@pytest.mark.asyncio
async def test_list_orders_limit_out_of_range(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """limit outside 1-200 raises ValueError."""
    with pytest.raises(ValueError, match="limit must be between"):
        await list_orders(client, limit=0)

    with pytest.raises(ValueError, match="limit must be between"):
        await list_orders(client, limit=201)


@pytest.mark.asyncio
async def test_list_orders_404(client: CloverClient, mock_http: respx.Router) -> None:
    """404 from orders list surfaces as CloverAPIError."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await list_orders(client, date_from="2024-01-01", date_to="2024-01-01")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_orders_empty(client: CloverClient, mock_http: respx.Router) -> None:
    """Empty result set returns empty list without error."""
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    results = await list_orders(client, date_from="2024-01-01", date_to="2024-01-01")

    assert results == []


# ── get_order tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_order_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    """Returns shaped order with expanded line items."""
    mock_http.get(_order_path("ORD_PAID1")).mock(return_value=httpx.Response(200, json=ORDER_PAID))

    result = await get_order(client, "ORD_PAID1")

    assert result["id"] == "ORD_PAID1"
    assert result["state"] == "paid"
    assert result["total"] == 2000
    assert "href" not in result
    assert "line_items" in result


@pytest.mark.asyncio
async def test_get_order_404(client: CloverClient, mock_http: respx.Router) -> None:
    """Non-existent order raises CloverAPIError with 404."""
    mock_http.get(_order_path("FAKEID")).mock(
        return_value=httpx.Response(
            404, json={"message": "Order not found", "details": "Order not found"}
        )
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await get_order(client, "FAKEID")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_order_empty_id_raises(client: CloverClient, mock_http: respx.Router) -> None:
    """Empty order_id raises ValueError before HTTP call."""
    with pytest.raises(ValueError, match="order_id must not be empty"):
        await get_order(client, "")

    with pytest.raises(ValueError, match="order_id must not be empty"):
        await get_order(client, "   ")


@pytest.mark.asyncio
async def test_get_order_no_card_data(client: CloverClient, mock_http: respx.Router) -> None:
    """Customer card data is never present in get_order output."""
    order_with_customer = {
        **ORDER_PAID,
        "customers": {
            "elements": [
                {
                    "id": "CUST1",
                    "cards": {"elements": [{"token": "tok_secret", "last4": "4242"}]},
                }
            ]
        },
    }
    mock_http.get(_order_path("ORD_PAID1")).mock(
        return_value=httpx.Response(200, json=order_with_customer)
    )

    result = await get_order(client, "ORD_PAID1")

    assert "customer_ids" in result
    assert result["customer_ids"] == ["CUST1"]
    # No full customer object, no card data
    assert "cards" not in result
    assert "cardTransaction" not in result


@pytest.mark.asyncio
async def test_get_order_429(client: CloverClient, mock_http: respx.Router) -> None:
    """429 rate limit surfaces as CloverAPIError."""
    mock_http.get(_order_path("ORD1")).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "60"})
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await get_order(client, "ORD1")

    assert exc_info.value.status_code == 429


# ── list_open_orders tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_open_orders_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    """Returns only open orders."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(200, json={"elements": [ORDER_OPEN]})
    )

    results = await list_open_orders(client)

    assert len(results) == 1
    assert results[0]["id"] == "ORD_OPEN1"
    assert results[0]["state"] == "open"


@pytest.mark.asyncio
async def test_list_open_orders_empty(client: CloverClient, mock_http: respx.Router) -> None:
    """No open orders returns an empty list."""
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    results = await list_open_orders(client)

    assert results == []


@pytest.mark.asyncio
async def test_list_open_orders_403(client: CloverClient, mock_http: respx.Router) -> None:
    """403 from orders endpoint surfaces as CloverAPIError."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(403, json={"message": "Missing ORDERS_R"})
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await list_open_orders(client)

    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_list_open_orders_strips_href(client: CloverClient, mock_http: respx.Router) -> None:
    """href field is never present in shaped output."""
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(200, json={"elements": [ORDER_OPEN]})
    )

    results = await list_open_orders(client)

    assert "href" not in results[0]
