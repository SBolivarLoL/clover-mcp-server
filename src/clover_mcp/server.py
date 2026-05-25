"""FastMCP server: tool registration, startup permission checks, run()."""

from __future__ import annotations

import sys
from typing import Any

from fastmcp import FastMCP

from clover_mcp.client import CloverClient
from clover_mcp.config import load_config
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools.merchant import get_merchant_info as _get_merchant_info

mcp: FastMCP = FastMCP(
    "Clover POS",
    instructions=(
        "Tools for querying and managing a Clover POS merchant: "
        "sales reporting, inventory, orders, customers, and employee shifts. "
        "IMPORTANT: This server does NOT support payment capture, refunds, "
        "voids, or charge creation — those actions must be performed in the "
        "Clover dashboard directly."
    ),
)

# Module-level client — initialised lazily on first tool call
_client: CloverClient | None = None


def _get_client() -> CloverClient:
    global _client
    if _client is None:
        config = load_config()
        _client = CloverClient(config)
    return _client


# ── Startup permission self-check ─────────────────────────────────────────────


async def _check_permissions() -> None:
    """Probe one read per required permission category and report failures."""
    client = _get_client()
    missing: list[str] = []

    probes: list[tuple[str, str]] = [
        ("MERCHANT_R", f"/v3/merchants/{client._config.merchant_id}"),
    ]

    for perm, path in probes:
        try:
            await client.get(path, limit=1)
        except CloverAPIError as exc:
            if exc.status_code == 403:
                missing.append(f"  • {perm}: {exc.message}")
            elif exc.status_code == 401:
                print(
                    "ERROR: Invalid or expired access token. Check CLOVER_ACCESS_TOKEN.",
                    file=sys.stderr,
                )
                sys.exit(1)

    if missing:
        print("ERROR: Missing required Clover permissions:", file=sys.stderr)
        for m in missing:
            print(m, file=sys.stderr)
        print(
            "Grant these permissions via the Clover Developer Dashboard "
            "and reinstall the app on the merchant account.",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Tool registrations ────────────────────────────────────────────────────────


@mcp.tool()
async def get_merchant_info() -> dict[str, Any]:
    """Return key information about this Clover merchant.

    Includes name, address, currency, timezone, country, and business type.
    Also primes the internal currency and timezone cache used by all other tools.
    """
    return await _get_merchant_info(_get_client())


# ── Entry point ───────────────────────────────────────────────────────────────


def run() -> None:
    mcp.run()
