"""Tests for Layer 1 guarded writes + Layer 4 elicitation confirmation.

Pins the confirmation gate (`confirm_write`) and that each write tool: previews
on dry_run without touching the network, refuses when not confirmed, and POSTs
once approved.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

from clover_mcp.client import CloverClient
from clover_mcp.confirm import confirm_write
from clover_mcp.tools.customers import update_customer
from clover_mcp.tools.inventory import create_category, create_item
from clover_mcp.tools.orders import add_line_item, create_order
from tests.conftest import TEST_MERCHANT_ID

BASE = f"/v3/merchants/{TEST_MERCHANT_ID}"


class AcceptCtx:
    async def elicit(self, message, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.last_message = message
        return AcceptedElicitation(data="ok")


class DeclineCtx:
    async def elicit(self, message, *args, **kwargs):  # type: ignore[no-untyped-def]
        return DeclinedElicitation()


class NoElicitCtx:
    async def elicit(self, message, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("client does not support elicitation")


# ── confirm_write gate ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_explicit_override() -> None:
    assert await confirm_write(None, "x", confirm=True) == (True, "explicit_confirm")


@pytest.mark.asyncio
async def test_confirm_no_context_fails_closed() -> None:
    assert await confirm_write(None, "x", confirm=False) == (False, "no_context")


@pytest.mark.asyncio
async def test_confirm_elicit_accept_and_decline() -> None:
    assert await confirm_write(AcceptCtx(), "x", confirm=False) == (True, "elicited_accept")  # type: ignore[arg-type]
    assert await confirm_write(DeclineCtx(), "x", confirm=False) == (False, "elicited_declined")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_confirm_elicit_unsupported_fails_closed() -> None:
    assert await confirm_write(NoElicitCtx(), "x", confirm=False) == (  # type: ignore[arg-type]
        False,
        "elicitation_unsupported",
    )


# ── create_category ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_category_dry_run_no_network(client: CloverClient) -> None:
    out = await create_category(client, AcceptCtx(), "Drinks", dry_run=True)  # type: ignore[arg-type]
    assert out["dry_run"] is True
    assert out["would_post_body"] == {"name": "Drinks"}


@pytest.mark.asyncio
async def test_create_category_refused_without_confirmation(client: CloverClient) -> None:
    out = await create_category(client, NoElicitCtx(), "Drinks")  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_category_writes_when_confirmed(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.post(f"{BASE}/categories").mock(
        return_value=httpx.Response(200, json={"id": "C9", "name": "Drinks", "sortOrder": 1})
    )
    out = await create_category(client, AcceptCtx(), "Drinks")  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out["category"]["id"] == "C9"


@pytest.mark.asyncio
async def test_create_category_empty_name_rejected(client: CloverClient) -> None:
    with pytest.raises(ValueError, match="name"):
        await create_category(client, AcceptCtx(), "   ")  # type: ignore[arg-type]


# ── create_item ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_item_bounds_violation(client: CloverClient) -> None:
    out = await create_item(client, AcceptCtx(), "Latte", -5)  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "bounds_violation"


@pytest.mark.asyncio
async def test_create_item_writes_when_confirmed(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.post(f"{BASE}/items").mock(
        return_value=httpx.Response(200, json={"id": "I9", "name": "Latte", "price": 500})
    )
    out = await create_item(client, AcceptCtx(), "Latte", 500)  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out["item"]["price"] == 500


@pytest.mark.asyncio
async def test_create_item_declined(client: CloverClient) -> None:
    out = await create_item(client, DeclineCtx(), "Latte", 500)  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["how"] == "elicited_declined"


# ── orders ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_order_writes_when_confirmed(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.post(f"{BASE}/orders").mock(
        return_value=httpx.Response(200, json={"id": "O9", "state": "open", "total": 0})
    )
    out = await create_order(client, AcceptCtx())  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out["order"]["id"] == "O9"


@pytest.mark.asyncio
async def test_add_line_item_writes_when_confirmed(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.post(f"{BASE}/orders/O9/line_items").mock(
        return_value=httpx.Response(200, json={"id": "LI9", "name": "Latte", "price": 500})
    )
    out = await add_line_item(client, AcceptCtx(), "O9", "I9")  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out["line_item"]["name"] == "Latte"


@pytest.mark.asyncio
async def test_add_line_item_empty_ids_rejected(client: CloverClient) -> None:
    with pytest.raises(ValueError):
        await add_line_item(client, AcceptCtx(), "", "I9")  # type: ignore[arg-type]


# ── update_customer ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_customer_nothing_to_update(client: CloverClient) -> None:
    with pytest.raises(ValueError, match="nothing to update"):
        await update_customer(client, AcceptCtx(), "C1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_update_customer_dry_run(client: CloverClient) -> None:
    out = await update_customer(client, AcceptCtx(), "C1", first_name="Jane", dry_run=True)  # type: ignore[arg-type]
    assert out["dry_run"] is True
    assert out["would_post_body"] == {"firstName": "Jane"}


@pytest.mark.asyncio
async def test_update_customer_writes_when_confirmed(
    client: CloverClient, mock_http: respx.Router
) -> None:
    mock_http.post(f"{BASE}/customers/C1").mock(
        return_value=httpx.Response(200, json={"id": "C1", "firstName": "Jane", "lastName": "Doe"})
    )
    out = await update_customer(client, AcceptCtx(), "C1", first_name="Jane")  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out["customer"]["firstName"] == "Jane"
