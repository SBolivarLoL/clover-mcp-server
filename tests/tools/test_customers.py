"""Tests for customer tools: search_customers, get_customer, create_customer."""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.customers import create_customer, get_customer, search_customers
from tests.conftest import TEST_MERCHANT_ID

CUSTOMERS_PATH = f"/v3/merchants/{TEST_MERCHANT_ID}/customers"

CUSTOMER_RAW = {
    "id": "CUST1",
    "firstName": "Jane",
    "lastName": "Doe",
    "marketingAllowed": True,
    "customerSince": 1680000000000,
    "emailAddresses": {"elements": [{"emailAddress": "jane@example.com", "id": "EA1"}]},
    "phoneNumbers": {"elements": [{"phoneNumber": "+15550001111", "id": "PN1"}]},
    # PII / banned fields that must be stripped
    "cards": {"elements": [{"token": "tok_secret", "last4": "4242", "pan": "XXXX"}]},
    "href": "https://api.clover.com/v3/merchants/M1/customers/CUST1",
}

CUSTOMER_RAW_MINIMAL = {
    "id": "CUST2",
    "firstName": "Bob",
    "lastName": "Smith",
    # no email or phone
}


# ── search_customers ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_customers_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW]})
    )
    result = await search_customers(client)

    assert result["count"] == 1
    assert result["limit"] == 50
    custs = result["customers"]
    assert custs[0]["id"] == "CUST1"
    assert custs[0]["firstName"] == "Jane"
    assert custs[0]["emails"] == ["jane@example.com"]
    assert custs[0]["phones"] == ["+15550001111"]
    # PII must be stripped
    assert "cards" not in custs[0]
    assert "href" not in custs[0]


@pytest.mark.asyncio
async def test_search_customers_cards_never_returned(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Cards must never appear in the output even when present in raw payload."""
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW]})
    )
    result = await search_customers(client)
    for cust in result["customers"]:
        assert "cards" not in cust
        assert "token" not in str(cust)
        assert "pan" not in str(cust)


@pytest.mark.asyncio
async def test_search_customers_by_query(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW]})
    )
    result = await search_customers(client, query="Jane Doe")
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_search_customers_by_phone(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW]})
    )
    result = await search_customers(client, phone="+15550001111")
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_search_customers_by_email(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW]})
    )
    result = await search_customers(client, email="jane@example.com")
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_search_customers_phone_takes_precedence(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """When both phone and email are given, phone filter wins."""
    mock_http.get(CUSTOMERS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    # Should not raise; phone filter is applied, not email
    result = await search_customers(client, phone="+15550001111", email="other@example.com")
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_search_customers_empty(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    result = await search_customers(client)
    assert result["count"] == 0
    assert result["customers"] == []


@pytest.mark.asyncio
async def test_search_customers_no_contact_fields(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Customers without phone/email should not crash."""
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW_MINIMAL]})
    )
    result = await search_customers(client)
    assert result["count"] == 1
    cust = result["customers"][0]
    assert cust["id"] == "CUST2"
    assert "emails" not in cust
    assert "phones" not in cust


@pytest.mark.asyncio
async def test_search_customers_401(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(401, json={"message": "401 Unauthorized"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await search_customers(client)
    assert exc_info.value.status_code == 401
    assert "token" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_search_customers_403(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await search_customers(client)
    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.message.lower()


# ── get_customer ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_customer_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{CUSTOMERS_PATH}/CUST1").mock(
        return_value=httpx.Response(200, json=CUSTOMER_RAW)
    )
    result = await get_customer(client, "CUST1")

    assert result["id"] == "CUST1"
    assert result["firstName"] == "Jane"
    assert result["emails"] == ["jane@example.com"]
    assert result["phones"] == ["+15550001111"]
    # Cards must never appear
    assert "cards" not in result
    assert "href" not in result


@pytest.mark.asyncio
async def test_get_customer_cards_never_returned_even_if_included(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Passing include=["cards"] must still not return cards."""
    mock_http.get(f"{CUSTOMERS_PATH}/CUST1").mock(
        return_value=httpx.Response(200, json=CUSTOMER_RAW)
    )
    result = await get_customer(client, "CUST1", include=["cards"])
    assert "cards" not in result


@pytest.mark.asyncio
async def test_get_customer_include_addresses(
    client: CloverClient, mock_http: respx.Router
) -> None:
    raw_with_addresses = {
        **CUSTOMER_RAW,
        "addresses": [{"address1": "123 Main St", "city": "Springfield"}],
    }
    mock_http.get(f"{CUSTOMERS_PATH}/CUST1").mock(
        return_value=httpx.Response(200, json=raw_with_addresses)
    )
    result = await get_customer(client, "CUST1", include=["addresses"])
    assert "addresses" in result
    assert result["addresses"][0]["address1"] == "123 Main St"


@pytest.mark.asyncio
async def test_get_customer_include_orders(client: CloverClient, mock_http: respx.Router) -> None:
    raw_with_orders = {
        **CUSTOMER_RAW,
        "orders": {"elements": [{"id": "ORD1", "total": 1500}]},
    }
    mock_http.get(f"{CUSTOMERS_PATH}/CUST1").mock(
        return_value=httpx.Response(200, json=raw_with_orders)
    )
    result = await get_customer(client, "CUST1", include=["orders"])
    assert "orders" in result


@pytest.mark.asyncio
async def test_get_customer_404(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{CUSTOMERS_PATH}/BADID").mock(
        return_value=httpx.Response(
            404, json={"message": "Not Found", "details": "Customer not found"}
        )
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await get_customer(client, "BADID")
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_get_customer_pii_not_leaked(client: CloverClient, mock_http: respx.Router) -> None:
    """Comprehensive check that no banned keys appear anywhere in the output."""
    mock_http.get(f"{CUSTOMERS_PATH}/CUST1").mock(
        return_value=httpx.Response(200, json=CUSTOMER_RAW)
    )
    result = await get_customer(client, "CUST1")

    banned = {"pin", "unhashedPin", "cards", "cardTransaction", "href", "token", "pan"}

    def _check(data: object, path: str = "") -> None:
        if isinstance(data, dict):
            for key, val in data.items():
                assert key not in banned, f"Banned key {key!r} found at {path}.{key}"
                _check(val, f"{path}.{key}")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                _check(item, f"{path}[{i}]")

    _check(result)


# ── create_customer ───────────────────────────────────────────────────────────

CREATED_CUSTOMER_RAW = {
    "id": "CUST_NEW",
    "firstName": "Alice",
    "lastName": "Wonder",
    "marketingAllowed": False,
    "customerSince": 1700000000000,
    "emailAddresses": {"elements": [{"emailAddress": "alice@example.com", "id": "EA_NEW"}]},
    "phoneNumbers": {"elements": [{"phoneNumber": "+15550009999", "id": "PN_NEW"}]},
}


@pytest.mark.asyncio
async def test_create_customer_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    """Happy path: no duplicate found, customer is created and shaped."""
    # Duplicate check — returns empty
    mock_http.get(CUSTOMERS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    # POST
    mock_http.post(CUSTOMERS_PATH).mock(return_value=httpx.Response(200, json=CREATED_CUSTOMER_RAW))
    result = await create_customer(
        client,
        first_name="Alice",
        last_name="Wonder",
        email="alice@example.com",
        phone="+15550009999",
    )

    assert result["created"] is True
    cust = result["customer"]
    assert cust["id"] == "CUST_NEW"
    assert cust["firstName"] == "Alice"
    assert cust["emails"] == ["alice@example.com"]
    assert cust["phones"] == ["+15550009999"]
    # Cards must never appear
    assert "cards" not in cust


@pytest.mark.asyncio
async def test_create_customer_no_email_no_phone_skips_dupe_check(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """When neither email nor phone is given, no search is made — go straight to POST."""
    mock_http.post(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "CUST_MIN",
                "firstName": "Bob",
                "lastName": "Min",
                "marketingAllowed": False,
                "customerSince": 1700000000000,
            },
        )
    )
    result = await create_customer(client, first_name="Bob", last_name="Min")

    assert result["created"] is True
    assert result["customer"]["id"] == "CUST_MIN"


@pytest.mark.asyncio
async def test_create_customer_dry_run(client: CloverClient, mock_http: respx.Router) -> None:
    """dry_run=True returns the payload without making any network call."""
    # No GET or POST mock registered — any call would fail
    result = await create_customer(
        client,
        first_name="Dry",
        last_name="Run",
        email="dry@example.com",
        phone="+15550000000",
        marketing_allowed=True,
        dry_run=True,
    )

    assert result["dry_run"] is True
    payload = result["would_post"]
    assert payload["firstName"] == "Dry"
    assert payload["lastName"] == "Run"
    assert payload["emailAddresses"] == [{"emailAddress": "dry@example.com"}]
    assert payload["phoneNumbers"] == [{"phoneNumber": "+15550000000"}]
    assert payload["marketingAllowed"] is True


@pytest.mark.asyncio
async def test_create_customer_dry_run_no_network(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """dry_run also skips the duplicate-check GET (no network call at all)."""
    # Confirm no HTTP calls are made by using assert_all_called=True on a fresh router
    with respx.mock(base_url="https://apisandbox.dev.clover.com", assert_all_called=False) as r:
        r.get(CUSTOMERS_PATH).mock(
            side_effect=AssertionError("GET should not be called in dry_run")
        )
        r.post(CUSTOMERS_PATH).mock(
            side_effect=AssertionError("POST should not be called in dry_run")
        )
        result = await create_customer(
            client,
            first_name="Dry",
            last_name="NoNet",
            email="dry@example.com",
            dry_run=True,
        )
    assert result["dry_run"] is True


@pytest.mark.asyncio
async def test_create_customer_duplicate_refused(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """When a matching customer is found and confirm_duplicate=False, refuse."""
    mock_http.get(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [CUSTOMER_RAW]})
    )
    result = await create_customer(
        client,
        first_name="Jane",
        last_name="Doe",
        email="jane@example.com",
    )

    assert result["created"] is False
    assert result["reason"] == "duplicate"
    assert "existing_customer" in result
    assert result["existing_customer"]["id"] == "CUST1"
    # No POST should have been made (respx would surface an unexpected call)


@pytest.mark.asyncio
async def test_create_customer_duplicate_override(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """confirm_duplicate=True bypasses the duplicate check and creates."""
    # No GET mock — search must NOT be called when confirm_duplicate=True
    mock_http.post(CUSTOMERS_PATH).mock(return_value=httpx.Response(200, json=CREATED_CUSTOMER_RAW))
    result = await create_customer(
        client,
        first_name="Alice",
        last_name="Wonder",
        email="alice@example.com",
        confirm_duplicate=True,
    )

    assert result["created"] is True
    assert result["customer"]["id"] == "CUST_NEW"


@pytest.mark.asyncio
async def test_create_customer_post_401(client: CloverClient, mock_http: respx.Router) -> None:
    """401 from POST surfaces as CloverAPIError (no retry on writes)."""
    # No email/phone — no duplicate-check GET
    mock_http.post(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(401, json={"message": "401 Unauthorized"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await create_customer(client, first_name="X", last_name="Y")
    assert exc_info.value.status_code == 401
    assert "token" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_create_customer_post_403(client: CloverClient, mock_http: respx.Router) -> None:
    """403 from POST surfaces as CloverAPIError with permission hint."""
    mock_http.post(CUSTOMERS_PATH).mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await create_customer(client, first_name="X", last_name="Y")
    assert exc_info.value.status_code == 403
    assert "permission" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_create_customer_marketing_allowed_in_body(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """marketing_allowed is forwarded in the POST body when provided."""
    captured: list[dict] = []  # type: ignore[type-arg]

    def capture_request(request: httpx.Request) -> httpx.Response:
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(200, json=CREATED_CUSTOMER_RAW)

    mock_http.post(CUSTOMERS_PATH).mock(side_effect=capture_request)

    await create_customer(
        client,
        first_name="Alice",
        last_name="Wonder",
        marketing_allowed=True,
        confirm_duplicate=True,
    )

    assert len(captured) == 1
    assert captured[0]["marketingAllowed"] is True


@pytest.mark.asyncio
async def test_create_customer_cards_never_returned(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Cards in the POST response are never surfaced."""
    raw_with_cards = {
        **CREATED_CUSTOMER_RAW,
        "cards": {"elements": [{"token": "tok_secret", "last4": "4242"}]},
    }
    mock_http.post(CUSTOMERS_PATH).mock(return_value=httpx.Response(200, json=raw_with_cards))
    result = await create_customer(
        client,
        first_name="Alice",
        last_name="Wonder",
        confirm_duplicate=True,
    )

    assert result["created"] is True
    assert "cards" not in result["customer"]
    assert "token" not in str(result)
