"""Regression coverage for tenant token-store identity and customer expansions."""

from dataclasses import replace

from clover_mcp.auth import TokenStore
from clover_mcp.remote import tenant_config
from clover_mcp.shaping import shape_customer


def _oauth_entry(merchant_id: str, *, sandbox: bool = True) -> dict[str, object]:
    return {
        "merchant_id": merchant_id,
        "auth_mode": "oauth_refresh",
        "access_token": "access",
        "refresh_token": "refresh",
        "oauth_client_id": "client",
        "sandbox": sandbox,
    }


def test_tenant_store_identity_preserves_case_punctuation_and_binding(test_config, tmp_path):
    base = replace(test_config, merchant_store=tmp_path / "merchants.json")
    identities = [
        ("a+b@example.com", "M1", True),
        ("a-b@example.com", "M1", True),
        ("A+B@example.com", "M1", True),
        ("a+b@example.com", "M2", True),
        ("a+b@example.com", "M1", False),
    ]
    stores = [
        tenant_config(
            base,
            {identity: _oauth_entry(merchant, sandbox=sandbox)},
            identity,
        ).token_store
        for identity, merchant, sandbox in identities
    ]

    assert len({store.name for store in stores}) == len(stores)
    stores[0].parent.mkdir(parents=True, exist_ok=True)
    TokenStore(stores[0]).save({"access_token": "rotated-A"})
    assert TokenStore(stores[1]).load() == {}


def test_customer_expansions_are_nested_allowlist_projections():
    shaped = shape_customer(
        {
            "id": "C1",
            "addresses": {
                "elements": [
                    {
                        "id": "ADDR1",
                        "address1": "123 Main St",
                        "city": "Springfield",
                        "zip": "12345",
                        "href": "https://api.invalid/address/ADDR1",
                        "token": "address-secret",
                    },
                    None,
                    "malformed",
                ],
                "href": "https://api.invalid/customers/C1/addresses",
            },
            "orders": {
                "elements": [
                    {
                        "id": "O1",
                        "state": "paid",
                        "total": 1500,
                        "lineItems": {
                            "elements": [
                                {
                                    "id": "LI1",
                                    "name": "Coffee",
                                    "price": 1500,
                                    "item": {"id": "ITEM1", "href": "secret-ref"},
                                }
                            ]
                        },
                        "payments": {
                            "elements": [
                                {
                                    "id": "P1",
                                    "amount": 1500,
                                    "cardTransaction": {"token": "card-secret"},
                                }
                            ]
                        },
                        "orderType": {
                            "id": "TYPE1",
                            "label": "Dine in",
                            "href": "secret-ref",
                            "token": "order-type-secret",
                        },
                        "href": "https://api.invalid/orders/O1",
                    },
                    None,
                ],
            },
        },
        include=["addresses", "orders"],
    )

    assert shaped["addresses"] == {
        "elements": [
            {"id": "ADDR1", "address1": "123 Main St", "city": "Springfield", "zip": "12345"}
        ]
    }
    assert shaped["orders"]["elements"][0]["id"] == "O1"
    assert shaped["orders"]["elements"][0]["line_items"][0]["item_id"] == "ITEM1"
    assert shaped["orders"]["elements"][0]["orderType"] == {
        "id": "TYPE1",
        "label": "Dine in",
    }
    assert "cardTransaction" not in str(shaped)
    assert "secret" not in str(shaped)


def test_customer_expansions_handle_null_and_malformed_containers():
    assert shape_customer({"id": "C1", "addresses": None}, include=["addresses"])["addresses"] == []
    assert shape_customer({"id": "C1", "orders": {"elements": None}}, include=["orders"])[
        "orders"
    ] == {"elements": []}
