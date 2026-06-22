"""FastMCP server: tool registration and the startup permission self-check."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from clover_mcp.client import CloverClient
from clover_mcp.config import Config, load_config
from clover_mcp.errors import CloverAPIError
from clover_mcp.remote import (
    auth_context,
    build_auth_provider,
    load_tenants,
    request_tenant_key,
    tenant_config,
)
from clover_mcp.tools.customers import create_customer as _create_customer
from clover_mcp.tools.customers import get_customer as _get_customer
from clover_mcp.tools.customers import search_customers as _search_customers
from clover_mcp.tools.employees import get_employee as _get_employee
from clover_mcp.tools.employees import list_active_shifts as _list_active_shifts
from clover_mcp.tools.employees import list_employees as _list_employees
from clover_mcp.tools.employees import list_shifts as _list_shifts
from clover_mcp.tools.inventory import get_item as _get_item
from clover_mcp.tools.inventory import list_categories as _list_categories
from clover_mcp.tools.inventory import list_items as _list_items
from clover_mcp.tools.inventory import list_low_stock_items as _list_low_stock_items
from clover_mcp.tools.inventory import list_modifiers as _list_modifiers
from clover_mcp.tools.inventory import list_taxes as _list_taxes
from clover_mcp.tools.inventory import set_item_price_cents as _set_item_price_cents
from clover_mcp.tools.inventory import set_item_stock_quantity as _set_item_stock_quantity
from clover_mcp.tools.merchant import get_merchant_info as _get_merchant_info
from clover_mcp.tools.merchant import list_devices as _list_devices
from clover_mcp.tools.orders import get_order as _get_order
from clover_mcp.tools.orders import list_open_orders as _list_open_orders
from clover_mcp.tools.orders import list_orders as _list_orders
from clover_mcp.tools.reporting import get_sales_summary as _get_sales_summary
from clover_mcp.tools.reporting import get_top_items as _get_top_items
from clover_mcp.tools.reporting import list_payments as _list_payments


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """Run the startup permission self-check before the server serves tools."""
    await _check_permissions()
    yield


def _boot_config() -> Config | None:
    """Load config at import for the auth provider. Returns None if the env isn't
    configured (e.g. during tests / CI) so importing the server never requires a
    full environment — auth is simply absent in that case."""
    try:
        return load_config()
    except Exception:
        return None


_INSTRUCTIONS = (
    "Tools for querying and managing a Clover POS merchant: "
    "sales reporting, inventory, orders, and customers. "
    "IMPORTANT: This server does NOT support payment capture, refunds, "
    "voids, or charge creation — those actions must be performed in the "
    "Clover dashboard directly."
)

# Resolve the layer-1 OAuth provider once, at construction. FastMCP wires the
# Protected Resource Metadata routes from this — it can't be attached later.
_BOOT_CONFIG = _boot_config()
_auth = build_auth_provider(_BOOT_CONFIG) if _BOOT_CONFIG is not None else None

mcp: FastMCP = FastMCP(
    "Clover POS",
    instructions=_INSTRUCTIONS,
    lifespan=_lifespan,
    auth=_auth,
)


async def create_server() -> FastMCP:
    """Hosted/remote entrypoint (e.g. FastMCP Cloud `fastmcp run server.py:create_server`).

    Fail-closed: always builds the layer-1 OAuth resource server and refuses to
    construct without an IdP — so a managed HTTP deploy can never accidentally
    serve unauthenticated, regardless of the CLOVER_TRANSPORT value. Tool
    definitions are copied from the module-level server so there's one source.
    """
    config = replace(load_config(), transport="http")  # force http → auth mandatory
    auth = build_auth_provider(config)  # raises without jwks_uri + issuer + public_url
    server: FastMCP = FastMCP(
        "Clover POS", instructions=_INSTRUCTIONS, lifespan=_lifespan, auth=auth
    )
    server.mount(mcp)  # expose all 23 tools (no prefix)
    return server


# Cached config + clients. In single-merchant mode one client is reused; in
# multi-merchant mode one client is cached per resolved tenant identity.
_config: Config | None = None
_client: CloverClient | None = None
_clients: dict[str, CloverClient] = {}
_tenants_cache: dict[str, Any] | None = None


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = _BOOT_CONFIG or load_config()
    return _config


def _get_tenants() -> dict[str, Any]:
    """Parse the tenant map once per process (env blob + file store)."""
    global _tenants_cache
    if _tenants_cache is None:
        _tenants_cache = load_tenants(_get_config())
    return _tenants_cache


def _get_client() -> CloverClient:
    """Return the Clover client for the current call.

    Single-merchant (stdio or single http): a reused module-level client.
    Multi-tenant (http): resolve the tenant from the request's validated token
    identity and return a per-tenant client (built once, then cached).
    """
    config = _get_config()
    if config.multi_merchant:
        key = request_tenant_key(config)
        client = _clients.get(key)
        if client is None:
            client = CloverClient(tenant_config(config, _get_tenants(), key))
            _clients[key] = client
        return client

    global _client
    if _client is None:
        _client = CloverClient(config)
    return _client


# ── Startup permission self-check ─────────────────────────────────────────────


async def _check_permissions() -> None:
    """Best-effort startup self-check: probe one read per required permission and
    log problems. It NEVER crashes the process — a hosted platform's pre-flight
    must be able to start the server, and upstream credential/scope/network issues
    surface as 401/403 on the first tool call instead of killing startup.
    """
    try:
        config = _get_config()
    except Exception as exc:  # noqa: BLE001 — bad/absent env: warn, still start
        print(f"WARNING: could not load configuration at startup: {exc}", file=sys.stderr)
        return

    # Multi-merchant has no single startup merchant — credentials and scopes are
    # resolved (and surfaced as 403s) per request instead.
    if config.multi_merchant:
        print(
            "Starting in multi-merchant http mode; per-merchant permission checks "
            "happen on first use.",
            file=sys.stderr,
        )
        return

    try:
        client = _get_client()
    except Exception as exc:  # noqa: BLE001 — surface at call time, don't crash startup
        print(f"WARNING: could not build Clover client at startup: {exc}", file=sys.stderr)
        return

    missing: list[str] = []

    # Required scopes gate startup. EMPLOYEES_R is optional (v1.1 employee/shift
    # tools are opt-in): a 403 only warns so merchants without it keep working.
    probes: list[tuple[str, str, bool]] = [
        ("MERCHANT_R", f"/v3/merchants/{client._config.merchant_id}", True),
        ("PAYMENTS_R", "/payments", True),
        ("ORDERS_R", "/orders", True),
        ("INVENTORY_R", "/items", True),
        ("CUSTOMERS_R", "/customers", True),
        ("EMPLOYEES_R", "/employees", False),
    ]

    for perm, path, required in probes:
        try:
            await client.get(path, limit=1)
        except CloverAPIError as exc:
            if exc.status_code == 403:
                if required:
                    missing.append(f"  • {perm}: {exc.message}")
                else:
                    print(
                        f"WARNING: {perm} not granted — its tools will return 403 "
                        "(employee/shift tools are optional).",
                        file=sys.stderr,
                    )
            elif exc.status_code == 401:
                print(
                    "WARNING: Invalid or expired Clover access token — tool calls will "
                    "fail until CLOVER_ACCESS_TOKEN is fixed.",
                    file=sys.stderr,
                )
                return
            else:
                # Transient (5xx / rate limit): don't block startup — tools surface it later.
                print(
                    f"WARNING: permission probe for {perm} failed: {exc.message}", file=sys.stderr
                )
        except Exception as exc:  # noqa: BLE001 — network error etc.; warn, don't crash startup
            print(f"WARNING: permission probe for {perm} skipped: {exc}", file=sys.stderr)

    if missing:
        print("WARNING: Missing required Clover permissions:", file=sys.stderr)
        for m in missing:
            print(m, file=sys.stderr)
        print(
            "Grant these permissions via the Clover Developer Dashboard and reinstall "
            "the app on the merchant account; affected tools will return 403 until then.",
            file=sys.stderr,
        )


# ── Tool behaviour annotations ────────────────────────────────────────────────
# Clients use these structured hints (not the prose docstrings) to gate
# confirmation prompts and to parallelize read-only tools. Every tool talks to
# the Clover REST API, so openWorldHint=True throughout.
_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_WRITE_ADD = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
_WRITE_SET = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
)


# ── Tool registrations ────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def whoami() -> dict[str, Any]:
    """Diagnostic: who is this request authenticated as, and is a Clover tenant
    mapped to them?

    Returns the authenticated identity, the *names* of available token claims
    (never their values), scopes, and whether a tenant is provisioned — no Clover
    data and no secrets. Use it when setting up multi-tenant to discover which
    identity claim your platform (e.g. FastMCP Cloud / Horizon) actually provides,
    so you can key CLOVER_TENANTS_JSON correctly.
    """
    return auth_context(_get_config(), _get_tenants())


@mcp.tool(annotations=_READ)
async def get_merchant_info() -> dict[str, Any]:
    """Return key information about this Clover merchant.

    Includes name, address, currency, timezone, country, and business type.
    Also primes the internal currency and timezone cache used by all other tools.
    """
    return await _get_merchant_info(_get_client())


@mcp.tool(annotations=_READ)
async def get_sales_summary(
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Return an aggregated sales summary for the given date window.

    Defaults to today (UTC) when no dates are supplied. Uses 90-day chunking
    so multi-month or full-year queries work transparently.

    Rules: only result=SUCCESS payments counted; voids/refunds reported separately;
    tips, taxes broken out; offline payments flagged; currency from merchant record.
    This tool does NOT support payment capture, refund, or void actions.
    """
    return await _get_sales_summary(_get_client(), date_from=date_from, date_to=date_to)


@mcp.tool(annotations=_READ)
async def list_payments(
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List payments within an optional date window (default: today, limit 50).

    Only result=SUCCESS payments. Card transaction details never included.
    This tool does NOT support payment capture, refund, or void actions.
    """
    return await _list_payments(_get_client(), date_from=date_from, date_to=date_to, limit=limit)


@mcp.tool(annotations=_READ)
async def list_orders(
    date_from: str | None = None,
    date_to: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List orders within an optional date window and/or state filter (default: today, limit 50).

    state: open | paid | refunded | partially_refunded (omit for all states).
    Customer card data is never included. This tool is read-only.
    """
    return await _list_orders(
        _get_client(), date_from=date_from, date_to=date_to, state=state, limit=limit
    )


@mcp.tool(annotations=_READ)
async def get_order(order_id: str) -> dict[str, Any]:
    """Fetch a single order by ID, including line items and payment summary.

    Expands lineItems and payments only. Customer card data never expanded.
    Returns a 404 error if the order_id does not exist. This tool is read-only.
    """
    return await _get_order(_get_client(), order_id=order_id)


@mcp.tool(annotations=_READ)
async def list_open_orders() -> list[dict[str, Any]]:
    """Return all currently open orders for this merchant (up to 200).

    Convenience wrapper — no date filter, state=open only.
    Customer card data is never included. This tool is read-only.
    """
    return await _list_open_orders(_get_client())


@mcp.tool(annotations=_READ)
async def list_items(
    query: str | None = None,
    category_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a page of inventory items. Filter by name (query) or category (category_id).

    Requires INVENTORY_R.
    """
    return await _list_items(
        _get_client(), query=query, category_id=category_id, limit=limit, offset=offset
    )


@mcp.tool(annotations=_READ)
async def get_item(item_id: str) -> dict[str, Any]:
    """Return a single inventory item by ID, including stock quantity. Requires INVENTORY_R."""
    return await _get_item(_get_client(), item_id)


@mcp.tool(annotations=_READ)
async def list_low_stock_items(threshold: int = 5) -> dict[str, Any]:
    """Return all items whose stock quantity is at or below threshold.

    Items with no stock tracking are excluded. Requires INVENTORY_R.
    """
    return await _list_low_stock_items(_get_client(), threshold=threshold)


@mcp.tool(annotations=_READ)
async def list_categories() -> dict[str, Any]:
    """Return all inventory categories. Requires INVENTORY_R."""
    return await _list_categories(_get_client())


@mcp.tool(annotations=_READ)
async def list_modifiers() -> dict[str, Any]:
    """Return all modifier groups with their modifiers. Requires INVENTORY_R."""
    return await _list_modifiers(_get_client())


@mcp.tool(annotations=_READ)
async def list_taxes() -> dict[str, Any]:
    """Return the merchant's tax rates (raw rate + computed percent). Requires INVENTORY_R."""
    return await _list_taxes(_get_client())


@mcp.tool(annotations=_READ)
async def list_devices() -> dict[str, Any]:
    """Return the merchant's Clover devices/terminals. Requires MERCHANT_R."""
    return await _list_devices(_get_client())


@mcp.tool(annotations=_READ)
async def get_top_items(
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Return the best-selling items in a date window, ranked by units sold.

    Defaults to today (UTC); 90-day chunked. Each line item counts as one unit.
    Requires ORDERS_R.
    """
    return await _get_top_items(_get_client(), date_from=date_from, date_to=date_to, top_n=top_n)


@mcp.tool(annotations=_READ)
async def list_employees(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """Return a page of employees (PINs never returned). Requires EMPLOYEES_R."""
    return await _list_employees(_get_client(), limit=limit, offset=offset)


@mcp.tool(annotations=_READ)
async def get_employee(employee_id: str) -> dict[str, Any]:
    """Return a single employee by ID (PINs never returned). Requires EMPLOYEES_R."""
    return await _get_employee(_get_client(), employee_id)


@mcp.tool(annotations=_READ)
async def list_shifts(
    employee_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """List shifts, optionally by employee and/or date window. Requires EMPLOYEES_R.

    Without employee_id, aggregates shifts across all employees.
    """
    return await _list_shifts(
        _get_client(), employee_id=employee_id, date_from=date_from, date_to=date_to
    )


@mcp.tool(annotations=_READ)
async def list_active_shifts() -> dict[str, Any]:
    """Return currently open shifts (clocked in, not out) across all employees. Requires EMPLOYEES_R."""
    return await _list_active_shifts(_get_client())


@mcp.tool(annotations=_READ)
async def search_customers(
    query: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search customers by full name (query), phone, or email.

    Cards are never returned. Requires CUSTOMERS_R.
    """
    return await _search_customers(
        _get_client(), query=query, phone=phone, email=email, limit=limit
    )


@mcp.tool(annotations=_READ)
async def get_customer(customer_id: str, include: list[str] | None = None) -> dict[str, Any]:
    """Return a single customer by ID.

    Pass include=["addresses"] or include=["orders"] to opt in to optional fields.
    Cards are never returned. Requires CUSTOMERS_R.
    """
    return await _get_customer(_get_client(), customer_id, include=include)


# NOTE: the process entry point is clover_mcp.__main__:main (calls mcp.run()).
# Startup permission validation runs via the FastMCP lifespan above.


# ── Write tools (M3) ──────────────────────────────────────────────────────────
# Write permissions (CUSTOMERS_W, INVENTORY_W) are NOT probed at startup — a
# write probe would mutate data. Missing write scopes surface as a 403 at call
# time. Every write tool description begins with "Modifies merchant data." so
# MCP surfaces prompt for confirmation, and supports dry_run to preview payloads.


@mcp.tool(annotations=_WRITE_ADD)
async def create_customer(
    first_name: str,
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    marketing_allowed: bool | None = None,
    confirm_duplicate: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Create a new customer record in Clover.

    Idempotency guard: searches for an existing customer with the same email or
    phone before creating. If a match is found and confirm_duplicate is False,
    the call is refused and the existing match is returned.

    dry_run=True returns the would-be POST payload without sending it.
    Requires CUSTOMERS_R (duplicate check) and CUSTOMERS_W (write).
    """
    return await _create_customer(
        _get_client(),
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        marketing_allowed=marketing_allowed,
        confirm_duplicate=confirm_duplicate,
        dry_run=dry_run,
    )


@mcp.tool(annotations=_WRITE_SET)
async def set_item_price_cents(
    item_id: str,
    new_price_cents: int,
    expected_current_price_cents: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Set an item's price (in cents, absolute value).

    Optimistic lock: refuses the write unless the item's current price equals
    expected_current_price_cents (prevents stale-context overwrites). Bounds:
    0 <= new_price_cents <= 100_000_000. dry_run=True previews the PUT body
    (still performs one read to fetch current price/name) and never writes.
    Requires INVENTORY_R and INVENTORY_W.
    """
    return await _set_item_price_cents(
        _get_client(), item_id, new_price_cents, expected_current_price_cents, dry_run
    )


@mcp.tool(annotations=_WRITE_SET)
async def set_item_stock_quantity(
    item_id: str,
    new_quantity: int,
    expected_current_quantity: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Modifies merchant data. Set an item's stock to an ABSOLUTE quantity (not a delta).

    Optimistic lock: refuses unless current stock equals expected_current_quantity.
    Bounds: 0 <= new_quantity <= 1_000_000. dry_run=True previews the PUT body
    (still performs one read to fetch current stock) and never writes.
    Requires INVENTORY_R and INVENTORY_W.
    """
    return await _set_item_stock_quantity(
        _get_client(), item_id, new_quantity, expected_current_quantity, dry_run
    )
