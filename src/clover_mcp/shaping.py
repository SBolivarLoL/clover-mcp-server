"""Allowlist-based response projection for Clover API payloads.

Every tool passes raw Clover JSON through a shaper before returning it to the
LLM. Only explicitly-named fields are kept; anything else is silently dropped.
This prevents PII leakage (customer cards, employee PINs) and keeps context
windows lean.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _pick(src: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return a new dict with only the specified keys (missing keys are skipped)."""
    return {k: src[k] for k in keys if k in src}


def project(rows: list[dict[str, Any]], fields: list[str] | None) -> list[dict[str, Any]]:
    """Narrow already-shaped rows to `fields` (order preserved). None/empty → rows
    unchanged. Operates on shaped output only, so it can only drop keys, never add
    or un-redact them — it is not a way around the allowlist."""
    if not fields:
        return rows
    wanted = set(fields)
    return [{k: v for k, v in row.items() if k in wanted} for row in rows]


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
    # Optional associations — present only when get_item(include=...) expanded them.
    # Each is a {elements:[...]} container (sandbox-verified 2026-07-05); element
    # shapes reuse the same shapers as the standalone list_* tools. `categories`
    # above is always the flattened id list; `category_details` (opt-in) is the
    # full shaped record so both stay available without a breaking-change collision.
    if "modifierGroups" in raw:
        out["modifier_groups"] = [
            shape_modifier_group(g) for g in _elements_of(raw["modifierGroups"])
        ]
    if "taxRates" in raw:
        out["tax_rates"] = [shape_tax(t) for t in _elements_of(raw["taxRates"])]
    if "tags" in raw:
        out["tags"] = [shape_tag(t) for t in _elements_of(raw["tags"])]
    if "categoryDetails" in raw:
        out["category_details"] = [shape_category(c) for c in _elements_of(raw["categoryDetails"])]
    return out


def _elements_of(container: Any) -> list[dict[str, Any]]:
    """Unwrap a Clover {elements:[...]} container (or pass through a bare list)."""
    elements = container.get("elements", container) if isinstance(container, dict) else container
    return [e for e in elements if isinstance(e, dict)] if isinstance(elements, list) else []


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
    )
    if "orderType" in raw:
        order_type = raw["orderType"]
        if isinstance(order_type, dict):
            out["orderType"] = shape_order_type(order_type)
        elif isinstance(order_type, (str, int, float, bool)) or order_type is None:
            out["orderType"] = order_type
    if "employee" in raw and isinstance(raw["employee"], dict):
        out["employee_id"] = raw["employee"].get("id")
    # Customer IDs only — never full customer records with card data
    if "customers" in raw:
        out["customer_ids"] = [c.get("id") for c in _elements_of(raw["customers"])]
    # Line items — lean projection
    if "lineItems" in raw:
        out["line_items"] = [_shape_line_item(li) for li in _elements_of(raw["lineItems"])]
    # Payments — get_order expands these; shape via shape_payment (strips cardTransaction)
    if "payments" in raw:
        out["payments"] = [shape_payment(p) for p in _elements_of(raw["payments"])]
    # Order-level discounts — present only when expanded / applied.
    if "discounts" in raw:
        out["discounts"] = [
            _pick(d, "name", "amount", "percentage") for d in _elements_of(raw["discounts"])
        ]
    # Service charges total
    if "serviceCharge" in raw and isinstance(raw["serviceCharge"], dict):
        out["service_charge"] = raw["serviceCharge"].get("amount")
    return out


def _shape_line_item(raw: dict[str, Any]) -> dict[str, Any]:
    out = _pick(
        raw,
        "id",
        "name",
        "price",
        "unitQty",
        "unitName",
        "note",
        "refunded",
        "exchanged",
        "isRevenue",
    )
    # Reference to the catalog item (sandbox-verified field: lineItem.item.id)
    if isinstance(raw.get("item"), dict):
        out["item_id"] = raw["item"].get("id")
    # Order detail sub-resources — present only when expanded / applied.
    if "modifications" in raw:
        out["modifications"] = [
            _pick(m, "name", "amount") for m in _elements_of(raw["modifications"])
        ]
    if "discounts" in raw:
        out["discounts"] = [
            _pick(d, "name", "amount", "percentage") for d in _elements_of(raw["discounts"])
        ]
    return out


def shape_order_type(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an order type (Dine In, Take Out, …)."""
    return _pick(raw, "id", "label", "taxable", "isDefault", "isHidden", "filterCategories")


def shape_opening_hours(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an opening-hours set. Day arrays (sunday…saturday) carry
    {elements:[{start,end}]} time ranges; passed through as-is (not sensitive)."""
    out = _pick(raw, "id", "name")
    for day in (
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    ):
        if day in raw:
            val = raw[day]
            elements = val.get("elements", val) if isinstance(val, dict) else val
            out[day] = [_pick(e, "start", "end") for e in elements if isinstance(e, dict)]
    return out


def shape_cash_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a cash-drawer event (paid in/out, no-sale, deposit)."""
    out = _pick(raw, "id", "type", "amount", "note", "timestamp", "cashEventType")
    if isinstance(raw.get("employee"), dict):
        out["employee_id"] = raw["employee"].get("id")
    if isinstance(raw.get("device"), dict):
        out["device_id"] = raw["device"].get("id")
    return out


def shape_attribute(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an item attribute (variant axis, e.g. Size) with its options."""
    out = _pick(raw, "id", "name")
    if "options" in raw:
        opts = raw["options"]
        elements = opts.get("elements", opts) if isinstance(opts, dict) else opts
        out["options"] = [_pick(o, "id", "name") for o in elements if isinstance(o, dict)]
    return out


def shape_tag(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a tag/label (used to group items, e.g. on reporting/printers)."""
    return _pick(raw, "id", "name", "showInReporting")


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


def shape_credit(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a credit record (store-credit / account-credit adjustment).

    Element shape is UNVERIFIED — the sandbox `/credits` endpoint returns 200
    with an empty `{elements:[]}` container (same situation as list_item_groups
    and list_discounts before their fields were confirmed). Projects only the
    fields documented for the resource; refs are reduced to ids like every other
    shaper. Revisit this allowlist once a live credit exists to audit."""
    out = _pick(raw, "id", "amount", "createdTime")
    if isinstance(raw.get("tender"), dict):
        out["tender"] = raw["tender"].get("label") or raw["tender"].get("id")
    if isinstance(raw.get("customer"), dict):
        out["customer_id"] = raw["customer"].get("id")
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
            if field == "addresses":
                out[field] = _shape_customer_collection(raw[field], shape_address)
            else:
                out[field] = _shape_customer_collection(raw[field], shape_order)
    return out


def shape_address(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a customer address without forwarding Clover metadata or refs."""
    return _pick(
        raw,
        "id",
        "address1",
        "address2",
        "address3",
        "city",
        "state",
        "zip",
        "country",
        "label",
    )


def _shape_customer_collection(
    value: Any, shaper: Callable[[dict[str, Any]], dict[str, Any]]
) -> list[dict[str, Any]] | dict[str, Any]:
    """Shape an expanded customer collection while retaining its public wrapper shape."""
    if isinstance(value, list):
        elements = value
        shaped = [shaper(item) for item in elements if isinstance(item, dict)]
        return shaped
    if isinstance(value, dict):
        shaped = [shaper(item) for item in _elements_of(value)]
        return {"elements": shaped}
    return []


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


def shape_modifier(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a single modifier (POST /modifier_groups/{id}/modifiers response)."""
    out = _pick(raw, "id", "name", "price", "available")
    if isinstance(raw.get("modifierGroup"), dict):
        out["modifier_group_id"] = raw["modifierGroup"].get("id")
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


def shape_discount(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a merchant-level discount (catalogue entry). `amount` is cents
    (a fixed discount), `percentage` is a whole-number percent — only one is set."""
    return _pick(raw, "id", "name", "amount", "percentage")


def shape_order_discount(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an order-level discount (POST /orders/{orderId}/discounts response).

    `amount` is cents (negative — Clover requires the write to be negative; see
    apply_order_discount). `percentage` is a whole-number percent — only one is
    set. `disc_type` is `"DEFAULT"` when the discount was applied via a catalogue
    reference (`discount:{id}`), absent for ad-hoc discounts."""
    out = _pick(raw, "id", "name", "percentage", "amount")
    if "discType" in raw:
        out["disc_type"] = raw["discType"]
    if isinstance(raw.get("discount"), dict):
        out["discount_ref"] = raw["discount"].get("id")
    return out


def shape_tip_suggestion(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a tip-suggestion preset. `percentage` is a whole-number percent;
    `amount` (cents) is set instead for flat-amount presets."""
    return _pick(raw, "id", "name", "percentage", "amount", "isEnabled", "isDefault")


def shape_service_charge(raw: dict[str, Any]) -> dict[str, Any]:
    """Project the default service charge. `percentage` is the human percent;
    `percentageDecimal` is Clover's raw encoding (percent * 10_000)."""
    return _pick(raw, "id", "name", "enabled", "percentage", "percentageDecimal")


def shape_role(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an employee role. `systemRole` is the built-in category
    (EMPLOYEE / MANAGER / ADMIN); `name` is the merchant-facing label."""
    return _pick(raw, "id", "name", "systemRole")


# Merchant /properties carries POS configuration AND banking fields
# (abaAccountNumber, ddaAccountNumber). This is a strict allowlist of safe,
# useful config — the banking/account numbers and internal billing flags are
# never picked, so they cannot leak.
_PROPERTY_FIELDS = (
    "defaultCurrency",
    "timezone",
    "locale",
    "vat",
    "vatTaxName",
    "tipsEnabled",
    "tipRateDefault",
    "signatureThreshold",
    "cashBackEnabled",
    "trackStock",
    "updateStock",
    "orderTitle",
    "notesOnOrders",
    "groupLineItems",
    "deleteOrders",
    "removeTaxEnabled",
    "autoLogout",
    "pinLength",
    "marketingEnabled",
    "supportPhone",
    "supportEmail",
    "autoCloseoutTimezone",
)


def shape_merchant_properties(raw: dict[str, Any]) -> dict[str, Any]:
    """Project merchant POS settings. Banking fields (aba/dda account numbers)
    and internal billing flags are deliberately excluded by the allowlist."""
    return _pick(raw, *_PROPERTY_FIELDS)


def shape_item_group(raw: dict[str, Any]) -> dict[str, Any]:
    """Project an item group (a set of item variants, e.g. size/color)."""
    return _pick(raw, "id", "name")
