"""Layer 4 — MCP resources: a read-only capability cheat-sheet.

`clover://capabilities` lets an agent ground itself on what this server can do
(tools by read/write, prompts, guardrails, hard exclusions) in one fetch instead
of spending tool calls to discover it. Built live from the registered tools and
prompts so it can't drift. No merchant data and no secrets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Things this server will never do — surfaced so an agent doesn't try.
_EXCLUSIONS = [
    "payment capture / charge creation",
    "refunds and voids",
    "record deletes",
    "gateway / processing configuration",
    "Ecommerce API and device-paired endpoints",
    "returning card data, employee PINs, or merchant banking/account numbers",
]


def register_resources(mcp: FastMCP) -> None:
    """Register the capabilities resource on the given server."""

    @mcp.resource(
        "clover://capabilities",
        name="capabilities",
        mime_type="application/json",
        description="What this Clover MCP server can do: tools, prompts, and guardrails.",
    )
    async def capabilities() -> dict[str, Any]:
        tools = await mcp.list_tools()
        reads = sorted(t.name for t in tools if getattr(t.annotations, "readOnlyHint", False))
        writes = sorted(t.name for t in tools if not getattr(t.annotations, "readOnlyHint", False))
        prompts = sorted(p.name for p in await mcp.list_prompts())
        return {
            "summary": (
                "Run a Clover POS merchant by conversation: reporting, inventory, "
                "orders, and customers. Reads are allowlist-shaped (no card/PII leakage); "
                "writes require confirmation (MCP elicitation or confirm=True)."
            ),
            "read_tools": reads,
            "write_tools": writes,
            "prompts": prompts,
            "guardrails": {
                "writes_need_confirmation": True,
                "writes_support_dry_run": True,
                "ai_tools_use_client_sampling": True,
                "response_shaping_allowlist": True,
            },
            "excluded_by_design": _EXCLUSIONS,
            "counts": {"reads": len(reads), "writes": len(writes), "prompts": len(prompts)},
        }
