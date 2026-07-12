#!/usr/bin/env python
"""Measure the token cost of the MCP tool-definition schemas sent to clients.

Every tool's `tools/list` wire payload (name, description, inputSchema,
outputSchema, annotations, meta) counts against the client's context budget
before a single call is made. This script sums that cost across all registered tools
and can fail CI when it grows too much.

Token counting prefers `tiktoken` (cl100k_base) when installed, falling back
to a chars/4 heuristic otherwise. tiktoken is NOT a project dependency —
it's an optional accuracy upgrade, never installed automatically.

Usage:
    uv run python scripts/schema_budget.py                  # print table + total
    uv run python scripts/schema_budget.py --check           # fail if >10% over baseline
    uv run python scripts/schema_budget.py --update-baseline # overwrite the baseline file
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).parent / "schema_budget.baseline.json"
GROWTH_TOLERANCE = 0.10  # fail --check if current total exceeds baseline by more than this


def _count_tokens(text: str) -> tuple[int, str]:
    """Return (token_count, method_name) for a serialized tool schema."""
    try:
        import tiktoken  # type: ignore[import-not-found]

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text)), "tiktoken"
    except ImportError:
        return len(text) // 4, "chars/4"


async def per_tool() -> tuple[list[tuple[str, int]], str]:
    """Return ((tool_name, token_count) per registered tool, method_name), using
    whichever counting method is available (tiktoken or chars/4)."""
    from clover_mcp import server

    tools = await server.mcp.list_tools()
    results: list[tuple[str, int]] = []
    method = "chars/4"
    for tool in tools:
        wire_dict: dict[str, Any] = tool.to_mcp_tool().model_dump(exclude_none=True)
        text = json.dumps(wire_dict, separators=(",", ":"))
        tokens, method = _count_tokens(text)
        results.append((tool.name, tokens))
    return results, method


async def measure() -> tuple[int, str]:
    """Return (total_tokens, method) across all tool schemas."""
    rows, method = await per_tool()
    return sum(tokens for _, tokens in rows), method


def _load_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.exists():
        return None
    result: dict[str, Any] = json.loads(BASELINE_PATH.read_text())
    return result


def _write_baseline(total: int, method: str) -> None:
    BASELINE_PATH.write_text(json.dumps({"total_tokens": total, "method": method}, indent=2) + "\n")


async def _run(args: argparse.Namespace) -> int:
    if args.update_baseline:
        total, method = await measure()
        _write_baseline(total, method)
        print(f"Baseline updated: {total} tokens ({method}) -> {BASELINE_PATH}")
        return 0

    if args.check:
        total, method = await measure()
        baseline = _load_baseline()
        if baseline is None:
            print(f"No baseline found at {BASELINE_PATH}; run --update-baseline first.")
            return 1

        # ponytail: "acknowledging growth" is just re-running --update-baseline and
        # committing the new file by hand — no changelog parsing, no approval workflow.
        if baseline["method"] != method:
            print(
                f"WARNING: baseline was measured with '{baseline['method']}' but current "
                f"run used '{method}' — these are not comparable. Skipping ratio check."
            )
            return 0

        limit = baseline["total_tokens"] * (1 + GROWTH_TOLERANCE)
        print(
            f"Current: {total} tokens ({method}); baseline: {baseline['total_tokens']}; limit: {limit:.0f}"
        )
        if total > limit:
            print(f"FAIL: schema token count grew more than {GROWTH_TOLERANCE:.0%} over baseline.")
            return 1
        print("OK: within budget.")
        return 0

    rows, method = await per_tool()
    rows.sort(key=lambda row: row[1], reverse=True)
    total = sum(tokens for _, tokens in rows)
    name_width = max(len(name) for name, _ in rows)
    for name, tokens in rows:
        print(f"{name:<{name_width}}  {tokens:>6}")
    print("-" * (name_width + 8))
    print(f"{'TOTAL':<{name_width}}  {total:>6}  ({method})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if current total exceeds the committed baseline by more than 10%%.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite scripts/schema_budget.baseline.json with the current total.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
