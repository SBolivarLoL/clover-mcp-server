"""Tests for the roadmap-completion guarded writes (2026-07-05 sandbox audit):
apply_order_discount, update_item_name, create_modifier_group, create_modifier,
create_tag.

Follows the conventions of tests/tools/test_writes.py: AcceptCtx/DeclineCtx/
NoElicitCtx fixtures for the elicitation gate, respx for HTTP mocking, and
per-tool happy-path + error-path + dry_run + bounds + pre-check coverage.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.inventory import (
    create_modifier,
    create_modifier_group,
    create_tag,
    update_item_name,
)
from clover_mcp.tools.orders import apply_order_discount
from tests.conftest import TEST_MERCHANT_ID
from tests.tools.test_writes import AcceptCtx, DeclineCtx, NoElicitCtx

BASE = f"/v3/merchants/{TEST_MERCHANT_ID}"


# ── apply_order_discount ───────────────────────────────────────────────────────

ORDER_RAW = {
    "id": "O1",
    "state": "open",
    "lineItems": {
        "elements": [
            {"id": "LI1", "name": "Latte", "price": 500},
            {"id": "LI2", "name": "Muffin", "price": 300},
        ]
    },
    "discounts": {"elements": []},
}

DISCOUNTS_CATALOGUE = {
    "elements": [
        {"id": "CATDISC1", "name": "Happy Hour", "percentage": 10},
        {"id": "CATDISC2", "name": "Fixed Off", "amount": 200},
        {"id": "CATDISC_BAD", "name": "Broken"},
    ]
}


@pytest.mark.asyncio
async def test_apply_order_discount_xor_violation(client: CloverClient) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        await apply_order_discount(client, AcceptCtx(), "O1", percentage=10, amount_cents=100)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_order_discount_none_given(client: CloverClient) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        await apply_order_discount(client, AcceptCtx(), "O1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_order_discount_percentage_bounds(client: CloverClient) -> None:
    result = await apply_order_discount(client, AcceptCtx(), "O1", percentage=0)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"

    result = await apply_order_discount(client, AcceptCtx(), "O1", percentage=101)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"


@pytest.mark.asyncio
async def test_apply_order_discount_amount_bounds(client: CloverClient) -> None:
    result = await apply_order_discount(client, AcceptCtx(), "O1", amount_cents=0)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"

    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        amount_cents=100_000_001,  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"


@pytest.mark.asyncio
async def test_apply_order_discount_dry_run_percentage_preview(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        name="Loyalty",
        percentage=15,
        dry_run=True,  # type: ignore[arg-type]
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_post_body"] == {"name": "Loyalty", "percentage": 15}
    assert result["preview"]["line_item_subtotal_cents"] == 800
    assert result["preview"]["current_discounts"] == []
    assert "not server-computed" in result["preview"]["note"]
    # Only the order GET fires — no POST
    assert not any(r.request.method == "POST" for r in mock_http.calls)


@pytest.mark.asyncio
async def test_apply_order_discount_amount_cents_negated_on_wire(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Verified sandbox semantics: Clover requires `amount` NEGATIVE. The tool
    accepts a positive amount_cents and must send the negated value."""
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    post_route = mock_http.post(f"{BASE}/orders/O1/discounts").mock(
        return_value=httpx.Response(200, json={"id": "D1", "name": "Sale", "amount": -150})
    )
    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        name="Sale",
        amount_cents=150,  # type: ignore[arg-type]
    )
    assert result["ok"] is True
    assert result["discount"]["amount"] == -150

    sent_body = post_route.calls.last.request.content
    import json as _json

    payload = _json.loads(sent_body)
    assert payload["amount"] == -150
    assert payload["name"] == "Sale"


@pytest.mark.asyncio
async def test_apply_order_discount_catalogue_path_sends_inline_fields(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Clover does not resolve discount:{id} server-side — name + percentage
    must be sent inline alongside the discount reference."""
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    mock_http.get(f"{BASE}/discounts").mock(
        return_value=httpx.Response(200, json=DISCOUNTS_CATALOGUE)
    )
    post_route = mock_http.post(f"{BASE}/orders/O1/discounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "D2",
                "name": "Happy Hour",
                "percentage": 10,
                "discType": "DEFAULT",
                "discount": {"id": "CATDISC1"},
            },
        )
    )
    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        catalogue_discount_id="CATDISC1",  # type: ignore[arg-type]
    )
    assert result["ok"] is True
    assert result["discount"]["disc_type"] == "DEFAULT"
    assert result["discount"]["discount_ref"] == "CATDISC1"

    import json as _json

    payload = _json.loads(post_route.calls.last.request.content)
    assert payload["discount"] == {"id": "CATDISC1"}
    assert payload["name"] == "Happy Hour"
    assert payload["percentage"] == 10


@pytest.mark.asyncio
async def test_apply_order_discount_catalogue_amount_path(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    mock_http.get(f"{BASE}/discounts").mock(
        return_value=httpx.Response(200, json=DISCOUNTS_CATALOGUE)
    )
    post_route = mock_http.post(f"{BASE}/orders/O1/discounts").mock(
        return_value=httpx.Response(200, json={"id": "D3", "name": "Fixed Off", "amount": 200})
    )
    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        catalogue_discount_id="CATDISC2",  # type: ignore[arg-type]
    )
    assert result["ok"] is True

    import json as _json

    payload = _json.loads(post_route.calls.last.request.content)
    assert payload["discount"] == {"id": "CATDISC2"}
    assert payload["name"] == "Fixed Off"
    assert payload["amount"] == 200


@pytest.mark.asyncio
async def test_apply_order_discount_catalogue_not_found(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    mock_http.get(f"{BASE}/discounts").mock(
        return_value=httpx.Response(200, json=DISCOUNTS_CATALOGUE)
    )
    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        catalogue_discount_id="NOPE",  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "not_found"


@pytest.mark.asyncio
async def test_apply_order_discount_catalogue_missing_amount_and_percentage(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    mock_http.get(f"{BASE}/discounts").mock(
        return_value=httpx.Response(200, json=DISCOUNTS_CATALOGUE)
    )
    result = await apply_order_discount(
        client,
        AcceptCtx(),
        "O1",
        catalogue_discount_id="CATDISC_BAD",  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "invalid_catalogue_discount"


@pytest.mark.asyncio
async def test_apply_order_discount_refused_without_confirmation(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    result = await apply_order_discount(client, NoElicitCtx(), "O1", percentage=10)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "confirmation_required"


@pytest.mark.asyncio
async def test_apply_order_discount_declined(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    result = await apply_order_discount(client, DeclineCtx(), "O1", percentage=10)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["how"] == "elicited_declined"


@pytest.mark.asyncio
async def test_apply_order_discount_empty_order_id(client: CloverClient) -> None:
    with pytest.raises(ValueError):
        await apply_order_discount(client, AcceptCtx(), "", percentage=10)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_order_discount_5xx_not_retried(
    client: CloverClient, mock_http: respx.Router
) -> None:
    """Writes never auto-retry on 5xx — assert exactly one POST attempt."""
    mock_http.get(f"{BASE}/orders/O1").mock(return_value=httpx.Response(200, json=ORDER_RAW))
    post_route = mock_http.post(f"{BASE}/orders/O1/discounts").mock(
        return_value=httpx.Response(500, json={"message": "Internal error"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await apply_order_discount(client, AcceptCtx(), "O1", percentage=10)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 500
    assert post_route.call_count == 1


# ── update_item_name ────────────────────────────────────────────────────────────

ITEM_RAW = {
    "id": "ITEM1",
    "name": "Latte",
    "price": 500,
    "priceType": "FIXED",
    "available": True,
    "hidden": False,
}
ITEM_RAW_RENAMED = {**ITEM_RAW, "name": "Iced Latte"}


@pytest.mark.asyncio
async def test_update_item_name_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{BASE}/items/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW))
    mock_http.post(f"{BASE}/items/ITEM1").mock(
        return_value=httpx.Response(200, json=ITEM_RAW_RENAMED)
    )
    result = await update_item_name(
        client,
        AcceptCtx(),
        "ITEM1",
        "Iced Latte",
        expected_current_name="Latte",  # type: ignore[arg-type]
    )
    assert result["ok"] is True
    assert result["item"]["name"] == "Iced Latte"
    assert result["item"]["price"] == 500  # price preserved (POST partial update)


@pytest.mark.asyncio
async def test_update_item_name_dry_run_no_post(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW))
    result = await update_item_name(
        client,
        AcceptCtx(),  # type: ignore[arg-type]
        "ITEM1",
        "Iced Latte",
        expected_current_name="Latte",
        dry_run=True,
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_post_body"] == {"name": "Iced Latte"}
    assert not any(r.request.method == "POST" for r in mock_http.calls)


@pytest.mark.asyncio
async def test_update_item_name_pre_check_mismatch(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW))
    result = await update_item_name(
        client,
        AcceptCtx(),
        "ITEM1",
        "Iced Latte",
        expected_current_name="Mocha",  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "optimistic_lock_mismatch"
    assert result["expected"] == "Mocha"
    assert result["actual"] == "Latte"


@pytest.mark.asyncio
async def test_update_item_name_bounds_empty(client: CloverClient, mock_http: respx.Router) -> None:
    result = await update_item_name(
        client,
        AcceptCtx(),
        "ITEM1",
        "   ",
        expected_current_name="Latte",  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"
    assert not mock_http.calls


@pytest.mark.asyncio
async def test_update_item_name_bounds_too_long(
    client: CloverClient, mock_http: respx.Router
) -> None:
    result = await update_item_name(
        client,
        AcceptCtx(),
        "ITEM1",
        "x" * 128,
        expected_current_name="Latte",  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"
    assert not mock_http.calls


@pytest.mark.asyncio
async def test_update_item_name_refused_without_confirmation(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW))
    result = await update_item_name(
        client,
        NoElicitCtx(),
        "ITEM1",
        "Iced Latte",
        expected_current_name="Latte",  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["reason"] == "confirmation_required"


@pytest.mark.asyncio
async def test_update_item_name_5xx_not_retried(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{BASE}/items/ITEM1").mock(return_value=httpx.Response(200, json=ITEM_RAW))
    post_route = mock_http.post(f"{BASE}/items/ITEM1").mock(
        return_value=httpx.Response(503, json={"message": "Service unavailable"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await update_item_name(
            client,
            AcceptCtx(),
            "ITEM1",
            "Iced Latte",
            expected_current_name="Latte",  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 503
    assert post_route.call_count == 1


@pytest.mark.asyncio
async def test_update_item_name_empty_item_id(client: CloverClient) -> None:
    with pytest.raises(ValueError):
        await update_item_name(client, AcceptCtx(), "", "Iced Latte", expected_current_name="Latte")  # type: ignore[arg-type]


# ── create_modifier_group ───────────────────────────────────────────────────────

MODIFIER_GROUPS_PATH = f"{BASE}/modifier_groups"


@pytest.mark.asyncio
async def test_create_modifier_group_dry_run_no_network(client: CloverClient) -> None:
    result = await create_modifier_group(client, AcceptCtx(), "Milk options", dry_run=True)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_post_body"] == {"name": "Milk options"}


@pytest.mark.asyncio
async def test_create_modifier_group_happy_path(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(MODIFIER_GROUPS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    mock_http.post(MODIFIER_GROUPS_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": "MG9", "name": "Milk options", "showByDefault": True, "deleted": False}
        )
    )
    result = await create_modifier_group(client, AcceptCtx(), "Milk options")  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["modifier_group"]["id"] == "MG9"
    assert result["modifier_group"]["name"] == "Milk options"


@pytest.mark.asyncio
async def test_create_modifier_group_duplicate_refused(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(MODIFIER_GROUPS_PATH).mock(
        return_value=httpx.Response(
            200, json={"elements": [{"id": "MG1", "name": "  Milk Options  "}]}
        )
    )
    result = await create_modifier_group(client, AcceptCtx(), "milk options")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "duplicate"
    assert result["existing_modifier_group"]["id"] == "MG1"


@pytest.mark.asyncio
async def test_create_modifier_group_empty_name_rejected(client: CloverClient) -> None:
    with pytest.raises(ValueError, match="name"):
        await create_modifier_group(client, AcceptCtx(), "   ")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_modifier_group_declined(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(MODIFIER_GROUPS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    result = await create_modifier_group(client, DeclineCtx(), "Milk options")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["how"] == "elicited_declined"


@pytest.mark.asyncio
async def test_create_modifier_group_5xx_not_retried(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(MODIFIER_GROUPS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    post_route = mock_http.post(MODIFIER_GROUPS_PATH).mock(
        return_value=httpx.Response(500, json={"message": "Internal error"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await create_modifier_group(client, AcceptCtx(), "Milk options")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 500
    assert post_route.call_count == 1


# ── create_modifier ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_modifier_bounds_violation(client: CloverClient) -> None:
    result = await create_modifier(client, AcceptCtx(), "MG1", "Oat milk", -5)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"

    result = await create_modifier(client, AcceptCtx(), "MG1", "Oat milk", 100_000_001)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "bounds_violation"


@pytest.mark.asyncio
async def test_create_modifier_group_not_found(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{MODIFIER_GROUPS_PATH}/MG1").mock(
        return_value=httpx.Response(404, json={"message": "invalid ID"})
    )
    result = await create_modifier(client, AcceptCtx(), "MG1", "Oat milk", 75)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "not_found"


@pytest.mark.asyncio
async def test_create_modifier_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{MODIFIER_GROUPS_PATH}/MG1").mock(
        return_value=httpx.Response(200, json={"id": "MG1", "name": "Milk options"})
    )
    mock_http.post(f"{MODIFIER_GROUPS_PATH}/MG1/modifiers").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "MOD1",
                "name": "Oat milk",
                "available": True,
                "price": 75,
                "modifierGroup": {"id": "MG1"},
                "deleted": False,
            },
        )
    )
    result = await create_modifier(client, AcceptCtx(), "MG1", "Oat milk", 75)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["modifier"]["id"] == "MOD1"
    assert result["modifier"]["price"] == 75
    assert result["modifier"]["modifier_group_id"] == "MG1"


@pytest.mark.asyncio
async def test_create_modifier_dry_run_no_post(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{MODIFIER_GROUPS_PATH}/MG1").mock(
        return_value=httpx.Response(200, json={"id": "MG1", "name": "Milk options"})
    )
    result = await create_modifier(client, AcceptCtx(), "MG1", "Oat milk", 75, dry_run=True)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_post_body"] == {"name": "Oat milk", "price": 75}
    assert not any(r.request.method == "POST" for r in mock_http.calls)


@pytest.mark.asyncio
async def test_create_modifier_declined(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(f"{MODIFIER_GROUPS_PATH}/MG1").mock(
        return_value=httpx.Response(200, json={"id": "MG1", "name": "Milk options"})
    )
    result = await create_modifier(client, DeclineCtx(), "MG1", "Oat milk", 75)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["how"] == "elicited_declined"


@pytest.mark.asyncio
async def test_create_modifier_5xx_not_retried(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.get(f"{MODIFIER_GROUPS_PATH}/MG1").mock(
        return_value=httpx.Response(200, json={"id": "MG1", "name": "Milk options"})
    )
    post_route = mock_http.post(f"{MODIFIER_GROUPS_PATH}/MG1/modifiers").mock(
        return_value=httpx.Response(500, json={"message": "Internal error"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await create_modifier(client, AcceptCtx(), "MG1", "Oat milk", 75)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 500
    assert post_route.call_count == 1


@pytest.mark.asyncio
async def test_create_modifier_empty_ids_rejected(client: CloverClient) -> None:
    with pytest.raises(ValueError):
        await create_modifier(client, AcceptCtx(), "", "Oat milk", 75)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await create_modifier(client, AcceptCtx(), "MG1", "   ", 75)  # type: ignore[arg-type]


# ── create_tag ───────────────────────────────────────────────────────────────────

TAGS_PATH = f"{BASE}/tags"


@pytest.mark.asyncio
async def test_create_tag_dry_run_no_network(client: CloverClient) -> None:
    result = await create_tag(client, AcceptCtx(), "Seasonal", dry_run=True)  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_post_body"] == {"name": "Seasonal"}


@pytest.mark.asyncio
async def test_create_tag_happy_path(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(TAGS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    mock_http.post(TAGS_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": "TAG9", "name": "Seasonal", "showInReporting": False}
        )
    )
    result = await create_tag(client, AcceptCtx(), "Seasonal")  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["tag"]["id"] == "TAG9"


@pytest.mark.asyncio
async def test_create_tag_duplicate_refused(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(TAGS_PATH).mock(
        return_value=httpx.Response(200, json={"elements": [{"id": "TAG1", "name": " seasonal "}]})
    )
    result = await create_tag(client, AcceptCtx(), "Seasonal")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "duplicate"
    assert result["existing_tag"]["id"] == "TAG1"


@pytest.mark.asyncio
async def test_create_tag_empty_name_rejected(client: CloverClient) -> None:
    with pytest.raises(ValueError, match="name"):
        await create_tag(client, AcceptCtx(), "  ")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_tag_declined(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(TAGS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    result = await create_tag(client, DeclineCtx(), "Seasonal")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["how"] == "elicited_declined"


@pytest.mark.asyncio
async def test_create_tag_5xx_not_retried(client: CloverClient, mock_http: respx.Router) -> None:
    mock_http.get(TAGS_PATH).mock(return_value=httpx.Response(200, json={"elements": []}))
    post_route = mock_http.post(TAGS_PATH).mock(
        return_value=httpx.Response(502, json={"message": "Bad gateway"})
    )
    with pytest.raises(CloverAPIError) as exc_info:
        await create_tag(client, AcceptCtx(), "Seasonal")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 502
    assert post_route.call_count == 1
