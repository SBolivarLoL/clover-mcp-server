"""Tool: get_merchant_info — M1 smoke-test tool and cache primer."""

from __future__ import annotations

from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.shaping import (
    shape_cash_event,
    shape_device,
    shape_merchant,
    shape_merchant_properties,
    shape_opening_hours,
    shape_order_type,
    shape_tender,
)


async def get_merchant_info(client: CloverClient) -> dict[str, Any]:
    """Return key information about the configured Clover merchant.

    This also primes the internal currency and timezone cache used by all
    other tools for money formatting and time conversion.
    """
    raw = await client.get_merchant_info()
    return shape_merchant(raw)


async def list_devices(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's Clover devices (terminals). Requires MERCHANT_R."""
    devices: list[dict[str, Any]] = []
    async for el in client.iterate("/devices", limit=100):
        devices.append(shape_device(el))
    return {"devices": devices, "count": len(devices)}


async def list_tenders(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's tender types (payment methods: cash, credit, custom).
    Requires MERCHANT_R."""
    tenders: list[dict[str, Any]] = []
    async for el in client.iterate("/tenders", limit=100):
        tenders.append(shape_tender(el))
    return {"tenders": tenders, "count": len(tenders)}


async def get_merchant_properties(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's POS configuration settings (currency, tips, stock
    tracking, closeout, locale, support contacts). Banking/account fields are
    never returned. Requires MERCHANT_R."""
    raw = await client.get("/properties")
    return shape_merchant_properties(raw)


async def list_order_types(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's order types (Dine In, Take Out, …). Requires MERCHANT_R."""
    order_types: list[dict[str, Any]] = []
    async for el in client.iterate("/order_types", limit=100):
        order_types.append(shape_order_type(el))
    return {"order_types": order_types, "count": len(order_types)}


async def list_opening_hours(client: CloverClient) -> dict[str, Any]:
    """Return the merchant's opening-hours sets (per-day time ranges). Requires MERCHANT_R."""
    hours: list[dict[str, Any]] = []
    async for el in client.iterate("/opening_hours", limit=100):
        hours.append(shape_opening_hours(el))
    return {"opening_hours": hours, "count": len(hours)}


async def list_cash_events(client: CloverClient, limit: int = 50) -> dict[str, Any]:
    """Return recent cash-drawer events (paid in/out, no-sale, deposits).

    Newest first as returned by Clover; capped at `limit` (default 50, max 500).
    Requires MERCHANT_R (cash log permission).
    """
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    events: list[dict[str, Any]] = []
    async for el in client.iterate("/cash_events", limit=min(100, limit)):
        events.append(shape_cash_event(el))
        if len(events) >= limit:
            break
    return {"cash_events": events, "count": len(events)}
