"""Tests for the reporting tools: get_sales_summary, list_payments."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.reporting import get_sales_summary, list_payments
from tests.conftest import TEST_MERCHANT_ID

# ── Shared fixtures / helpers ─────────────────────────────────────────────────

MERCHANT_PAYLOAD = {
    "id": TEST_MERCHANT_ID,
    "name": "Test Café",
    "defaultCurrency": "USD",
    "timezone": "America/New_York",
    "country": "US",
}

# A minimal SUCCESS payment
PAYMENT_1 = {
    "id": "PAY1",
    "amount": 1050,
    "tipAmount": 100,
    "taxAmount": 50,
    "result": "SUCCESS",
    "createdTime": 1700000100000,
    "offline": False,
    "tender": {"id": "CREDIT", "label": "CREDIT_CARD"},
    "employee": {"id": "EMP1"},
    "order": {"id": "ORD1"},
    "cardTransaction": {"last4": "4242", "token": "tok_secret"},  # must be stripped
}

# A second payment via CASH
PAYMENT_2 = {
    "id": "PAY2",
    "amount": 500,
    "tipAmount": 0,
    "taxAmount": 25,
    "result": "SUCCESS",
    "createdTime": 1700000200000,
    "offline": False,
    "tender": {"id": "CASH", "label": "Cash"},
    "employee": {"id": "EMP1"},
    "order": {"id": "ORD2"},
}

# An offline payment
PAYMENT_OFFLINE = {
    "id": "PAY3",
    "amount": 800,
    "tipAmount": 0,
    "taxAmount": 40,
    "result": "SUCCESS",
    "createdTime": 1700000300000,
    "offline": True,
    "tender": {"id": "CREDIT", "label": "CREDIT_CARD"},
    "employee": {"id": "EMP2"},
    "order": {"id": "ORD3"},
}


def _merchant_path() -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}"


def _payments_path() -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}/payments"


def _orders_path() -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}/orders"


# An order carrying a service charge (lives on the order, not the payment)
ORDER_WITH_SC = {"id": "ORD1", "serviceCharge": {"name": "Gratuity", "amount": 200}}


# ── get_sales_summary tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_sales_summary_empty_window(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Empty payments list returns zeros without error."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(return_value=httpx.Response(200, json={"elements": []}))
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    result = await get_sales_summary(client, date_from="2024-01-01", date_to="2024-01-01")

    assert result["payment_count"] == 0
    assert result["gross_sales"]["amount"] == 0
    assert result["service_charges_collected"]["amount"] == 0
    assert result["currency"] == "USD"
    assert result["window"]["from"] == "2024-01-01"
    assert result["window"]["to"] == "2024-01-01"
    assert "note" not in result  # no offline flag


@pytest.mark.asyncio
async def test_get_sales_summary_with_payments(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Summary correctly aggregates amounts, tips, and taxes."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_1, PAYMENT_2]})
    )
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    result = await get_sales_summary(client, date_from="2024-01-01", date_to="2024-01-01")

    # gross = 1050 + 500 = 1550
    assert result["gross_sales"]["amount"] == 1550
    assert result["gross_sales"]["formatted"] == "$15.50"
    # tips = 100 + 0 = 100
    assert result["tips_collected"]["amount"] == 100
    # taxes = 50 + 25 = 75
    assert result["tax_collected"]["amount"] == 75
    # two SUCCESS payments
    assert result["payment_count"] == 2
    # average ticket
    assert result["average_ticket"]["amount"] == 775  # 1550 // 2
    # by_tender
    assert "CREDIT_CARD" in result["by_tender"]
    assert result["by_tender"]["CREDIT_CARD"]["amount"] == 1050
    assert "Cash" in result["by_tender"]
    assert result["by_tender"]["Cash"]["amount"] == 500


@pytest.mark.asyncio
async def test_get_sales_summary_offline_flag(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """When offline payments exist, a note flag is included."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_OFFLINE]})
    )
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    result = await get_sales_summary(client, date_from="2024-01-01", date_to="2024-01-01")

    assert result["payment_count"] == 1
    assert "note" in result
    assert "offline" in result["note"]


@pytest.mark.asyncio
async def test_get_sales_summary_defaults_to_today(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """No date args → window.from and window.to are the same date (today)."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(return_value=httpx.Response(200, json={"elements": []}))
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    result = await get_sales_summary(client)

    assert result["window"]["from"] == result["window"]["to"]


@pytest.mark.asyncio
async def test_get_sales_summary_inverted_dates_raises(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """date_from > date_to must raise ValueError."""
    with pytest.raises(ValueError, match="must be ≤"):
        await get_sales_summary(client, date_from="2024-12-31", date_to="2024-01-01")


@pytest.mark.asyncio
async def test_get_sales_summary_bad_date_format(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Non-ISO date string raises ValueError."""
    with pytest.raises(ValueError, match="ISO-8601"):
        await get_sales_summary(client, date_from="01/15/2024")


@pytest.mark.asyncio
async def test_get_sales_summary_403(client: CloverClient, mock_http: respx.Router) -> None:
    """403 from payments endpoint surfaces as CloverAPIError."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(403, json={"message": "Missing PAYMENTS_R"})
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await get_sales_summary(client, date_from="2024-01-01", date_to="2024-01-01")

    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_get_sales_summary_no_card_data_leaked(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """cardTransaction must never appear in summary output."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_1]})
    )
    mock_http.get(_orders_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    result = await get_sales_summary(client, date_from="2024-01-01", date_to="2024-01-01")

    # The summary aggregates — it never returns individual payment records,
    # so no card data can leak. Sanity-check the top-level keys.
    assert "cardTransaction" not in result
    assert "by_tender" in result


@pytest.mark.asyncio
async def test_get_sales_summary_service_charges_from_orders(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """service_charges_collected is summed from orders, not payments."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_1]})
    )
    mock_http.get(_orders_path()).mock(
        return_value=httpx.Response(
            200,
            json={"elements": [ORDER_WITH_SC, {"id": "ORD2"}]},  # second order has no SC
        )
    )

    result = await get_sales_summary(client, date_from="2024-01-01", date_to="2024-01-01")

    assert result["service_charges_collected"]["amount"] == 200
    assert result["service_charges_collected"]["formatted"] == "$2.00"
    # service charges are reported separately, not folded into gross
    assert result["gross_sales"]["amount"] == 1050


# ── list_payments tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_payments_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    """Returns shaped payments with card data stripped."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_1, PAYMENT_2]})
    )

    results = await list_payments(client, date_from="2024-01-01", date_to="2024-01-01")

    assert len(results) == 2
    assert results[0]["id"] == "PAY1"
    assert results[0]["amount"] == 1050
    assert "cardTransaction" not in results[0]
    assert results[0]["tender"] == "CREDIT_CARD"
    assert results[0]["order_id"] == "ORD1"


@pytest.mark.asyncio
async def test_list_payments_empty(client: CloverClient, mock_http: respx.Router) -> None:
    """Empty result set returns an empty list without error."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    results = await list_payments(client, date_from="2024-01-01", date_to="2024-01-01")

    assert results == []


@pytest.mark.asyncio
async def test_list_payments_defaults_to_today(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """No date args is valid and calls payments endpoint."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(return_value=httpx.Response(200, json={"elements": []}))

    results = await list_payments(client)
    assert results == []


@pytest.mark.asyncio
async def test_list_payments_limit_out_of_range(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """limit outside 1-200 raises ValueError."""
    with pytest.raises(ValueError, match="limit must be between"):
        await list_payments(client, limit=0)

    with pytest.raises(ValueError, match="limit must be between"):
        await list_payments(client, limit=201)


@pytest.mark.asyncio
async def test_list_payments_401(client: CloverClient, mock_http: respx.Router) -> None:
    """401 surfaces as CloverAPIError."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await list_payments(client, date_from="2024-01-01", date_to="2024-01-01")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_list_payments_shaped_fields(client: CloverClient, mock_http: respx.Router) -> None:
    """Shaped payment must include expected allowed fields."""
    mock_http.get(_merchant_path()).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_payments_path()).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_1]})
    )

    results = await list_payments(client, date_from="2024-01-01", date_to="2024-01-01")

    p = results[0]
    assert p["id"] == "PAY1"
    assert p["amount"] == 1050
    assert p["tipAmount"] == 100
    assert p["taxAmount"] == 50
    assert p["result"] == "SUCCESS"
    assert p["employee_id"] == "EMP1"
    # Card transaction must be absent
    assert "cardTransaction" not in p
