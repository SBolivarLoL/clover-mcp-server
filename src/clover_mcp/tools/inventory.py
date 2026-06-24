"""Tools: list_items, get_item, list_low_stock_items — Inventory (INVENTORY_R).

Write tools: set_item_price_cents, set_item_stock_quantity — require INVENTORY_W.
"""

from __future__ import annotations

from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.shaping import (
    shape_category,
    shape_item,
    shape_item_group,
    shape_modifier_group,
    shape_tax,
)


async def list_items(
    client: CloverClient,
    query: str | None = None,
    category_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a page of inventory items.

    Optionally filter by name (exact match, case-insensitive on Clover's side)
    via *query*, or by category via *category_id*.  Pagination is controlled by
    *limit* (max 100) and *offset*.

    Requires INVENTORY_R permission.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    filters: list[str] = []
    if query:
        # Clover filter syntax: field=value  (name supports wildcard * suffix)
        filters.append(f"name={query}")
    if category_id:
        # Items can be filtered by category using filter=categoryId=<id>
        # Note: categories.id is NOT supported; use categoryId
        filters.append(f"categoryId={category_id}")
    if filters:
        params["filter"] = ",".join(filters)

    body = await client.get("/items", **params)
    elements: list[dict[str, Any]] = body.get("elements", [])
    return {
        "items": [shape_item(el) for el in elements],
        "count": len(elements),
        "offset": offset,
        "limit": limit,
    }


async def get_item(client: CloverClient, item_id: str) -> dict[str, Any]:
    """Return a single inventory item by ID, including stock quantity.

    Expands itemStock so the returned record includes *stock_quantity*.

    Requires INVENTORY_R permission.
    """
    raw = await client.get(f"/items/{item_id}", expand="itemStock,categories")
    return shape_item(raw)


async def list_low_stock_items(
    client: CloverClient,
    threshold: int = 5,
) -> dict[str, Any]:
    """Return all inventory items whose stock quantity is at or below *threshold*.

    Iterates all items with itemStock expanded and filters client-side (Clover
    does not support a server-side stock-quantity filter).  Items with no stock
    tracking (stock_quantity is None) are excluded from results.

    Requires INVENTORY_R permission.
    """
    low: list[dict[str, Any]] = []
    async for el in client.iterate("/items", limit=200, expand="itemStock"):
        shaped = shape_item(el)
        qty = shaped.get("stock_quantity")
        if qty is not None and qty <= threshold:
            low.append(shaped)
    return {
        "threshold": threshold,
        "items": low,
        "count": len(low),
    }


async def list_categories(client: CloverClient) -> dict[str, Any]:
    """Return all inventory categories (up to 1000). Requires INVENTORY_R."""
    cats: list[dict[str, Any]] = []
    async for el in client.iterate("/categories", limit=100):
        cats.append(shape_category(el))
        if len(cats) >= 1000:
            break
    return {"categories": cats, "count": len(cats)}


async def list_item_groups(client: CloverClient) -> dict[str, Any]:
    """Return item groups (sets of item variants, e.g. size/color). Requires INVENTORY_R."""
    groups: list[dict[str, Any]] = []
    async for el in client.iterate("/item_groups", limit=100):
        groups.append(shape_item_group(el))
        if len(groups) >= 1000:
            break
    return {"item_groups": groups, "count": len(groups)}


async def list_modifiers(client: CloverClient) -> dict[str, Any]:
    """Return all modifier groups with their modifiers (up to 1000 groups).

    Requires INVENTORY_R.
    """
    groups: list[dict[str, Any]] = []
    async for el in client.iterate("/modifier_groups", limit=100, expand="modifiers"):
        groups.append(shape_modifier_group(el))
        if len(groups) >= 1000:
            break
    return {"modifier_groups": groups, "count": len(groups)}


async def list_taxes(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's tax rates. Requires INVENTORY_R."""
    taxes: list[dict[str, Any]] = []
    async for el in client.iterate("/tax_rates", limit=100):
        taxes.append(shape_tax(el))
    return {"tax_rates": taxes, "count": len(taxes)}


# ── Write tools ───────────────────────────────────────────────────────────────

_PRICE_MAX = 100_000_000  # $1 000 000.00 in cents
_STOCK_MAX = 1_000_000


async def set_item_price_cents(
    client: CloverClient,
    item_id: str,
    new_price_cents: int,
    expected_current_price_cents: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Update an item's price (in cents).

    Safety mechanics
    ----------------
    * **Optimistic-lock pre-check**: the current price is fetched before writing.
      If it does not equal *expected_current_price_cents* the call is refused with
      a diff so the caller can reconcile stale context before retrying.
    * **Bounds**: *new_price_cents* must satisfy ``0 <= new_price_cents <= 100_000_000``
      (i.e. $0.00 to $1 000 000.00). Requests outside this range are refused before
      any network call.
    * **dry_run=True**: returns the would-be PUT body without sending it.  No
      network call is made beyond the pre-check GET.
    * PUT is never auto-retried on error.

    Note: The Clover PUT /items/{id} endpoint requires the item ``name`` field in
    the request body.  This function fetches it from the pre-check GET automatically.

    Requires INVENTORY_R + INVENTORY_W permissions.
    """
    # Bounds check — refuse before any network call
    if not (0 <= new_price_cents <= _PRICE_MAX):
        return {
            "ok": False,
            "reason": "bounds_violation",
            "message": (
                f"new_price_cents {new_price_cents} is out of bounds (must be 0 – {_PRICE_MAX})."
            ),
        }

    # Pre-check GET — also retrieves name required by the PUT body
    current_item = await get_item(client, item_id)
    current_price: int = current_item.get("price", -1)

    if current_price != expected_current_price_cents:
        return {
            "ok": False,
            "reason": "optimistic_lock_mismatch",
            "message": (
                f"Price mismatch: expected {expected_current_price_cents} cents "
                f"but current value is {current_price} cents. "
                "Refresh item data before retrying."
            ),
            "expected": expected_current_price_cents,
            "actual": current_price,
        }

    # Build PUT body — Clover requires name alongside price
    item_name: str = current_item.get("name", "")
    put_body: dict[str, Any] = {"name": item_name, "price": new_price_cents}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_put_path": f"/items/{item_id}",
            "would_put_body": put_body,
        }

    raw = await client.put(f"/items/{item_id}", json=put_body)
    # Clover may return the full updated item or an empty body on success
    shaped = shape_item(raw) if raw else current_item
    return {"ok": True, "item": shaped}


async def set_item_stock_quantity(
    client: CloverClient,
    item_id: str,
    new_quantity: int,
    expected_current_quantity: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Set an item's stock quantity to an absolute value.

    **This sets stock to the absolute value provided — it is NOT a delta.**
    For example, passing ``new_quantity=10`` always results in a stock of 10,
    regardless of the previous value.

    Safety mechanics
    ----------------
    * **Optimistic-lock pre-check**: the current stock quantity is fetched from
      ``GET /item_stocks/{itemId}`` before writing.  If it does not equal
      *expected_current_quantity* the call is refused with a diff so the caller
      can reconcile stale context before retrying.
    * **Bounds**: *new_quantity* must satisfy ``0 <= new_quantity <= 1_000_000``.
      Requests outside this range are refused before any network call.
    * **dry_run=True**: returns the would-be PUT body without sending it.  Only
      the pre-check GET is made.
    * PUT is never auto-retried on error.

    Requires INVENTORY_R + INVENTORY_W permissions.
    """
    # Bounds check — refuse before any network call
    if not (0 <= new_quantity <= _STOCK_MAX):
        return {
            "ok": False,
            "reason": "bounds_violation",
            "message": (
                f"new_quantity {new_quantity} is out of bounds (must be 0 – {_STOCK_MAX})."
            ),
        }

    # Pre-check GET from item_stocks endpoint
    stock_raw = await client.get(f"/item_stocks/{item_id}")
    # Clover returns quantity as a float (e.g. 20.0); normalise to int for comparison
    current_quantity: int = int(stock_raw.get("quantity", -1))

    if current_quantity != expected_current_quantity:
        return {
            "ok": False,
            "reason": "optimistic_lock_mismatch",
            "message": (
                f"Stock mismatch: expected {expected_current_quantity} units "
                f"but current value is {current_quantity}. "
                "Refresh item data before retrying."
            ),
            "expected": expected_current_quantity,
            "actual": current_quantity,
        }

    put_body: dict[str, Any] = {"quantity": new_quantity}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_put_path": f"/item_stocks/{item_id}",
            "would_put_body": put_body,
        }

    raw = await client.put(f"/item_stocks/{item_id}", json=put_body)
    # Shape via the item endpoint so we return a consistent item representation
    # The item_stocks response does not include full item fields, so we re-fetch
    updated_item = await get_item(client, item_id)
    # Overlay the new stock quantity in case expand=itemStock isn't immediately
    # reflected (sandbox may lag); raw contains the authoritative new quantity
    new_qty_from_response = int(raw.get("quantity", new_quantity))
    updated_item["stock_quantity"] = new_qty_from_response
    return {"ok": True, "item": updated_item}
