#!/usr/bin/env python
"""Benchmark + correctness eval for clover-mcp against a live Clover sandbox.

Three phases, each printed as a JSON block + human summary:

  1. Correctness — every read tool is called once; the shaped result is scanned
     for banned keys (the PII/card/PIN leak gate) and checked for its expected
     top-level key. This is the eval's pass/fail signal.
  2. Latency — one representative read is timed over N iterations, throttled to
     stay well under Clover's ~16 req/s, reporting p50/p95/max/mean (ms).
  3. Load — a bounded concurrent burst, reporting throughput (req/s) and error
     rate; surfaces rate-limit (429) behaviour under pressure.

Read-only: GET calls only, never writes. Throttled to be a good API citizen.

Usage:
    uv run python scripts/benchmark.py                 # full run, human + JSON
    uv run python scripts/benchmark.py --json out.json # also write raw results
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.config import load_config
from clover_mcp.errors import CloverAPIError
from clover_mcp.tools import customers as C
from clover_mcp.tools import employees as E
from clover_mcp.tools import inventory as I
from clover_mcp.tools import merchant as M
from clover_mcp.tools import orders as O
from clover_mcp.tools import reporting as R

# The leak gate — mirrors tests/contract/test_shaping_allowlist.py BANNED_KEYS
# plus merchant banking fields. If any appears in a live response, correctness fails.
BANNED_KEYS = {
    "pin",
    "unhashedPin",
    "cards",
    "cardTransaction",
    "href",
    "token",
    "pan",
    "abaAccountNumber",
    "ddaAccountNumber",
}

# Throttle: sleep between latency samples so we stay well under ~16 req/s.
_THROTTLE_S = 0.15
_LATENCY_ITERS = 20
_LOAD_TOTAL = 30
_LOAD_CONCURRENCY = 5


def _find_banned(data: Any, path: str = "") -> list[str]:
    """Return dotted paths of any banned key found anywhere in the payload."""
    hits: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in BANNED_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(_find_banned(value, f"{path}.{key}"))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            hits.extend(_find_banned(item, f"{path}[{idx}]"))
    return hits


def _pct(values: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0,1])."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


async def _correctness(client: CloverClient) -> dict[str, Any]:
    """Call each read tool once; check top-level key present + no banned keys."""
    # (name, callable, expected_top_key). expected_top_key="" → object-shaped result.
    cases: list[tuple[str, Callable[[], Awaitable[Any]], str]] = [
        ("get_merchant_info", lambda: M.get_merchant_info(client), ""),
        ("get_merchant_properties", lambda: M.get_merchant_properties(client), ""),
        ("list_devices", lambda: M.list_devices(client), "devices"),
        ("list_tenders", lambda: M.list_tenders(client), "tenders"),
        ("list_order_types", lambda: M.list_order_types(client), "order_types"),
        ("list_opening_hours", lambda: M.list_opening_hours(client), "opening_hours"),
        ("list_cash_events", lambda: M.list_cash_events(client), "cash_events"),
        ("list_tip_suggestions", lambda: M.list_tip_suggestions(client), "tip_suggestions"),
        ("get_default_service_charge", lambda: M.get_default_service_charge(client), ""),
        ("list_items", lambda: I.list_items(client), "items"),
        ("list_low_stock_items", lambda: I.list_low_stock_items(client), "items"),
        ("list_categories", lambda: I.list_categories(client), "categories"),
        ("list_modifiers", lambda: I.list_modifiers(client), "modifier_groups"),
        ("list_item_groups", lambda: I.list_item_groups(client), "item_groups"),
        ("list_attributes", lambda: I.list_attributes(client), "attributes"),
        ("list_tags", lambda: I.list_tags(client), "tags"),
        # NOTE: list_taxes returns key `tax_rates`, not `taxes` — a naming
        # inconsistency vs the list_<noun>→<noun> convention (documented in eval.md).
        ("list_taxes", lambda: I.list_taxes(client), "tax_rates"),
        ("list_discounts", lambda: I.list_discounts(client), "discounts"),
        ("get_sales_summary", lambda: R.get_sales_summary(client), ""),
        ("list_payments", lambda: R.list_payments(client), ""),
        ("list_refunds", lambda: R.list_refunds(client), ""),
        ("get_top_items", lambda: R.get_top_items(client), ""),
        ("list_orders", lambda: O.list_orders(client), ""),
        ("list_open_orders", lambda: O.list_open_orders(client), ""),
        ("search_customers", lambda: C.search_customers(client), "customers"),
        ("list_employees", lambda: E.list_employees(client), "employees"),
        ("list_roles", lambda: E.list_roles(client), "roles"),
        ("list_active_shifts", lambda: E.list_active_shifts(client), "shifts"),
    ]
    results: list[dict[str, Any]] = []
    for name, call, top_key in cases:
        row: dict[str, Any] = {"tool": name}
        try:
            out = await call()
            banned = _find_banned(out)
            key_ok = (top_key == "") or (isinstance(out, dict) and top_key in out)
            row["ok"] = key_ok and not banned
            if banned:
                row["leaked"] = banned
            if not key_ok:
                row["missing_key"] = top_key
        except CloverAPIError as exc:
            row["ok"] = False
            row["error"] = f"{exc.status_code}: {exc.message[:60]}"
        except Exception as exc:  # noqa: BLE001 - benchmark records, never crashes
            row["ok"] = False
            row["error"] = f"{type(exc).__name__}: {str(exc)[:60]}"
        results.append(row)
        await asyncio.sleep(_THROTTLE_S)
    passed = sum(1 for r in results if r["ok"])
    return {"passed": passed, "total": len(results), "cases": results}


async def _latency(client: CloverClient) -> dict[str, Any]:
    """Time a single non-cached read over N throttled iterations."""
    samples: list[float] = []
    errors = 0
    for _ in range(_LATENCY_ITERS):
        start = time.perf_counter()
        try:
            await client.get("/tenders", limit=100)
            samples.append((time.perf_counter() - start) * 1000)
        except Exception:  # noqa: BLE001
            errors += 1
        await asyncio.sleep(_THROTTLE_S)
    return {
        "endpoint": "GET /tenders",
        "iterations": _LATENCY_ITERS,
        "errors": errors,
        "p50_ms": _pct(samples, 0.50),
        "p95_ms": _pct(samples, 0.95),
        "max_ms": round(max(samples), 2) if samples else 0.0,
        "mean_ms": round(sum(samples) / len(samples), 2) if samples else 0.0,
    }


async def _load(client: CloverClient) -> dict[str, Any]:
    """Bounded concurrent burst — throughput + error rate under pressure."""
    sem = asyncio.Semaphore(_LOAD_CONCURRENCY)
    errors = {"count": 0, "429": 0}

    async def one() -> None:
        async with sem:
            try:
                await client.get("/tenders", limit=100)
            except CloverAPIError as exc:
                errors["count"] += 1
                if exc.status_code == 429:
                    errors["429"] += 1
            except Exception:  # noqa: BLE001
                errors["count"] += 1

    start = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(_LOAD_TOTAL)))
    elapsed = time.perf_counter() - start
    return {
        "total_requests": _LOAD_TOTAL,
        "concurrency": _LOAD_CONCURRENCY,
        "elapsed_s": round(elapsed, 2),
        "throughput_rps": round(_LOAD_TOTAL / elapsed, 1) if elapsed else 0.0,
        "errors": errors["count"],
        "rate_limited_429": errors["429"],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write raw results to this path")
    args = parser.parse_args()

    config = load_config()
    if not config.sandbox:
        print(
            "Refusing to benchmark against a NON-sandbox config. Set CLOVER_SANDBOX=true.",
            file=sys.stderr,
        )
        sys.exit(2)

    client = CloverClient(config)
    print("Running clover-mcp benchmark against the sandbox (read-only, throttled)…\n")

    correctness = await _correctness(client)
    latency = await _latency(client)
    load = await _load(client)
    await client.close()

    results = {"correctness": correctness, "latency": latency, "load": load}

    print(f"CORRECTNESS  {correctness['passed']}/{correctness['total']} tools passed")
    for row in correctness["cases"]:
        if not row["ok"]:
            print(
                f"  FAIL {row['tool']}: {row.get('error') or row.get('leaked') or row.get('missing_key')}"
            )
    print(f"\nLATENCY ({latency['endpoint']}, n={latency['iterations']})")
    print(
        f"  p50={latency['p50_ms']}ms  p95={latency['p95_ms']}ms  max={latency['max_ms']}ms  mean={latency['mean_ms']}ms"
    )
    print(f"\nLOAD  {load['total_requests']} reqs @ concurrency {load['concurrency']}")
    print(
        f"  {load['throughput_rps']} req/s  errors={load['errors']}  429s={load['rate_limited_429']}"
    )

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nRaw results → {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
