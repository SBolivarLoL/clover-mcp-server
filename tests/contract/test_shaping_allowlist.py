"""Contract tests: shaping allowlist — PII, card data, and hrefs must never leak.

These tests feed known-bad Clover payloads (cards, employee PINs, hrefs) through
every shaper and assert the sensitive fields are absent from the output.
If a shaper accidentally passes through PII, these tests catch it.
"""

from clover_mcp.shaping import (
    shape_attribute,
    shape_cash_event,
    shape_category,
    shape_customer,
    shape_device,
    shape_employee,
    shape_item,
    shape_item_group,
    shape_merchant,
    shape_merchant_properties,
    shape_modifier_group,
    shape_opening_hours,
    shape_order,
    shape_order_type,
    shape_payment,
    shape_refund,
    shape_role,
    shape_shift,
    shape_tag,
    shape_tax,
    shape_tender,
)

BANNED_KEYS = {"pin", "unhashedPin", "cards", "cardTransaction", "href", "token", "pan"}


def _assert_no_banned(data: object, path: str = "") -> None:
    """Recursively assert that no banned key appears anywhere in the output."""
    if isinstance(data, dict):
        for key, val in data.items():
            assert key not in BANNED_KEYS, f"Banned key {key!r} found at {path}.{key}"
            _assert_no_banned(val, f"{path}.{key}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            _assert_no_banned(item, f"{path}[{i}]")


DIRTY_CUSTOMER = {
    "id": "C1",
    "firstName": "Jane",
    "lastName": "Doe",
    "emailAddresses": {"elements": [{"emailAddress": "jane@example.com"}]},
    "phoneNumbers": {"elements": [{"phoneNumber": "+15550001111"}]},
    "marketingAllowed": True,
    "cards": {"elements": [{"token": "tok_secret", "last4": "4242", "pan": "XXXX"}]},
    "href": "https://api.clover.com/v3/merchants/M1/customers/C1",
}

DIRTY_EMPLOYEE = {
    "id": "E1",
    "name": "Bob Smith",
    "role": "MANAGER",
    "pin": "1234",
    "unhashedPin": "1234",
    "href": "https://api.clover.com/v3/merchants/M1/employees/E1",
}

DIRTY_PAYMENT = {
    "id": "P1",
    "amount": 1050,
    "result": "SUCCESS",
    "cardTransaction": {
        "last4": "4242",
        "token": "tok_secret",
        "entryType": "SWIPE",
        "pan": "411111111111",
    },
    "href": "https://api.clover.com/v3/merchants/M1/payments/P1",
}

DIRTY_ORDER = {
    "id": "O1",
    "state": "paid",
    "total": 1050,
    "href": "https://api.clover.com/v3/merchants/M1/orders/O1",
    "customers": {"elements": [{"id": "C1", "cards": {"elements": [{"token": "tok"}]}}]},
}

DIRTY_ITEM = {
    "id": "I1",
    "name": "Latte",
    "price": 500,
    "href": "https://api.clover.com/v3/merchants/M1/items/I1",
}


def test_customer_no_cards_or_pii() -> None:
    out = shape_customer(DIRTY_CUSTOMER)
    _assert_no_banned(out)
    assert "cards" not in out


def test_customer_cards_not_included_even_if_requested() -> None:
    out = shape_customer(DIRTY_CUSTOMER, include=["cards"])
    assert "cards" not in out


def test_employee_no_pin() -> None:
    out = shape_employee(DIRTY_EMPLOYEE)
    _assert_no_banned(out)
    assert "pin" not in out
    assert "unhashedPin" not in out


def test_payment_no_card_transaction() -> None:
    out = shape_payment(DIRTY_PAYMENT)
    _assert_no_banned(out)
    assert "cardTransaction" not in out


def test_order_customer_cards_stripped() -> None:
    out = shape_order(DIRTY_ORDER)
    _assert_no_banned(out)
    # customer_ids should be just IDs, not full objects with cards
    assert "customer_ids" in out
    assert out["customer_ids"] == ["C1"]


def test_item_no_href() -> None:
    out = shape_item(DIRTY_ITEM)
    _assert_no_banned(out)


def test_shift_strips_href() -> None:
    out = shape_shift(
        {
            "id": "SH1",
            "inTime": 1700000000000,
            "outTime": 0,
            "employee": {"id": "E1", "name": "Bob"},
            "href": "https://api.clover.com/v3/merchants/M1/employees/E1/shifts/SH1",
        }
    )
    _assert_no_banned(out)
    assert out["employee_id"] == "E1"


def test_v11_list_shapers_strip_href() -> None:
    dirty = {"id": "X1", "name": "thing", "href": "https://api.clover.com/x"}
    for shaper in (
        shape_category,
        shape_modifier_group,
        shape_device,
        shape_tax,
        shape_refund,
        shape_tender,
        shape_role,
        shape_item_group,
        shape_order_type,
        shape_opening_hours,
        shape_cash_event,
        shape_attribute,
        shape_tag,
    ):
        _assert_no_banned(shaper(dict(dirty)))


def test_order_surfaces_discounts_and_line_item_detail() -> None:
    """Order detail sub-resources (discounts, line-item modifications) project
    cleanly and the line item carries its catalog item_id — no href leak."""
    raw = {
        "id": "O9",
        "state": "paid",
        "total": 900,
        "discounts": {"elements": [{"name": "10% off", "amount": -100, "percentage": 10}]},
        "lineItems": {
            "elements": [
                {
                    "id": "LI1",
                    "name": "Latte",
                    "price": 500,
                    "item": {"id": "ITEM1", "href": "https://api.clover.com/x"},
                    "modifications": {"elements": [{"name": "Oat milk", "amount": 50}]},
                    "href": "https://api.clover.com/li",
                }
            ]
        },
    }
    out = shape_order(raw)
    _assert_no_banned(out)
    assert out["discounts"][0]["name"] == "10% off"
    li = out["line_items"][0]
    assert li["item_id"] == "ITEM1"
    assert li["modifications"][0]["name"] == "Oat milk"


def test_cash_event_strips_refs_keeps_amount() -> None:
    out = shape_cash_event(
        {
            "id": "CE1",
            "type": "PAID_IN",
            "amount": 2000,
            "note": "float",
            "timestamp": 1700000000000,
            "employee": {"id": "E1", "href": "https://api.clover.com/x"},
            "device": {"id": "D1"},
            "href": "https://api.clover.com/ce",
        }
    )
    _assert_no_banned(out)
    assert out["amount"] == 2000
    assert out["employee_id"] == "E1"
    assert out["device_id"] == "D1"


def test_merchant_properties_drops_banking_fields() -> None:
    """Merchant /properties carries banking/account numbers — they must never
    surface through the allowlist."""
    raw = {
        "defaultCurrency": "USD",
        "timezone": "America/Chicago",
        "tipsEnabled": True,
        "supportPhone": "+1 555 0100",
        # sensitive — must be dropped
        "abaAccountNumber": "000000000000000",
        "ddaAccountNumber": "***********3770",
        "href": "https://api.clover.com/v3/merchants/M1/properties",
        "merchantRef": {"id": "M1"},
    }
    out = shape_merchant_properties(raw)
    _assert_no_banned(out)
    assert out["defaultCurrency"] == "USD"
    assert out["tipsEnabled"] is True
    assert "abaAccountNumber" not in out
    assert "ddaAccountNumber" not in out
    assert "merchantRef" not in out


def test_merchant_shaped_cleanly() -> None:
    raw = {
        "id": "M1",
        "name": "Test Café",
        "defaultCurrency": "USD",
        "timezone": "America/New_York",
        "href": "https://api.clover.com/v3/merchants/M1",
        "internalSecret": "shhh",
        "owner": {
            "id": "OWNER1",
            "href": "https://api.clover.com/v3/merchants/M1/employees/OWNER1",
            "orders": {"href": "https://api.clover.com/v3/merchants/M1/orders"},
        },
        "address": {
            "address1": "123 Main St",
            "city": "Boston",
            "state": "MA",
            "zip": "02101",
            "country": "US",
            "href": "https://api.clover.com/v3/merchants/M1/address",
        },
    }
    out = shape_merchant(raw)
    _assert_no_banned(out)
    assert "internalSecret" not in out
    assert out["owner"] == {"id": "OWNER1"}
    assert "href" not in out["address"]
    assert out["address"]["city"] == "Boston"
