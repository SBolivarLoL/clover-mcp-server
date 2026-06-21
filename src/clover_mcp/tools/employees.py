"""Tools: list_employees, get_employee, list_shifts, list_active_shifts.

All require EMPLOYEES_R. Shapers drop PIN fields (shape_employee). Shifts live
under /employees/{id}/shifts in the Clover v3 API, so the merchant-wide listings
iterate employees and aggregate.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.shaping import shape_employee, shape_shift
from clover_mcp.windowing import date_to_ms, split_window


def _today_utc() -> date:
    return datetime.now(tz=UTC).date()


def _parse_date(value: str, param_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{param_name} must be an ISO-8601 date (YYYY-MM-DD), got {value!r}"
        ) from exc


async def list_employees(
    client: CloverClient,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a page of employees. PIN fields are never returned.

    Requires EMPLOYEES_R.
    """
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    body = await client.get("/employees", limit=limit, offset=offset)
    elements: list[dict[str, Any]] = body.get("elements", [])
    return {
        "employees": [shape_employee(el) for el in elements],
        "count": len(elements),
        "offset": offset,
        "limit": limit,
    }


async def get_employee(client: CloverClient, employee_id: str) -> dict[str, Any]:
    """Return a single employee by ID. PIN fields are never returned.

    Requires EMPLOYEES_R.
    """
    if not employee_id or not employee_id.strip():
        raise ValueError("employee_id must not be empty")
    raw = await client.get(f"/employees/{employee_id}")
    return shape_employee(raw)


async def _shifts_for_employee(
    client: CloverClient, employee_id: str, ts_filters: list[str]
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"filter": ts_filters} if ts_filters else {}
    out: list[dict[str, Any]] = []
    async for raw in client.iterate(f"/employees/{employee_id}/shifts", limit=100, **params):
        out.append(shape_shift(raw))
    return out


async def list_shifts(
    client: CloverClient,
    employee_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """List shifts, optionally filtered by employee and/or a date window.

    Without `employee_id`, iterates all employees and aggregates their shifts
    (one extra request per employee — fine for a single small-business merchant).
    Date filtering uses 90-day windowing on the shift `inTime`.

    Requires EMPLOYEES_R.
    """
    ts_filters: list[str] = []
    if date_from or date_to:
        today = _today_utc()
        d_from = _parse_date(date_from, "date_from") if date_from else today
        d_to = _parse_date(date_to, "date_to") if date_to else today
        if d_from > d_to:
            raise ValueError(f"date_from ({d_from}) must be ≤ date_to ({d_to})")
        # Single window is enough for the filter strings; Clover ANDs repeated filters.
        # ponytail: shifts span days, not the 90-day cap of orders/payments — one
        # createdTime/inTime range covers any realistic query; split_window kept for parity.
        chunks = split_window(d_from, d_to)
        ts_from = date_to_ms(chunks[0][0], end_of_day=False)
        ts_to = date_to_ms(chunks[-1][1], end_of_day=True)
        ts_filters = [f"inTime>={ts_from}", f"inTime<={ts_to}"]

    if employee_id:
        shifts = await _shifts_for_employee(client, employee_id, ts_filters)
    else:
        shifts = []
        async for emp in client.iterate("/employees", limit=100):
            shifts.extend(await _shifts_for_employee(client, emp["id"], ts_filters))

    return {"shifts": shifts, "count": len(shifts)}


async def list_active_shifts(client: CloverClient) -> dict[str, Any]:
    """Return shifts that are currently open (clocked in, not yet clocked out).

    A shift is active when it has no `outTime`. Iterates all employees.

    Requires EMPLOYEES_R.
    """
    active: list[dict[str, Any]] = []
    async for emp in client.iterate("/employees", limit=100):
        for shift in await _shifts_for_employee(client, emp["id"], []):
            if not shift.get("outTime"):
                active.append(shift)
    return {"shifts": active, "count": len(active)}
