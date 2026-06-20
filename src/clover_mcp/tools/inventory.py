"""Tools: list_items, get_item, list_low_stock_items — Inventory (INVENTORY_R)."""

from __future__ import annotations

from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.shaping import shape_item


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
