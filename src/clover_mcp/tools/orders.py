"""Tools: list_orders, get_order, list_open_orders.

Clover orders support a `state` filter (open, paid, etc.) and time-range
filtering via ms-epoch `createdTime`. All list tools use 90-day windowing.
get_order expands lineItems and payments but never customers.cards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from clover_mcp.client import CloverClient
from clover_mcp.confirm import confirm_write, confirmation_required
from clover_mcp.shaping import _shape_line_item, shape_order
from clover_mcp.windowing import date_to_ms, split_window

if TYPE_CHECKING:
    from fastmcp import Context

_DEFAULT_LIMIT = 50

# States documented in the Clover API
_VALID_STATES = frozenset({"open", "paid", "refunded", "partially_refunded"})


def _today_utc() -> date:
    return datetime.now(tz=UTC).date()


def _parse_date(value: str, param_name: str) -> date:
    """Parse an ISO-8601 date string (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{param_name} must be an ISO-8601 date (YYYY-MM-DD), got {value!r}"
        ) from exc


async def list_orders(
    client: CloverClient,
    date_from: str | None = None,
    date_to: str | None = None,
    state: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """List orders within an optional date window and/or state filter.

    Defaults to today (UTC) when no dates are supplied. Uses 90-day chunking
    so multi-month queries work transparently. Results are capped at `limit`
    total items (default 50, max 200).

    `state` must be one of: open, paid, refunded, partially_refunded.
    Leave empty to return all states.

    Allowlisted projection is applied — customer card data is never included.
    This tool is read-only and does NOT modify any order state.
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")

    if state is not None and state not in _VALID_STATES:
        raise ValueError(f"state must be one of {sorted(_VALID_STATES)}, got {state!r}")

    today = _today_utc()
    d_from = _parse_date(date_from, "date_from") if date_from else today
    d_to = _parse_date(date_to, "date_to") if date_to else today

    if d_from > d_to:
        raise ValueError(f"date_from ({d_from}) must be ≤ date_to ({d_to})")

    results: list[dict[str, Any]] = []

    for chunk_start, chunk_end in split_window(d_from, d_to):
        if len(results) >= limit:
            break
        ts_from = date_to_ms(chunk_start, end_of_day=False)
        ts_to = date_to_ms(chunk_end, end_of_day=True)

        filters = [
            f"createdTime>={ts_from}",
            f"createdTime<={ts_to}",
        ]
        if state is not None:
            filters.append(f"state={state}")

        params: dict[str, Any] = {"filter": filters}
        chunk_limit = min(100, limit - len(results))

        async for raw in client.iterate("/orders", limit=chunk_limit, **params):
            results.append(shape_order(raw))
            if len(results) >= limit:
                break

    return results


async def get_order(
    client: CloverClient,
    order_id: str,
) -> dict[str, Any]:
    """Fetch a single order by ID, including line items, payments, and discounts.

    Expands lineItems (with their modifications + discounts), payments, and
    order-level discounts. Customer card data is never expanded. Returns a 404
    error if the order_id does not exist.

    This tool is read-only and does NOT modify any order state.
    """
    if not order_id or not order_id.strip():
        raise ValueError("order_id must not be empty")

    raw = await client.get(
        f"/orders/{order_id}",
        expand="lineItems.modifications,lineItems.discounts,payments,discounts",
    )
    return shape_order(raw)


async def list_open_orders(
    client: CloverClient,
) -> list[dict[str, Any]]:
    """Return all currently open orders for this merchant.

    Convenience wrapper around list_orders(state='open') with no date filter.
    Returns up to 200 open orders; open order counts above 200 are unusual
    in a healthy POS environment.

    Allowlisted projection is applied — customer card data is never included.
    This tool is read-only and does NOT modify any order state.
    """
    # No date filter — scan all open orders regardless of age
    params: dict[str, Any] = {"filter": ["state=open"]}
    results: list[dict[str, Any]] = []

    async for raw in client.iterate("/orders", limit=100, **params):
        results.append(shape_order(raw))
        if len(results) >= 200:
            break

    return results


# ── Write tools ───────────────────────────────────────────────────────────────


async def create_order(
    client: CloverClient,
    ctx: Context | None,
    note: str | None = None,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new open order (no line items yet).

    Previews on dry_run, then asks for confirmation (MCP elicitation, or
    confirm=True) before POSTing. Add items with add_line_item. Requires ORDERS_W.
    Does NOT take payment — this server never captures payments.
    """
    body: dict[str, Any] = {}
    if note and note.strip():
        body["note"] = note.strip()

    if dry_run:
        return {"ok": True, "dry_run": True, "would_post_path": "/orders", "would_post_body": body}

    approved, how = await confirm_write(ctx, "Create a new open order?", confirm=confirm)
    if not approved:
        return confirmation_required(how)

    raw = await client.post("/orders", json=body)
    return {"ok": True, "order": shape_order(raw)}


async def add_line_item(
    client: CloverClient,
    ctx: Context | None,
    order_id: str,
    item_id: str,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Add a catalog item as a line item to an order.

    The line item's name/price are copied from the catalog item by Clover.
    Previews on dry_run, then asks for confirmation (MCP elicitation, or
    confirm=True) before POSTing. Requires ORDERS_W. Does NOT take payment.
    """
    if not order_id or not order_id.strip():
        raise ValueError("order_id must not be empty")
    if not item_id or not item_id.strip():
        raise ValueError("item_id must not be empty")

    path = f"/orders/{order_id}/line_items"
    body = {"item": {"id": item_id}}
    if dry_run:
        return {"ok": True, "dry_run": True, "would_post_path": path, "would_post_body": body}

    approved, how = await confirm_write(
        ctx, f"Add item {item_id} to order {order_id}?", confirm=confirm
    )
    if not approved:
        return confirmation_required(how)

    raw = await client.post(path, json=body)
    return {"ok": True, "line_item": _shape_line_item(raw)}
