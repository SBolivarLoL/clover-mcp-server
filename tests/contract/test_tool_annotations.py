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
    "whoami",
    "get_merchant_info",
    "get_sales_summary",
    "list_payments",
    "list_refunds",
    "list_credits",
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
    "list_item_groups",
    "list_taxes",
    "list_discounts",
    "list_devices",
    "list_tenders",
    "get_merchant_properties",
    # Layer 1 reads — reference data + inventory depth
    "list_order_types",
    "list_opening_hours",
    "list_tip_suggestions",
    "get_default_service_charge",
    "list_cash_events",
    "list_attributes",
    "list_tags",
    "get_top_items",
    "list_employees",
    "get_employee",
    "list_shifts",
    "list_active_shifts",
    "list_roles",
    # Layer 2 AI/LLM tools (sampling) — read-only (never write the model's output)
    "summarize_sales",
    "suggest_item_categories",
    "inventory_reorder_suggestions",
    "detect_sales_anomalies",
    "draft_customer_message",
]
WRITE_TOOLS = [
    "create_customer",
    "set_item_price_cents",
    "set_item_stock_quantity",
    # Layer 1 guarded creates (additive) + update (destructive) — Layer 4 elicitation
    "create_category",
    "create_item",
    "create_order",
    "add_line_item",
    "update_customer",
    # Roadmap-completion writes (2026-07-05 audit)
    "apply_order_discount",
    "update_item_name",
    "create_modifier_group",
    "create_modifier",
    "create_tag",
]
# Additive writes: destructiveHint=False (they create, never overwrite/delete)
ADDITIVE_WRITES = [
    "create_customer",
    "create_category",
    "create_item",
    "create_order",
    "add_line_item",
    "create_modifier_group",
    "create_modifier",
    "create_tag",
]
# Set-style writes: destructiveHint=True, idempotentHint=True (overwrite an
# existing value — repeat calls with the same args are no-ops)
SET_WRITES = [
    "apply_order_discount",
    "update_item_name",
]


@pytest.mark.asyncio
async def test_tool_inventory_is_complete() -> None:
    """READ_TOOLS + WRITE_TOOLS must exactly match every tool registered on the
    live FastMCP instance — not a hardcoded count. If this fails after adding a
    tool, add its name to READ_TOOLS or WRITE_TOOLS above (and classify it in
    ADDITIVE_WRITES/SET_WRITES if it's a write) instead of bumping a number."""
    registered = {t.name for t in await server.mcp.list_tools()}
    listed = set(READ_TOOLS + WRITE_TOOLS)
    missing_from_list = registered - listed
    stale_in_list = listed - registered
    assert not missing_from_list, f"registered but not classified here: {missing_from_list}"
    assert not stale_in_list, f"classified here but no longer registered: {stale_in_list}"
    assert len(registered) == 53
    for name in READ_TOOLS + WRITE_TOOLS:
        ann = (await server.mcp.get_tool(name)).annotations
        assert ann is not None, f"{name} has no annotations"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", READ_TOOLS)
async def test_read_tools_are_read_only(name: str) -> None:
    ann = (await server.mcp.get_tool(name)).annotations
    assert ann.readOnlyHint is True
    # whoami is local (auth context only) — it makes no Clover call, so it's the
    # one read tool that is not open-world.
    assert ann.openWorldHint is (name != "whoami")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADDITIVE_WRITES)
async def test_additive_writes_are_not_destructive(name: str) -> None:
    ann = (await server.mcp.get_tool(name)).annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is False  # additive, not destructive
    assert ann.openWorldHint is True


@pytest.mark.asyncio
async def test_update_customer_is_destructive() -> None:
    """update_customer overwrites existing fields → destructive."""
    ann = (await server.mcp.get_tool("update_customer")).annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is True


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["set_item_price_cents", "set_item_stock_quantity"])
async def test_item_writes_are_destructive_and_idempotent(name: str) -> None:
    ann = (await server.mcp.get_tool(name)).annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is True  # overwrites existing value
    assert ann.idempotentHint is True  # absolute set — repeat calls are no-ops
    assert ann.openWorldHint is True


@pytest.mark.asyncio
@pytest.mark.parametrize("name", SET_WRITES)
async def test_set_writes_are_destructive_and_idempotent(name: str) -> None:
    ann = (await server.mcp.get_tool(name)).annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is True  # overwrites existing value
    assert ann.idempotentHint is True
    assert ann.openWorldHint is True
