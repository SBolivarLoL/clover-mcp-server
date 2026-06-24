"""Contract: Layer 3 prompts are registered and reference real tools.

A prompt that names a tool which doesn't exist would send the agent down a dead
end, so this pins prompt text to the actual tool inventory.
"""

from __future__ import annotations

import pytest

from clover_mcp import prompts, server

EXPECTED_PROMPTS = {
    "daily_briefing",
    "weekly_sales_report",
    "inventory_health_check",
    "end_of_day_closeout",
    "customer_lookup",
    "monthly_tax_summary",
}


@pytest.mark.asyncio
async def test_all_prompts_registered() -> None:
    registered = {p.name for p in await server.mcp.list_prompts()}
    assert registered >= EXPECTED_PROMPTS


def test_parameterized_prompts_use_their_argument() -> None:
    assert "Ada Lovelace" in prompts.customer_lookup("Ada Lovelace")
    assert "2026-06" in prompts.monthly_tax_summary("2026-06")


def test_prompts_reference_their_tools() -> None:
    """Each prompt must name the read tools it's meant to drive (catches typos)."""
    expected = {
        "daily_briefing": ["get_sales_summary", "list_low_stock_items", "list_open_orders"],
        "weekly_sales_report": ["get_sales_summary", "get_top_items", "list_tenders"],
        "inventory_health_check": ["list_low_stock_items", "list_categories", "list_items"],
        "end_of_day_closeout": ["get_sales_summary", "list_payments", "list_refunds"],
        "customer_lookup": ["search_customers", "get_customer"],
        "monthly_tax_summary": ["get_sales_summary", "list_taxes"],
    }
    for name, tools in expected.items():
        fn = getattr(prompts, name)
        text = fn("x") if fn.__code__.co_argcount else fn()
        for tool in tools:
            assert tool in text, f"{name} should reference {tool}"
