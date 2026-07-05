"""Tests for the reporting-depth tools: get_sales_by_employee,
get_tips_by_employee, get_sales_by_hour."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.tools.reporting import (
    get_sales_by_employee,
    get_sales_by_hour,
    get_tips_by_employee,
)
from tests.conftest import TEST_MERCHANT_ID

MERCHANT_PAYLOAD = {
    "id": TEST_MERCHANT_ID,
    "name": "Test Café",
    "defaultCurrency": "USD",
    "timezone": "America/New_York",
    "country": "US",
}

EMPLOYEES_PAYLOAD = {
    "elements": [
        {"id": "EMP1", "name": "Alice"},
        {"id": "EMP2", "name": "Bob"},
    ]
}

# Two employees + one unassigned payment
PAYMENT_EMP1 = {
    "id": "PAY1",
    "amount": 1000,
    "tipAmount": 200,
    "result": "SUCCESS",
    "createdTime": 1700000100000,
    "employee": {"id": "EMP1"},
}
PAYMENT_EMP2 = {
    "id": "PAY2",
    "amount": 3000,
    "tipAmount": 100,
    "result": "SUCCESS",
    "createdTime": 1700000200000,
    "employee": {"id": "EMP2"},
}
PAYMENT_UNASSIGNED = {
    "id": "PAY3",
    "amount": 500,
    "tipAmount": 0,
    "result": "SUCCESS",
    "createdTime": 1700000300000,
}

# For get_sales_by_hour: two payments on the same UTC day, deterministic local
# hours in America/New_York (EST, UTC-5 in January):
#   1705332600000 -> 2024-01-15T15:30:00Z -> 10:30 local -> hour 10
#   1705351500000 -> 2024-01-15T20:45:00Z -> 15:45 local -> hour 15
PAYMENT_HOUR_10 = {
    "id": "PAYH1",
    "amount": 400,
    "result": "SUCCESS",
    "createdTime": 1705332600000,
}
PAYMENT_HOUR_15 = {
    "id": "PAYH2",
    "amount": 900,
    "result": "SUCCESS",
    "createdTime": 1705351500000,
}


def _p(suffix: str) -> str:
    return f"/v3/merchants/{TEST_MERCHANT_ID}{suffix}"


# ── get_sales_by_employee ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_sales_by_employee_groups_and_sorts(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Two employees + one unassigned payment: correct grouping, gross sums,
    sorted descending, names enriched from /employees."""
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_p("/payments")).mock(
        return_value=httpx.Response(
            200, json={"elements": [PAYMENT_EMP1, PAYMENT_EMP2, PAYMENT_UNASSIGNED]}
        )
    )
    mock_http.get(_p("/employees")).mock(return_value=httpx.Response(200, json=EMPLOYEES_PAYLOAD))

    result = await get_sales_by_employee(client, date_from="2024-01-01", date_to="2024-01-01")

    assert result["currency"] == "USD"
    assert result["payment_count"] == 3
    assert "note" not in result

    rows = result["by_employee"]
    assert [r["employee_id"] for r in rows] == ["EMP2", "EMP1", "unassigned"]
    assert rows[0]["gross_sales"]["amount"] == 3000
    assert rows[0]["employee_name"] == "Bob"
    assert rows[1]["gross_sales"]["amount"] == 1000
    assert rows[1]["employee_name"] == "Alice"
    assert rows[2]["employee_id"] == "unassigned"
    assert rows[2]["employee_name"] is None
    assert rows[2]["gross_sales"]["amount"] == 500
    assert all(r["payment_count"] == 1 for r in rows)


@pytest.mark.asyncio
async def test_get_sales_by_employee_degrades_without_employees_r(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """A 403 on /employees degrades to ids-only plus a note."""
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_p("/payments")).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_EMP1]})
    )
    mock_http.get(_p("/employees")).mock(
        return_value=httpx.Response(403, json={"message": "Missing EMPLOYEES_R"})
    )

    result = await get_sales_by_employee(client, date_from="2024-01-01", date_to="2024-01-01")

    assert result["by_employee"][0]["employee_id"] == "EMP1"
    assert result["by_employee"][0]["employee_name"] is None
    assert "note" in result
    assert "EMPLOYEES_R" in result["note"]


# ── get_tips_by_employee ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tips_by_employee_sums_tips_and_total(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """tipAmount summed per employee, plus a top-level total_tips."""
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_p("/payments")).mock(
        return_value=httpx.Response(
            200, json={"elements": [PAYMENT_EMP1, PAYMENT_EMP2, PAYMENT_UNASSIGNED]}
        )
    )
    mock_http.get(_p("/employees")).mock(return_value=httpx.Response(200, json=EMPLOYEES_PAYLOAD))

    result = await get_tips_by_employee(client, date_from="2024-01-01", date_to="2024-01-01")

    assert result["total_tips"]["amount"] == 300  # 200 + 100 + 0
    rows = result["by_employee"]
    assert [r["employee_id"] for r in rows] == ["EMP1", "EMP2", "unassigned"]
    assert rows[0]["tips"]["amount"] == 200
    assert rows[0]["employee_name"] == "Alice"
    assert rows[1]["tips"]["amount"] == 100
    assert rows[1]["employee_name"] == "Bob"
    assert rows[2]["tips"]["amount"] == 0


# ── get_sales_by_hour ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_sales_by_hour_buckets_local_hours(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Payments at known epoch-ms times bucket into the correct local hours
    for the merchant's America/New_York timezone."""
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_p("/payments")).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_HOUR_10, PAYMENT_HOUR_15]})
    )

    result = await get_sales_by_hour(client, date="2024-01-15")

    assert result["date"] == "2024-01-15"
    assert result["timezone"] == "America/New_York"
    assert "note" not in result

    by_hour = result["by_hour"]
    assert [b["hour"] for b in by_hour] == [10, 15]
    assert by_hour[0]["gross_sales"]["amount"] == 400
    assert by_hour[0]["payment_count"] == 1
    assert by_hour[1]["gross_sales"]["amount"] == 900


@pytest.mark.asyncio
async def test_get_sales_by_hour_falls_back_to_utc_on_bad_timezone(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """An invalid/missing merchant timezone falls back to UTC with a note."""
    bad_tz_payload = {**MERCHANT_PAYLOAD, "timezone": "Not/A_Real_Zone"}
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=bad_tz_payload))
    mock_http.get(_p("/payments")).mock(
        return_value=httpx.Response(200, json={"elements": [PAYMENT_HOUR_10]})
    )

    result = await get_sales_by_hour(client, date="2024-01-15")

    assert result["timezone"] == "UTC"
    assert "note" in result
    # 1705332600000 -> 2024-01-15T15:30:00Z -> hour 15 in UTC
    assert result["by_hour"][0]["hour"] == 15


@pytest.mark.asyncio
async def test_get_sales_by_hour_uses_local_day_not_utc_day(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Bucketing is by the merchant's LOCAL day. In America/New_York (EST, UTC-5):
    - 2024-01-16T02:00:00Z  == 2024-01-15 21:00 local  → counted for Jan 15, hour 21
    - 2024-01-15T02:00:00Z  == 2024-01-14 21:00 local  → excluded (prior local day)
    A naive UTC-day window would miss the first (dinner rush) and wrongly keep the second."""
    evening_local = {"id": "EVE", "amount": 700, "result": "SUCCESS", "createdTime": 1705370400000}
    prior_local = {"id": "PRE", "amount": 999, "result": "SUCCESS", "createdTime": 1705284000000}
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_p("/payments")).mock(
        return_value=httpx.Response(200, json={"elements": [evening_local, prior_local]})
    )

    result = await get_sales_by_hour(client, date="2024-01-15")

    by_hour = result["by_hour"]
    assert [b["hour"] for b in by_hour] == [21]  # only the local-Jan-15 payment
    assert by_hour[0]["gross_sales"]["amount"] == 700
    assert by_hour[0]["payment_count"] == 1


@pytest.mark.asyncio
async def test_get_sales_by_hour_defaults_to_today(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """No date arg → defaults to today (UTC) without error."""
    mock_http.get(_p("")).mock(return_value=httpx.Response(200, json=MERCHANT_PAYLOAD))
    mock_http.get(_p("/payments")).mock(return_value=httpx.Response(200, json={"elements": []}))

    result = await get_sales_by_hour(client)

    assert result["by_hour"] == []
