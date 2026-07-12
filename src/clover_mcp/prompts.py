"""Predefined MCP prompts (Layer 3) — vetted, parameterized workflows.

A prompt is **not** an LLM call. It returns instruction text that drives the
existing read tools so a merchant's agent runs common workflows the same way
every time. Every prompt names the tools it should chain and the order to call
them, so the agent does not have to (re)discover the workflow.

Register with `register_prompts(mcp)` from server.py. The bodies are plain
functions returning `str` so they can be unit-tested without a live server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def daily_briefing() -> str:
    """A start-of-day briefing: today's sales, low stock, and open orders."""
    return (
        "Give me a concise daily briefing for my Clover business. Run these tools and "
        "summarize the results in plain language:\n"
        "1. `get_sales_summary` for today (no date arguments = today) — report gross "
        "sales, net sales, refunds, tips, and tax.\n"
        "2. `list_low_stock_items` (threshold 5) — list anything running low so I can reorder.\n"
        "3. `list_open_orders` — how many orders are still open and their total value.\n\n"
        "Keep it short: a few bullet points and one sentence flagging anything that needs "
        "my attention today. Do not perform any writes."
    )


def weekly_sales_report() -> str:
    """A 7-day sales report: totals, best sellers, and tender mix."""
    return (
        "Build a weekly sales report covering the last 7 days. Steps:\n"
        "1. Determine the date range: today minus 6 days through today (inclusive).\n"
        "2. `get_sales_summary` for that range — gross, net, refunds, tips, tax.\n"
        "3. `get_top_items` for the same range (top_n 10) — the best sellers by units.\n"
        "4. `list_tenders` — so you can describe which payment methods are configured.\n"
        "5. Optionally `get_sales_summary` for the prior 7 days to show the trend "
        "(up or down vs. the previous week).\n\n"
        "Present a short report: headline totals, a top-sellers table, and one line on "
        "the week-over-week trend. Read-only — make no changes."
    )


def inventory_health_check() -> str:
    """Surface low stock, uncategorized items, and catalog gaps."""
    return (
        "Run an inventory health check and tell me what needs attention:\n"
        "1. `list_low_stock_items` (threshold 5) — items at or below 5 in stock.\n"
        "2. `list_categories`, then `list_items` — flag items whose `categories` list is "
        "empty (uncategorized items are hard for staff and customers to find).\n"
        "3. `list_items` — flag items missing a price (price 0) or a SKU/code.\n\n"
        "Output three short lists: Low stock, Uncategorized, and Missing price/SKU. "
        "Suggest next steps but do not change anything (categorizing or repricing is a "
        "separate, confirmed action)."
    )


def end_of_day_closeout() -> str:
    """Reconcile the day: payments, refunds, and open orders still pending."""
    return (
        "Help me close out the day. Reconcile today's activity:\n"
        "1. `get_sales_summary` for today — the headline numbers.\n"
        "2. `list_payments` for today — the individual successful payments.\n"
        "3. `list_refunds` for today — anything refunded.\n"
        "4. `list_open_orders` — orders still open that should be settled before closing.\n\n"
        "Summarize: total collected, total refunded, net, and a clear callout of any open "
        "orders that still need to be paid or closed. This is a report only — do not capture, "
        "refund, or void anything (those are done in the Clover dashboard)."
    )


def customer_lookup(query: str) -> str:
    """Find a customer and summarize who they are and their recent history."""
    return (
        f"Look up the customer matching '{query}' and summarize them:\n"
        f"1. `search_customers` with query='{query}' (or use the phone/email argument if "
        "the query looks like a phone number or email).\n"
        "2. If exactly one match, call `get_customer` with that id and "
        "include=['orders'] to pull their order history.\n"
        "3. If several match, list the candidates and ask me which one.\n\n"
        "Report their name, contact info, marketing opt-in status, and a short summary of "
        "their recent orders. Never display card data (it is never returned). Read-only."
    )


def monthly_tax_summary(month: str) -> str:
    """Tax collected for a given month (format YYYY-MM), broken down by rate."""
    return (
        f"Produce a tax summary for {month} (format YYYY-MM). Steps:\n"
        f"1. Compute the first and last day of {month} as the date range.\n"
        "2. `get_sales_summary` for that range — read the tax collected and taxable sales.\n"
        "3. `list_taxes` — list the merchant's configured tax rates so the summary can "
        "attribute tax to each rate where possible.\n\n"
        "Present total tax collected for the month and the configured rates. Note clearly "
        "that this is an informational summary, not a filing — confirm figures against the "
        "Clover dashboard before using them for taxes. Read-only."
    )


_PROMPTS = (
    daily_briefing,
    weekly_sales_report,
    inventory_health_check,
    end_of_day_closeout,
    customer_lookup,
    monthly_tax_summary,
)


def register_prompts(mcp: FastMCP) -> None:
    """Register every prompt on the given server. Docstrings become descriptions;
    typed arguments (e.g. `query`, `month`) become prompt arguments automatically."""
    for fn in _PROMPTS:
        mcp.prompt(fn)
