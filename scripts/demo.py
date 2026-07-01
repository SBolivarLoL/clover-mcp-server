#!/usr/bin/env python
"""A runnable 5-minute technical demo of clover-mcp against a Clover sandbox.

Narrates a realistic operator session — reporting, inventory, customers, and a
**guarded write shown as a dry-run preview** (no data is mutated). Everything here
is read-only or dry-run; safe to run repeatedly.

Usage:
    uv run python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.config import load_config
from clover_mcp.tools import customers as C
from clover_mcp.tools import inventory as I
from clover_mcp.tools import merchant as M
from clover_mcp.tools import reporting as R


def _say(step: str, text: str) -> None:
    print(f"\n\033[1m▶ {step}\033[0m  {text}")


def _show(label: str, value: Any) -> None:
    blob = json.dumps(value, default=str)
    print(f"    {label}: {blob[:220]}{'…' if len(blob) > 220 else ''}")


async def main() -> None:
    config = load_config()
    client = CloverClient(config)
    env = "SANDBOX" if config.sandbox else "PRODUCTION"
    print(f"clover-mcp demo — talking to a Clover {env} merchant, in plain tool calls.\n")

    _say("1. Who am I connected to?", "get_merchant_info")
    merchant = await M.get_merchant_info(client)
    _show(
        "merchant",
        {
            "name": merchant.get("name"),
            "currency": merchant.get("defaultCurrency") or merchant.get("currency"),
            "timezone": merchant.get("timezone"),
            "country": merchant.get("country"),
        },
    )

    _say("2. How did we do today?", "get_sales_summary (defaults to today)")
    summary = await R.get_sales_summary(client)
    _show(
        "sales",
        {
            k: summary.get(k)
            for k in ("gross_sales", "net_sales", "refund_amount", "tip_amount", "tax_amount")
        },
    )

    _say("3. What's running low?", "list_low_stock_items(threshold=5)")
    low = await I.list_low_stock_items(client, threshold=5)
    _show("low_stock", {"count": low.get("count"), "sample": low.get("items", [])[:2]})

    _say("4. What's in the catalog?", "list_items")
    items = await I.list_items(client, limit=5)
    catalog = items.get("items", [])
    _show("items", [{"name": it.get("name"), "price": it.get("price")} for it in catalog[:5]])

    _say("5. Look up a customer", "search_customers — note: card data is never returned")
    customers = await C.search_customers(client, limit=3)
    _show(
        "customers",
        [
            {"name": f"{c.get('firstName')} {c.get('lastName')}", "has_cards_field": "cards" in c}
            for c in customers.get("customers", [])[:3]
        ],
    )

    _say(
        "6. Change a price — safely", "set_item_price_cents(dry_run=True) — previews, never writes"
    )
    if catalog:
        item = catalog[0]
        preview = await I.set_item_price_cents(
            client,
            item_id=item["id"],
            new_price_cents=int(item.get("price", 0)) + 50,
            expected_current_price_cents=int(item.get("price", 0)),
            dry_run=True,
        )
        _show("dry_run", preview)
    else:
        print("    (no catalog items to preview a price change on)")

    _say("7. What it will NOT do", "by design")
    print(
        "    No payment capture, refunds, voids, or record deletes — those stay in the Clover dashboard."
    )
    print("    Card numbers, employee PINs, and bank/account numbers are never returned.")

    await client.close()
    print(
        "\n\033[1mDemo complete.\033[0m Reads were live; the price change was a dry-run preview — nothing was mutated."
    )


if __name__ == "__main__":
    asyncio.run(main())
