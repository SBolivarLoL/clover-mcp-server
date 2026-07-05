"""Tools: list_items, get_item, list_low_stock_items — Inventory (INVENTORY_R).

Write tools: set_item_price_cents, set_item_stock_quantity, update_item_name,
create_modifier_group, create_modifier, create_tag — require INVENTORY_W.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clover_mcp.client import CloverClient
from clover_mcp.confirm import confirm_write, confirmation_required
from clover_mcp.errors import CloverAPIError
from clover_mcp.shaping import (
    project,
    shape_attribute,
    shape_category,
    shape_discount,
    shape_item,
    shape_item_group,
    shape_modifier,
    shape_modifier_group,
    shape_tag,
    shape_tax,
)

if TYPE_CHECKING:
    from fastmcp import Context


async def list_items(
    client: CloverClient,
    query: str | None = None,
    category_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Return a page of inventory items.

    Optionally filter by name (exact match, case-insensitive on Clover's side)
    via *query*, or by category via *category_id*.  Pagination is controlled by
    *limit* (max 100) and *offset*.

    `fields` narrows each item to the named keys (cannot widen past the
    allowlist).

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
        "items": project([shape_item(el) for el in elements], fields),
        "count": len(elements),
        "offset": offset,
        "limit": limit,
    }


# Maps a get_item(include=...) value to its Clover expand parameter. `categories`
# is deliberately its own include: the base call already expands `categories` for
# the flattened id list, so requesting it again fetches the full category records
# under a distinct raw key (see get_item below) to avoid clobbering that id list.
_ITEM_INCLUDE_EXPAND = {
    "modifier_groups": "modifierGroups",
    "tax_rates": "taxRates",
    "categories": "categories",
    "tags": "tags",
}


async def get_item(
    client: CloverClient,
    item_id: str,
    include: list[str] | None = None,
) -> dict[str, Any]:
    """Return a single inventory item by ID, including stock quantity.

    Always expands itemStock and categories (flattened to a `categories` id list).

    *include* opts in to additional association detail (verified sandbox-side
    2026-07-05 — all four accepted together, each a `{elements:[...]}` container):
      - "modifier_groups" — full modifier group records (adds `modifier_groups`)
      - "tax_rates"        — tax rates applied to the item (adds `tax_rates`)
      - "categories"       — full category records, not just ids (adds `category_details`)
      - "tags"             — tags/labels on the item (adds `tags`)

    Requires INVENTORY_R permission.
    """
    expand_parts = ["itemStock", "categories"]
    allowed_extras = set(_ITEM_INCLUDE_EXPAND)
    for field in include or []:
        if field in allowed_extras and _ITEM_INCLUDE_EXPAND[field] not in expand_parts:
            expand_parts.append(_ITEM_INCLUDE_EXPAND[field])

    raw = await client.get(f"/items/{item_id}", expand=",".join(expand_parts))

    # The full category records (not just ids) are surfaced under a separate raw
    # key so shape_item can keep the base `categories` id list intact.
    if include and "categories" in include and "categories" in raw:
        raw = {**raw, "categoryDetails": raw["categories"]}

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


async def list_discounts(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's discount catalogue (fixed-amount or percentage).
    Requires INVENTORY_R."""
    discounts: list[dict[str, Any]] = []
    async for el in client.iterate("/discounts", limit=100):
        discounts.append(shape_discount(el))
        if len(discounts) >= 1000:
            break
    return {"discounts": discounts, "count": len(discounts)}


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


async def list_attributes(client: CloverClient) -> dict[str, Any]:
    """Return item attributes (variant axes like Size/Color) with their options.

    Attributes + options define an item's variants. Requires INVENTORY_R.
    """
    attrs: list[dict[str, Any]] = []
    async for el in client.iterate("/attributes", limit=100, expand="options"):
        attrs.append(shape_attribute(el))
        if len(attrs) >= 1000:
            break
    return {"attributes": attrs, "count": len(attrs)}


async def list_tags(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's tags/labels (used to group items). Requires INVENTORY_R."""
    tags: list[dict[str, Any]] = []
    async for el in client.iterate("/tags", limit=100):
        tags.append(shape_tag(el))
        if len(tags) >= 1000:
            break
    return {"tags": tags, "count": len(tags)}


# ── Write tools ───────────────────────────────────────────────────────────────

_PRICE_MAX = 100_000_000  # $1 000 000.00 in cents
_STOCK_MAX = 1_000_000


async def create_category(
    client: CloverClient,
    ctx: Context | None,
    name: str,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new inventory category.

    Validates a non-empty name, previews on dry_run, then asks for confirmation
    (MCP elicitation, or confirm=True) before POSTing. Requires INVENTORY_W.
    """
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")

    body = {"name": name}
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_post_path": "/categories",
            "would_post_body": body,
        }

    approved, how = await confirm_write(ctx, f"Create category '{name}'?", confirm=confirm)
    if not approved:
        return confirmation_required(how)

    raw = await client.post("/categories", json=body)
    return {"ok": True, "category": shape_category(raw)}


async def create_item(
    client: CloverClient,
    ctx: Context | None,
    name: str,
    price_cents: int,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new inventory item.

    Bounds: 0 <= price_cents <= 100_000_000. Validates a non-empty name, previews
    on dry_run, then asks for confirmation (MCP elicitation, or confirm=True)
    before POSTing. Requires INVENTORY_W.
    """
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    if not (0 <= price_cents <= _PRICE_MAX):
        return {
            "ok": False,
            "reason": "bounds_violation",
            "message": f"price_cents {price_cents} is out of bounds (0 – {_PRICE_MAX}).",
        }

    body = {"name": name, "price": price_cents}
    if dry_run:
        return {"ok": True, "dry_run": True, "would_post_path": "/items", "would_post_body": body}

    approved, how = await confirm_write(
        ctx, f"Create item '{name}' priced at {price_cents} cents?", confirm=confirm
    )
    if not approved:
        return confirmation_required(how)

    raw = await client.post("/items", json=body)
    return {"ok": True, "item": shape_item(raw)}


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


_ITEM_NAME_MAX = 127


async def update_item_name(
    client: CloverClient,
    ctx: Context | None,
    item_id: str,
    new_name: str,
    expected_current_name: str,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Rename an inventory item.

    Uses POST /items/{itemId}, which — unlike PUT — is a true partial update:
    only `name` changes, price and all other fields are preserved (sandbox-
    verified 2026-07-05).

    Safety mechanics
    ----------------
    * **Optimistic-lock pre-check**: the current name is fetched before writing.
      If it does not equal *expected_current_name* the call is refused with a
      diff so the caller can reconcile stale context before retrying.
    * **Bounds**: *new_name* must be non-empty and at most 127 characters.
    * **dry_run=True**: returns the would-be POST body without sending it (still
      performs the pre-check GET).
    * POST is never auto-retried on error.

    Previews on dry_run, then asks for confirmation (MCP elicitation, or
    confirm=True) before writing. Requires INVENTORY_R + INVENTORY_W.
    """
    if not item_id or not item_id.strip():
        raise ValueError("item_id must not be empty")

    stripped_name = new_name.strip()
    if not stripped_name:
        return {
            "ok": False,
            "reason": "bounds_violation",
            "message": "new_name must not be empty.",
        }
    if len(stripped_name) > _ITEM_NAME_MAX:
        return {
            "ok": False,
            "reason": "bounds_violation",
            "message": f"new_name exceeds {_ITEM_NAME_MAX} characters.",
        }

    # Pre-check GET — optimistic lock on the current name
    current_item = await get_item(client, item_id)
    current_name: str = current_item.get("name", "")

    if current_name != expected_current_name:
        return {
            "ok": False,
            "reason": "optimistic_lock_mismatch",
            "message": (
                f"Name mismatch: expected {expected_current_name!r} but current "
                f"value is {current_name!r}. Refresh item data before retrying."
            ),
            "expected": expected_current_name,
            "actual": current_name,
        }

    path = f"/items/{item_id}"
    body = {"name": stripped_name}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_post_path": path,
            "would_post_body": body,
        }

    approved, how = await confirm_write(
        ctx, f"Rename item {item_id} from {current_name!r} to {stripped_name!r}?", confirm=confirm
    )
    if not approved:
        return confirmation_required(how)

    raw = await client.post(path, json=body)
    shaped = shape_item(raw) if raw else current_item
    return {"ok": True, "item": shaped}


async def create_modifier_group(
    client: CloverClient,
    ctx: Context | None,
    name: str,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new modifier group (e.g. "Milk options").

    Duplicate guard: refuses if a modifier group with the same name already
    exists (case-insensitive, trimmed comparison) — mirrors create_customer's
    dup-guard pattern. Previews on dry_run, then asks for confirmation (MCP
    elicitation, or confirm=True) before POSTing. Requires INVENTORY_W.
    """
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")

    body = {"name": name}
    path = "/modifier_groups"

    if dry_run:
        return {"ok": True, "dry_run": True, "would_post_path": path, "would_post_body": body}

    existing = await list_modifiers(client)
    normalized = name.casefold()
    match = next(
        (
            g
            for g in existing.get("modifier_groups", [])
            if g.get("name", "").strip().casefold() == normalized
        ),
        None,
    )
    if match is not None:
        return {
            "ok": False,
            "reason": "duplicate",
            "message": (
                f"A modifier group named {name!r} already exists. "
                "Choose a different name if this is not a duplicate."
            ),
            "existing_modifier_group": match,
        }

    approved, how = await confirm_write(ctx, f"Create modifier group '{name}'?", confirm=confirm)
    if not approved:
        return confirmation_required(how)

    raw = await client.post(path, json=body)
    return {"ok": True, "modifier_group": shape_modifier_group(raw)}


_MODIFIER_PRICE_MAX = 100_000_000  # $1 000 000.00 in cents


async def create_modifier(
    client: CloverClient,
    ctx: Context | None,
    modifier_group_id: str,
    name: str,
    price_cents: int,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new modifier within a modifier group.

    Pre-check: verifies the modifier group exists via GET before writing; a
    404 there is surfaced as a clear error instead of a raw Clover 404.
    Bounds: 0 <= price_cents <= 100_000_000. Previews on dry_run, then asks for
    confirmation (MCP elicitation, or confirm=True) before POSTing. Requires
    INVENTORY_W.
    """
    if not modifier_group_id or not modifier_group_id.strip():
        raise ValueError("modifier_group_id must not be empty")

    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")

    if not (0 <= price_cents <= _MODIFIER_PRICE_MAX):
        return {
            "ok": False,
            "reason": "bounds_violation",
            "message": f"price_cents {price_cents} is out of bounds (0 – {_MODIFIER_PRICE_MAX}).",
        }

    try:
        await client.get(f"/modifier_groups/{modifier_group_id}")
    except CloverAPIError as exc:
        if exc.status_code == 404:
            return {
                "ok": False,
                "reason": "not_found",
                "message": f"Modifier group {modifier_group_id!r} does not exist.",
            }
        raise

    path = f"/modifier_groups/{modifier_group_id}/modifiers"
    body = {"name": name, "price": price_cents}

    if dry_run:
        return {"ok": True, "dry_run": True, "would_post_path": path, "would_post_body": body}

    approved, how = await confirm_write(
        ctx,
        f"Create modifier '{name}' (price {price_cents} cents) in group {modifier_group_id}?",
        confirm=confirm,
    )
    if not approved:
        return confirmation_required(how)

    raw = await client.post(path, json=body)
    return {"ok": True, "modifier": shape_modifier(raw)}


async def create_tag(
    client: CloverClient,
    ctx: Context | None,
    name: str,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new tag/label used to group items.

    Duplicate guard: refuses if a tag with the same name already exists
    (case-insensitive, trimmed comparison) against list_tags. Previews on
    dry_run, then asks for confirmation (MCP elicitation, or confirm=True)
    before POSTing. Requires INVENTORY_W.
    """
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")

    body = {"name": name}
    path = "/tags"

    if dry_run:
        return {"ok": True, "dry_run": True, "would_post_path": path, "would_post_body": body}

    existing = await list_tags(client)
    normalized = name.casefold()
    match = next(
        (t for t in existing.get("tags", []) if t.get("name", "").strip().casefold() == normalized),
        None,
    )
    if match is not None:
        return {
            "ok": False,
            "reason": "duplicate",
            "message": (
                f"A tag named {name!r} already exists. "
                "Choose a different name if this is not a duplicate."
            ),
            "existing_tag": match,
        }

    approved, how = await confirm_write(ctx, f"Create tag '{name}'?", confirm=confirm)
    if not approved:
        return confirmation_required(how)

    raw = await client.post(path, json=body)
    return {"ok": True, "tag": shape_tag(raw)}
