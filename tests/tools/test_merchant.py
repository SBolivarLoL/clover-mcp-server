"""Tests for the get_merchant_info tool."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.merchant import get_merchant_info, get_merchant_properties, list_tenders
from tests.conftest import TEST_MERCHANT_ID

MERCHANT_PAYLOAD = {
    "id": TEST_MERCHANT_ID,
    "name": "Test Café",
    "defaultCurrency": "USD",
    "timezone": "America/New_York",
    "country": "US",
    "businessType": "FOOD_AND_BEVERAGE",
    "href": "https://api.clover.com/v3/merchants/" + TEST_MERCHANT_ID,
    "internalSecret": "should-be-stripped",
}


@pytest.mark.asyncio
async def test_get_merchant_info_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    path = f"/v3/merchants/{TEST_MERCHANT_ID}"
    mock_http.get(path).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))

    result = await get_merchant_info(client)

    assert result["id"] == TEST_MERCHANT_ID
    assert result["name"] == "Test Café"
    assert result["defaultCurrency"] == "USD"
    assert result["timezone"] == "America/New_York"
    # Shaping: href and internal fields must be stripped
    assert "href" not in result
    assert "internalSecret" not in result


@pytest.mark.asyncio
async def test_get_merchant_info_401(client: CloverClient, mock_http: respx.Router) -> None:
    path = f"/v3/merchants/{TEST_MERCHANT_ID}"
    mock_http.get(path).mock(return_value=httpx.Response(401, json={"message": "Unauthorized"}))

    with pytest.raises(CloverAPIError) as exc_info:
        await get_merchant_info(client)

    assert exc_info.value.status_code == 401
    assert "token" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_get_merchant_info_403(client: CloverClient, mock_http: respx.Router) -> None:
    path = f"/v3/merchants/{TEST_MERCHANT_ID}"
    mock_http.get(path).mock(
        return_value=httpx.Response(403, json={"message": "Merchant not authorized"})
    )

    with pytest.raises(CloverAPIError) as exc_info:
        await get_merchant_info(client)

    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_list_tenders(client: CloverClient, mock_http: respx.Router) -> None:
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/tenders"
    mock_http.get(path).mock(
        return_value=httpx.Response(
            200,
            json={
                # Sandbox-verified element shape (2026-06-24)
                "elements": [
                    {
                        "id": "T1",
                        "label": "Cash",
                        "labelKey": "com.clover.tender.cash",
                        "enabled": True,
                        "opensCashDrawer": True,
                        "editable": False,
                        "visible": True,
                        "supportsCashDiscount": False,
                        "href": "https://sandbox.dev.clover.com/v3/merchants/M1/tenders/T1",
                    }
                ]
            },
        )
    )

    result = await list_tenders(client)

    assert result["count"] == 1
    t = result["tenders"][0]
    assert t["label"] == "Cash"
    assert t["opensCashDrawer"] is True
    assert t["supportsCashDiscount"] is False
    assert "href" not in t  # allowlist drops href and everything else


@pytest.mark.asyncio
async def test_get_merchant_properties_drops_banking(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """POS settings surface; banking/account numbers never do."""
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/properties"
    mock_http.get(path).mock(
        return_value=httpx.Response(
            200,
            json={
                "defaultCurrency": "USD",
                "timezone": "America/Chicago",
                "tipsEnabled": False,
                "trackStock": False,
                "supportPhone": "+1 555 0100",
                "abaAccountNumber": "000000000000000",
                "ddaAccountNumber": "***********3770",
                "href": f"https://sandbox.dev.clover.com/v3/merchants/{TEST_MERCHANT_ID}/properties",
            },
        )
    )

    result = await get_merchant_properties(client)

    assert result["defaultCurrency"] == "USD"
    assert result["timezone"] == "America/Chicago"
    assert result["tipsEnabled"] is False
    assert "abaAccountNumber" not in result
    assert "ddaAccountNumber" not in result
    assert "href" not in result
