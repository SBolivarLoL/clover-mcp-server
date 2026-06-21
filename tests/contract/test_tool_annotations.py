"""Contract: every tool carries the correct MCP behaviour annotations.

Clients (Claude Code, ChatGPT, …) rely on these structured hints — not the prose
docstrings — to gate confirmation prompts and to parallelize read-only tools.
This test pins the read/write/destructive/idempotent classification so a future
edit can't silently mislabel a write as read-only.
"""

from __future__ import annotations

import pytest

from clover_mcp import server

READ_TOOLS = [
    "get_merchant_info",
    "get_sales_summary",
    "list_payments",
    "list_orders",
    "get_order",
    "list_open_orders",
    "list_items",
    "get_item",
    "list_low_stock_items",
    "search_customers",
    "get_customer",
    # v1.1 read tools
    "list_categories",
    "list_modifiers",
    "list_taxes",
    "list_devices",
    "get_top_items",
    "list_employees",
    "get_employee",
    "list_shifts",
    "list_active_shifts",
]
WRITE_TOOLS = ["create_customer", "set_item_price_cents", "set_item_stock_quantity"]


@pytest.mark.asyncio
async def test_tool_inventory_is_complete() -> None:
    """All 23 tools exist and every one is annotated."""
    assert len(READ_TOOLS + WRITE_TOOLS) == 23
    for name in READ_TOOLS + WRITE_TOOLS:
        ann = (await server.mcp.get_tool(name)).annotations
        assert ann is not None, f"{name} has no annotations"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", READ_TOOLS)
async def test_read_tools_are_read_only(name: str) -> None:
    ann = (await server.mcp.get_tool(name)).annotations
    assert ann.readOnlyHint is True
    assert ann.openWorldHint is True


@pytest.mark.asyncio
async def test_create_customer_is_additive_write() -> None:
    ann = (await server.mcp.get_tool("create_customer")).annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is False  # additive, not destructive
    assert ann.openWorldHint is True


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["set_item_price_cents", "set_item_stock_quantity"])
async def test_item_writes_are_destructive_and_idempotent(name: str) -> None:
    ann = (await server.mcp.get_tool(name)).annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is True  # overwrites existing value
    assert ann.idempotentHint is True  # absolute set — repeat calls are no-ops
    assert ann.openWorldHint is True
