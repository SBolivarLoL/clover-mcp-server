#!/usr/bin/env python
"""Seed / verify / clean up Clover SANDBOX data for the v1.1 read tools.

Throwaway helper to live-verify the endpoints behind list_employees, list_shifts,
list_categories, list_modifiers, list_taxes, list_devices, and get_top_items.

    python scripts/seed_sandbox.py            # create sandbox data, save IDs
    python scripts/seed_sandbox.py verify     # run the 9 v1.1 read tools live
    python scripts/seed_sandbox.py cleanup    # delete everything this script made

HARD-GATED to sandbox: it refuses to run unless CLOVER_SANDBOX=true. Created
object IDs are recorded in scripts/.seed_state.json (gitignored) so cleanup is
exact — it never deletes anything it didn't create. Devices cannot be created
via the REST API (they are provisioned hardware), so they are only listed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clover_mcp.client import CloverClient  # noqa: E402
from clover_mcp.config import load_config  # noqa: E402
from clover_mcp.errors import CloverAPIError  # noqa: E402

STATE_FILE = Path(__file__).resolve().parent / ".seed_state.json"


def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))
    STATE_FILE.chmod(0o600)


def _require_sandbox() -> CloverClient:
    config = load_config()
    if not config.sandbox:
        sys.exit("REFUSED: CLOVER_SANDBOX is not true. This script only runs against the sandbox.")
    return CloverClient(config)


async def _try(label: str, coro: Any) -> Any:
    """Run a write, log the outcome, and swallow API errors (best-effort seeding)."""
    try:
        result = await coro
        print(f"  ✓ {label}")
        return result
    except CloverAPIError as exc:
        print(f"  ⚠ {label} skipped ({exc.status_code}: {exc.message})")
        return None


async def seed() -> None:
    client = _require_sandbox()
    state: dict[str, Any] = _load_state()
    print("Seeding sandbox data...")

    async with client:
        tax = await _try(
            "tax rate", client.post("/tax_rates", json={"name": "Seed Tax", "rate": 825000})
        )
        if tax:
            state["tax_rate_id"] = tax["id"]

        cat = await _try("category", client.post("/categories", json={"name": "Seed Drinks"}))
        if cat:
            state["category_id"] = cat["id"]

        mg = await _try(
            "modifier group", client.post("/modifier_groups", json={"name": "Seed Size"})
        )
        if mg:
            state["modifier_group_id"] = mg["id"]
            mod = await _try(
                "modifier",
                client.post(
                    f"/modifier_groups/{mg['id']}/modifiers",
                    json={"name": "Large", "price": 50},
                ),
            )
            if mod:
                state["modifier_id"] = mod["id"]

        emp = await _try(
            "employee",
            client.post("/employees", json={"name": "Seed Employee", "role": "EMPLOYEE"}),
        )
        if emp:
            state["employee_id"] = emp["id"]
            # Shifts: best-effort — clock-in via the shifts sub-resource may be
            # unsupported on sandbox; failure is fine (list_shifts still returns []).
            shift = await _try(
                "shift (clock-in)",
                client.post(f"/employees/{emp['id']}/shifts", json={}),
            )
            if shift and shift.get("id"):
                state["shift_id"] = shift["id"]

        # Items + an order with repeated line items so get_top_items has a winner.
        item_ids: list[str] = []
        for name, price in [("Seed Latte", 500), ("Seed Muffin", 300)]:
            item = await _try(f"item {name}", client.post("/items", json={"name": name, "price": price}))
            if item:
                item_ids.append(item["id"])
        state["item_ids"] = item_ids

        order = await _try("order", client.post("/orders", json={"state": "open"}))
        if order:
            state["order_id"] = order["id"]
            # 2x Latte + 1x Muffin → Latte is the top item by units.
            plan = [item_ids[0]] * 2 + ([item_ids[1]] if len(item_ids) > 1 else [])
            for iid in plan:
                await _try(
                    f"line item {iid}",
                    client.post(f"/orders/{order['id']}/line_items", json={"item": {"id": iid}}),
                )

    _save_state(state)
    print(f"\nSaved created IDs to {STATE_FILE.name}. Run `verify` next, then `cleanup`.")


async def verify() -> None:
    client = _require_sandbox()
    from clover_mcp.tools.employees import (
        list_active_shifts,
        list_employees,
        list_shifts,
    )
    from clover_mcp.tools.inventory import list_categories, list_modifiers, list_taxes
    from clover_mcp.tools.merchant import list_devices
    from clover_mcp.tools.reporting import get_top_items

    async def ok(coro: Any) -> bool:
        """True if the tool call returned a well-shaped result. The response is
        consumed here and never returned/stored — so no value derived from it
        (which may carry PII) can reach a log sink."""
        try:
            return isinstance(await coro, (dict, list))
        except Exception:  # noqa: BLE001 — any failure is a failed check
            return False

    print("Verifying v1.1 read tools against live sandbox:\n")
    async with client:
        # Run each call, keeping only a (constant label, plain bool) pair. The
        # coroutine is never co-located with the label in a container, so its
        # taint can't flow to the print below.
        results: list[tuple[str, bool]] = [
            ("list_taxes", await ok(list_taxes(client))),
            ("list_categories", await ok(list_categories(client))),
            ("list_modifiers", await ok(list_modifiers(client))),
            ("list_employees", await ok(list_employees(client))),
            ("list_shifts", await ok(list_shifts(client))),
            ("list_active_shifts", await ok(list_active_shifts(client))),
            ("list_devices", await ok(list_devices(client))),
            ("get_top_items", await ok(get_top_items(client))),
        ]

    for label, passed in results:
        print(f"  {'✓' if passed else '✗'} {label}")
    n_pass = sum(1 for _, p in results if p)
    print(f"\n{n_pass}/{len(results)} v1.1 read tools returned a well-shaped result.")


async def cleanup() -> None:
    client = _require_sandbox()
    state = _load_state()
    if not state:
        print("Nothing recorded — nothing to clean up.")
        return
    print("Deleting seeded objects...")

    async with client:
        # Orders/items first (line items go with the order), then catalog, then employee.
        order_paths: list[str] = []
        if state.get("order_id"):
            order_paths.append(f"/orders/{state['order_id']}")
        for iid in state.get("item_ids", []):
            order_paths.append(f"/items/{iid}")
        rest = [
            f"/modifier_groups/{state['modifier_group_id']}" if state.get("modifier_group_id") else None,
            f"/categories/{state['category_id']}" if state.get("category_id") else None,
            f"/tax_rates/{state['tax_rate_id']}" if state.get("tax_rate_id") else None,
            f"/employees/{state['employee_id']}" if state.get("employee_id") else None,
        ]
        for path in [*order_paths, *[p for p in rest if p]]:
            await _try(f"delete {path}", client.delete(path))

    STATE_FILE.unlink(missing_ok=True)
    print(f"\nRemoved {STATE_FILE.name}. Cleanup complete.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    fn = {"seed": seed, "verify": verify, "cleanup": cleanup}.get(mode)
    if fn is None:
        sys.exit(f"Unknown mode {mode!r}. Use: seed | verify | cleanup")
    asyncio.run(fn())


if __name__ == "__main__":
    main()
