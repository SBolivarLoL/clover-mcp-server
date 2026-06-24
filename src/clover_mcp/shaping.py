"""Allowlist-based response projection for Clover API payloads.

Every tool passes raw Clover JSON through a shaper before returning it to the
LLM. Only explicitly-named fields are kept; anything else is silently dropped.
This prevents PII leakage (customer cards, employee PINs) and keeps context
windows lean.
"""

from __future__ import annotations

from typing import Any


def _pick(src: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return a new dict with only the specified keys (missing keys are skipped)."""
    return {k: src[k] for k in keys if k in src}


def shape_merchant(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(
        raw,
        "id",
        "name",
        "currency",
        "defaultCurrency",
        "timezone",
        "country",
        "phoneNumber",
        "website",
        "businessType",
        "merchantPlan",
    )
    # Nested owner/address carry href fields (full API URLs with ids) — flatten to
    # real fields only so they can't leak. See test_shaping_allowlist BANNED_KEYS.
    if isinstance(raw.get("owner"), dict):
        out["owner"] = _pick(raw["owner"], "id")
    if isinstance(raw.get("address"), dict):
        out["address"] = _pick(
            raw["address"], "address1", "address2", "address3", "city", "state", "zip", "country"
        )
    return out


def shape_item(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(
        raw,
        "id",
        "name",
        "price",
        "priceType",
        "sku",
        "code",
        "cost",
        "available",
        "hidden",
        "isRevenue",
    )
    # Flatten nested categories to just ids
    if "categories" in raw:
        cats = raw["categories"]
        elements = cats.get("elements", cats) if isinstance(cats, dict) else cats
        out["categories"] = [c.get("id") for c in elements if isinstance(c, dict)]
    # Include stock quantity if expanded
    if "itemStock" in raw and isinstance(raw["itemStock"], dict):
        out["stock_quantity"] = raw["itemStock"].get("quantity")
    return out


def shape_order(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(
        raw,
        "id",
        "state",
        "total",
        "taxAmount",
        "currency",
        "createdTime",
        "modifiedTime",
        "clientCreatedTime",
        "note",
        "orderType",
    )
    if "employee" in raw and isinstance(raw["employee"], dict):
        out["employee_id"] = raw["employee"].get("id")
    # Customer IDs only — never full customer records with card data
    if "customers" in raw:
        custs = raw["customers"]
        elements = custs.get("elements", custs) if isinstance(custs, dict) else custs
        out["customer_ids"] = [c.get("id") for c in elements if isinstance(c, dict)]
    # Line items — lean projection
    if "lineItems" in raw:
        items = raw["lineItems"]
        elements = items.get("elements", items) if isinstance(items, dict) else items
        out["line_items"] = [_shape_line_item(li) for li in elements if isinstance(li, dict)]
    # Service charges total
    if "serviceCharge" in raw and isinstance(raw["serviceCharge"], dict):
        out["service_charge"] = raw["serviceCharge"].get("amount")
    return out


def _shape_line_item(raw: dict[str, Any]) -> dict[str, Any]:
    return _pick(raw, "id", "name", "price", "unitQty", "unitName", "note", "refunded")


def shape_payment(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(
        raw,
        "id",
        "amount",
        "tipAmount",
        "taxAmount",
        "cashbackAmount",
        "result",
        "createdTime",
        "modifiedTime",
        "offline",
        "note",
    )
    if "tender" in raw and isinstance(raw["tender"], dict):
        out["tender"] = raw["tender"].get("label") or raw["tender"].get("id")
    if "employee" in raw and isinstance(raw["employee"], dict):
        out["employee_id"] = raw["employee"].get("id")
    if "order" in raw and isinstance(raw["order"], dict):
        out["order_id"] = raw["order"].get("id")
    # cardTransaction deliberately excluded — contains full PAN / entry mode
    return out


def shape_refund(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a refund record. `amount` is positive cents (refunds are separate
    objects, not negative payments). transactionInfo is dropped — it can carry
    card/entry-mode detail."""
    out = _pick(raw, "id", "amount", "taxAmount", "createdTime")
    if isinstance(raw.get("orderRef"), dict):
        out["order_id"] = raw["orderRef"].get("id")
    if isinstance(raw.get("payment"), dict):
        out["payment_id"] = raw["payment"].get("id")
    if isinstance(raw.get("employee"), dict):
        out["employee_id"] = raw["employee"].get("id")
    return out


def shape_tender(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a tender type (payment method: cash, credit, custom, …)."""
    return _pick(
        raw,
        "id",
        "label",
        "labelKey",
        "enabled",
        "opensCashDrawer",
        "editable",
        "visible",
        "supportsCashDiscount",
    )


def shape_customer(raw: dict[str, Any], include: list[str] | None = None) -> dict[str, Any]:
    """Project a customer record.

    include: list of optional field groups to add (e.g. ["addresses", "orders"]).
    "cards" is never included regardless of include — privacy/compliance.
    """
    out = _pick(raw, "id", "firstName", "lastName", "marketingAllowed", "customerSince")
    # Flatten email / phone arrays
    if "emailAddresses" in raw:
        elems = raw["emailAddresses"]
        elements = elems.get("elements", elems) if isinstance(elems, dict) else elems
        out["emails"] = [e.get("emailAddress") for e in elements if isinstance(e, dict)]
    if "phoneNumbers" in raw:
        elems = raw["phoneNumbers"]
        elements = elems.get("elements", elems) if isinstance(elems, dict) else elems
        out["phones"] = [e.get("phoneNumber") for e in elements if isinstance(e, dict)]
    # Optional inclusions — cards never allowed
    allowed_includes = {"addresses", "orders"}
    for field in include or []:
        if field in allowed_includes and field in raw:
            out[field] = raw[field]
    return out


def shape_employee(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an employee record — PIN fields are always excluded."""
    return _pick(raw, "id", "name", "nickname", "email", "role", "isOwner", "customId")
    # Deliberately excluded: pin, unhashedPin


def shape_shift(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(
        raw,
        "id",
        "inTime",
        "outTime",
        "overrideInTime",
        "overrideOutTime",
        "inTimestamp",
        "outTimestamp",
    )
    if "employee" in raw and isinstance(raw["employee"], dict):
        out["employee_id"] = raw["employee"].get("id")
        out["employee_name"] = raw["employee"].get("name")
    return out


def shape_category(raw: dict[str, Any]) -> dict[str, Any]:
    return _pick(raw, "id", "name", "sortOrder")


def shape_modifier_group(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(raw, "id", "name", "showByDefault", "minRequired", "maxAllowed")
    if "modifiers" in raw:
        mods = raw["modifiers"]
        elements = mods.get("elements", mods) if isinstance(mods, dict) else mods
        out["modifiers"] = [
            _pick(m, "id", "name", "price") for m in elements if isinstance(m, dict)
        ]
    return out


def shape_device(raw: dict[str, Any]) -> dict[str, Any]:
    return _pick(raw, "id", "name", "serial", "model", "productName", "deviceTypeName")


def shape_tax(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(raw, "id", "name", "rate", "isDefault", "taxType")
    # ponytail: Clover encodes rate as 10_000_000 == 100%; surface a human percent
    # alongside the raw value. Units inferred from the API docs, not yet sandbox-verified.
    rate = raw.get("rate")
    if isinstance(rate, int):
        out["rate_percent"] = round(rate / 100_000, 4)
    return out
