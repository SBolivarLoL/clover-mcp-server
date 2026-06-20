"""Tools: search_customers, get_customer, create_customer — Customers (CUSTOMERS_R/W).

Card data is NEVER returned by any function in this module, even when explicitly
requested via the *include* parameter.  This is enforced by shape_customer().
"""

from __future__ import annotations

from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.shaping import shape_customer

# Fields the Clover API supports for customer filtering (verified in endpoint audit)
# Supported: customerSince, deletedTime, emailAddress, firstName, fullName,
#            id, lastName, marketingAllowed, phoneNumber
_EXPAND_DEFAULT = "emailAddresses,phoneNumbers"


async def search_customers(
    client: CloverClient,
    query: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search for customers by name, phone, or email.

    *query* matches against fullName (Clover's combined first+last field).
    *phone* matches against phoneNumber (exact).
    *email* matches against emailAddress (exact).

    Only one filter is applied at a time; precedence: phone > email > query.
    Cards are never returned.

    Requires CUSTOMERS_R permission.
    """
    params: dict[str, Any] = {
        "limit": limit,
        "expand": _EXPAND_DEFAULT,
    }

    if phone:
        params["filter"] = f"phoneNumber={phone}"
    elif email:
        params["filter"] = f"emailAddress={email}"
    elif query:
        params["filter"] = f"fullName={query}"

    body = await client.get("/customers", **params)
    elements: list[dict[str, Any]] = body.get("elements", [])
    return {
        "customers": [shape_customer(el) for el in elements],
        "count": len(elements),
        "limit": limit,
    }


async def create_customer(
    client: CloverClient,
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    marketing_allowed: bool | None = None,
    confirm_duplicate: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new customer record in Clover.

    Idempotency guard: before creating, searches for an existing customer with
    the same email (if provided) or phone (if provided). If a match is found
    and *confirm_duplicate* is False, the call is refused and the existing
    match is returned — no customer is created. Pass confirm_duplicate=True
    only after the caller has confirmed to the user that the duplicate should
    be created.

    *dry_run=True* returns the request payload that would be POSTed without
    sending it — useful for previewing the call without writing data.

    NOTE: marketingAllowed is accepted by the Clover API in the POST body but
    is silently ignored by the sandbox (always returns false). The field is
    included in the body for forward-compatibility with production behaviour.

    Requires CUSTOMERS_R (for duplicate check) and CUSTOMERS_W (for the write).
    """
    # --- Build request body ------------------------------------------------
    body: dict[str, Any] = {
        "firstName": first_name,
        "lastName": last_name,
    }
    if email is not None:
        body["emailAddresses"] = [{"emailAddress": email}]
    if phone is not None:
        body["phoneNumbers"] = [{"phoneNumber": phone}]
    if marketing_allowed is not None:
        body["marketingAllowed"] = marketing_allowed

    # --- Dry run (no network calls at all) ---------------------------------
    if dry_run:
        return {"dry_run": True, "would_post": body}

    # --- Duplicate check ---------------------------------------------------
    if not confirm_duplicate and (email or phone):
        search_result = await search_customers(
            client,
            email=email if email else None,
            phone=phone if (phone and not email) else None,
        )
        if search_result["count"] > 0:
            existing = search_result["customers"][0]
            return {
                "created": False,
                "reason": "duplicate",
                "message": (
                    "A customer with the same email or phone already exists. "
                    "Pass confirm_duplicate=True to create anyway."
                ),
                "existing_customer": existing,
            }

    # --- POST (never retried — non-idempotent) -----------------------------
    raw = await client.post(
        "/customers",
        json=body,
        expand=_EXPAND_DEFAULT,
    )
    return {"created": True, "customer": shape_customer(raw)}


async def get_customer(
    client: CloverClient,
    customer_id: str,
    include: list[str] | None = None,
) -> dict[str, Any]:
    """Return a single customer record by ID.

    *include* is the only way to opt in to optional field groups:
      - "addresses" — physical address records
      - "orders"    — order history (IDs and totals)

    "cards" is never returned regardless of what is in *include*.

    Requires CUSTOMERS_R permission.
    """
    # Build expand param: always include contact fields; optionally more
    expand_parts = ["emailAddresses", "phoneNumbers"]
    allowed_extras = {"addresses", "orders"}
    for field in include or []:
        if field in allowed_extras:
            expand_parts.append(field)

    raw = await client.get(
        f"/customers/{customer_id}",
        expand=",".join(expand_parts),
    )
    return shape_customer(raw, include=include)
