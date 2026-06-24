"""Tool: get_merchant_info — M1 smoke-test tool and cache primer."""

from __future__ import annotations

from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.shaping import (
    shape_device,
    shape_merchant,
    shape_merchant_properties,
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
