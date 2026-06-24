"""Tests for the get_merchant_info tool."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.merchant import get_merchant_info, list_tenders
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
                "elements": [
                    {
                        "id": "T1",
                        "label": "Cash",
                        "labelKey": "com.clover.tender.cash",
                        "enabled": True,
                        "opensCashDrawer": True,
                        "secret": "drop-me",
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
    assert "secret" not in t  # allowlist drops everything else
