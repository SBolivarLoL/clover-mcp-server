"""Tests for the v1.1 read tools: employees, shifts, categories, modifiers,
taxes, devices, and get_top_items."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.tools.employees import (
    get_employee,
    list_active_shifts,
    list_employees,
    list_shifts,
)
from clover_mcp.tools.inventory import list_categories, list_modifiers, list_taxes
from clover_mcp.tools.merchant import list_devices
from clover_mcp.tools.reporting import get_top_items
from tests.conftest import TEST_MERCHANT_ID

MERCHANT_PAYLOAD = {
    "id": TEST_MERCHANT_ID,
    "name": "Test Café",
    "defaultCurrency": "USD",
    "timezone": "America/New_York",
    "country": "US",
}


def _p(suffix: str) -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}{suffix}"


# ── employees ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_employees_strips_pin(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(_p("/employees")).mock(
        return_value=httpx.Response(
            200,
            json={"elements": [{"id": "E1", "name": "Bob", "role": "MANAGER", "pin": "1234"}]},
        )
    )
    result = await list_employees(client)
    assert result["count"] == 1
    assert result["employees"][0]["id"] == "E1"
    assert "pin" not in result["employees"][0]


@pytest.mark.asyncio
async def test_list_employees_bad_limit(client: CloverClient, mock_http: respx.Router) -> None:
    with pytest.raises(ValueError, match="limit must be between"):
        await list_employees(client, limit=0)


@pytest.mark.asyncio
async def test_get_employee_empty_id(client: CloverClient, mock_http: respx.Router) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await get_employee(client, "  ")


# ── shifts ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_shifts_for_employee(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(_p("/employees/E1/shifts")).mock(
        return_value=httpx.Response(
            200,
            json={"elements": [{"id": "S1", "inTime": 1, "outTime": 2, "employee": {"id": "E1"}}]},
        )
    )
    result = await list_shifts(client, employee_id="E1")
    assert result["count"] == 1
    assert result["shifts"][0]["employee_id"] == "E1"


@pytest.mark.asyncio
async def test_list_active_shifts_filters_open(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(_p("/employees")).mock(
        return_value=httpx.Response(200, json={"elements": [{"id": "E1", "name": "Bob"}]})
    )
    mock_http.get(_p("/employees/E1/shifts")).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {"id": "S1", "inTime": 1, "outTime": 2},  # closed
                    {"id": "S2", "inTime": 3, "outTime": 0},  # open
                ]
            },
        )
    )
    result = await list_active_shifts(client)
    assert result["count"] == 1
    assert result["shifts"][0]["id"] == "S2"
    # name injected from the iterated employee (shift payload carries only id)
    assert result["shifts"][0]["employee_name"] == "Bob"


@pytest.mark.asyncio
async def test_list_shifts_inverted_dates(client: CloverClient, mock_http: respx.Router) -> None:
    with pytest.raises(ValueError, match="must be ≤"):
        await list_shifts(client, date_from="2024-12-31", date_to="2024-01-01")


# ── categories / modifiers / taxes / devices ──────────────────────────────────


@pytest.mark.asyncio
async def test_list_categories(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(_p("/categories")).mock(
        return_value=httpx.Response(200, json={"elements": [{"id": "C1", "name": "Drinks"}]})
    )
    result = await list_categories(client)
    assert result["count"] == 1
    assert result["categories"][0]["name"] == "Drinks"


@pytest.mark.asyncio
async def test_list_modifiers_nests_modifiers(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(_p("/modifier_groups")).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "id": "MG1",
                        "name": "Size",
                        "modifiers": {"elements": [{"id": "M1", "name": "Large", "price": 50}]},
                    }
                ]
            },
        )
    )
    result = await list_modifiers(client)
    assert result["modifier_groups"][0]["modifiers"][0]["name"] == "Large"


@pytest.mark.asyncio
async def test_list_taxes_computes_percent(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(_p("/tax_rates")).mock(
        return_value=httpx.Response(
            200, json={"elements": [{"id": "T1", "name": "Sales Tax", "rate": 825000}]}
        )
    )
    result = await list_taxes(client)
    assert result["tax_rates"][0]["rate_percent"] == 8.25


@pytest.mark.asyncio
async def test_list_devices(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(_p("/devices")).mock(
        return_value=httpx.Response(
            200, json={"elements": [{"id": "D1", "name": "Station", "serial": "ABC"}]}
        )
    )
    result = await list_devices(client)
    assert result["devices"][0]["serial"] == "ABC"


# ── get_top_items ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_top_items_ranks_by_units(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"/v3/merchants/{TEST_MERCHANT_ID}").mock(
        return_value=httpx.Response(200, json=MERCHANT_PAYLOAD)
    )
    mock_http.get(_p("/orders")).mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "id": "O1",
                        "lineItems": {
                            "elements": [
                                {"id": "L1", "name": "Latte", "price": 500},
                                {"id": "L2", "name": "Latte", "price": 500},
                                {"id": "L3", "name": "Muffin", "price": 300},
                                {"id": "L4", "name": "Refunded", "price": 999, "refunded": True},
                            ]
                        },
                    }
                ]
            },
        )
    )
    result = await get_top_items(client, date_from="2024-01-01", date_to="2024-01-01")
    assert result["items"][0]["name"] == "Latte"
    assert result["items"][0]["units_sold"] == 2
    assert result["items"][0]["revenue"]["amount"] == 1000
    # refunded line item excluded
    assert all(it["name"] != "Refunded" for it in result["items"])


@pytest.mark.asyncio
async def test_get_top_items_bad_top_n(client: CloverClient, mock_http: respx.Router) -> None:
    with pytest.raises(ValueError, match="top_n must be between"):
        await get_top_items(client, top_n=0)
