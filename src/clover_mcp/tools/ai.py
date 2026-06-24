"""Layer 2 — AI/LLM tools via MCP sampling.

These tools gather Clover data with the existing read impls, then ask the
**connected client's** model to reason over it via `ctx.sample()`. The server
therefore never holds an LLM provider key or makes a paid API call itself.

Design contract (applies to every tool here):
  * Gather with the existing shaped read tools → build a **bounded** prompt.
  * Call `ctx.sample()`; return structured data PLUS the model's narrative,
    clearly labelled as an AI suggestion.
  * **Read-only** — never write back the model's output.
  * **Capability fallback** — if the client can't sample, return the raw data
    with a note instead of hard-failing (`_narrate` handles this).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from clover_mcp.client import CloverClient
from clover_mcp.tools.customers import get_customer
from clover_mcp.tools.inventory import list_categories, list_items, list_low_stock_items
from clover_mcp.tools.reporting import get_sales_summary, get_top_items, list_refunds

if TYPE_CHECKING:
    from fastmcp import Context

# Keep prompts bounded — never feed an unbounded catalog/customer list to the model.
_MAX_ROWS = 40


def _trim(rows: list[Any]) -> list[Any]:
    return rows[:_MAX_ROWS]


async def _narrate(
    ctx: Context,
    *,
    system: str,
    user: str,
    data: dict[str, Any],
    max_tokens: int = 600,
) -> dict[str, Any]:
    """Ask the client's model to reason over `data`, returning data + narrative.

    Falls back gracefully: if the client doesn't support sampling (or it errors),
    return the data with a note rather than failing the tool.
    """
    try:
        result = await ctx.sample(user, system_prompt=system, max_tokens=max_tokens)
        text = (result.text or "").strip()
        return {"data": data, "ai_summary": text, "is_ai_generated": True}
    except Exception as exc:  # noqa: BLE001 — capability/transport fallback, never hard-fail
        return {
            "data": data,
            "note": (
                "Returned raw data only — this client did not provide a sampling-capable "
                f"model ({type(exc).__name__}). Connect a client that supports MCP sampling "
                "for the AI narrative, or reason over `data` yourself."
            ),
            "is_ai_generated": False,
        }


async def summarize_sales(
    client: CloverClient,
    ctx: Context,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Plain-language sales briefing for a date window (suggestion, read-only)."""
    summary = await get_sales_summary(client, date_from=date_from, date_to=date_to)
    top = await get_top_items(client, date_from=date_from, date_to=date_to, top_n=10)
    data = {"sales_summary": summary, "top_items": top}
    return await _narrate(
        ctx,
        system=(
            "You are a concise retail analyst. Summarize the merchant's sales for the period "
            "in plain language: headline totals, notable movements, and the best sellers. "
            "Use only the data provided. Do not invent figures. A few short bullets."
        ),
        user="Summarize these sales figures:\n" + json.dumps(data, default=str),
        data=data,
    )


async def suggest_item_categories(
    client: CloverClient,
    ctx: Context,
    limit: int = 100,
) -> dict[str, Any]:
    """Propose categories for uncategorized items from the merchant's own taxonomy.

    Suggestion only — applying a category is a separate, confirmed write.
    """
    cats = await list_categories(client)
    items_page = await list_items(client, limit=limit)
    items = items_page.get("items", items_page.get("elements", []))
    uncategorized = [
        {"id": it.get("id"), "name": it.get("name")} for it in items if not it.get("categories")
    ]
    data = {
        "existing_categories": [
            c.get("name") for c in cats.get("categories", cats.get("elements", []))
        ],
        "uncategorized_items": _trim(uncategorized),
        "uncategorized_count": len(uncategorized),
    }
    return await _narrate(
        ctx,
        system=(
            "You categorize POS inventory. For each uncategorized item, suggest the single "
            "best-fit category FROM THE EXISTING category list only (do not invent new ones). "
            "If nothing fits, say 'none'. Output a compact item → category mapping. "
            "This is a suggestion; the merchant must confirm before anything is applied."
        ),
        user="Suggest categories:\n" + json.dumps(data, default=str),
        data=data,
        max_tokens=800,
    )


async def inventory_reorder_suggestions(
    client: CloverClient,
    ctx: Context,
    threshold: int = 5,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Cross low stock with recent sales velocity into a prioritized reorder list."""
    low = await list_low_stock_items(client, threshold=threshold)
    velocity = await get_top_items(client, date_from=date_from, date_to=date_to, top_n=40)
    data = {
        "low_stock": _trim(low.get("items", low.get("elements", []))),
        "sales_velocity": velocity.get("items", velocity),
    }
    return await _narrate(
        ctx,
        system=(
            "You manage retail reordering. Given items low in stock and recent sales velocity, "
            "produce a prioritized reorder list: fastest-selling low-stock items first. Note any "
            "low-stock item with no recent sales (may not need reordering). Use only the data given."
        ),
        user="Suggest what to reorder:\n" + json.dumps(data, default=str),
        data=data,
    )


async def detect_sales_anomalies(
    client: CloverClient,
    ctx: Context,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Flag unusual refund / discount / sales patterns in a window (read-only)."""
    summary = await get_sales_summary(client, date_from=date_from, date_to=date_to)
    refunds = await list_refunds(client, date_from=date_from, date_to=date_to, limit=50)
    data = {"sales_summary": summary, "refunds": _trim(refunds), "refund_count": len(refunds)}
    return await _narrate(
        ctx,
        system=(
            "You are a loss-prevention analyst. Review the period's totals and refunds and flag "
            "anything that looks unusual (high refund ratio, refund clustering, low net vs gross). "
            "Be measured: explain why each flag is notable. Only use the data provided; if nothing "
            "looks unusual, say so."
        ),
        user="Review for anomalies:\n" + json.dumps(data, default=str),
        data=data,
    )


async def draft_customer_message(
    client: CloverClient,
    ctx: Context,
    customer_id: str,
    intent: str,
) -> dict[str, Any]:
    """Draft a customer message (promo / win-back / thank-you) — a draft, never sent."""
    customer = await get_customer(client, customer_id, include=["orders"])
    data = {"customer": customer, "intent": intent}
    return await _narrate(
        ctx,
        system=(
            "You write short, friendly customer messages for a small business. Draft a message "
            "for the stated intent. Keep it brief and personal; use the customer's first name if "
            "available. Do NOT promise discounts or terms that aren't in the intent. This is a "
            "DRAFT for the owner to review and send themselves — never sent automatically."
        ),
        user="Draft a message:\n" + json.dumps(data, default=str),
        data=data,
        max_tokens=400,
    )
