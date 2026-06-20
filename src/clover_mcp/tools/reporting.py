"""Tools: get_sales_summary, list_payments.

Both tools use 90-day windowing so arbitrary date ranges work transparently.
Payments are filtered to result=SUCCESS for counts; voids and refunds are
reported separately per the plan's Sales Semantics spec.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from clover_mcp.client import CloverClient
from clover_mcp.formatting import format_money
from clover_mcp.shaping import shape_payment
from clover_mcp.windowing import date_to_ms, split_window

_DEFAULT_LIMIT = 50


def _today_utc() -> date:
    return datetime.now(tz=UTC).date()


def _parse_date(value: str, param_name: str) -> date:
    """Parse an ISO-8601 date string (YYYY-MM-DD); raise ValueError with context."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{param_name} must be an ISO-8601 date (YYYY-MM-DD), got {value!r}"
        ) from exc


def _money(cents: int, currency: str) -> dict[str, Any]:
    return {"amount": cents, "formatted": format_money(cents, currency)}


async def get_sales_summary(
    client: CloverClient,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Return an aggregated sales summary for the given date window.

    Defaults to today (UTC) when no dates are supplied. Uses 90-day chunking
    so multi-month or full-year queries work transparently.

    Rules applied:
    - Only result=SUCCESS payments are counted in payment_count and gross_sales.
    - Voids and refunds are tallied separately (refund_count, void_count,
      refund_amount) — they are NOT silently netted into payment_count.
    - Tips and taxes are broken out as their own line items.
    - Service charges are summed from orders (not payments, where Clover does not
      expose them) and reported as service_charges_collected. Requires ORDERS_R.
    - Offline payments are included; a warning flag is set if any are present.
    - Currency is fetched from the merchant record — never defaulted to USD.

    Requires PAYMENTS_R and ORDERS_R.
    This tool does NOT support payment capture, refund, or void actions.
    """
    today = _today_utc()
    d_from = _parse_date(date_from, "date_from") if date_from else today
    d_to = _parse_date(date_to, "date_to") if date_to else today

    if d_from > d_to:
        raise ValueError(f"date_from ({d_from}) must be ≤ date_to ({d_to})")

    currency = await client.merchant_currency()
    timezone = await client.merchant_timezone()

    gross_cents = 0
    tip_cents = 0
    tax_cents = 0
    service_charge_cents = 0
    payment_count = 0
    refund_count = 0
    void_count = 0
    refund_cents = 0
    has_offline = False
    by_tender: dict[str, int] = {}

    # Collect all SUCCESS payments across windowed chunks
    for chunk_start, chunk_end in split_window(d_from, d_to):
        ts_from = date_to_ms(chunk_start, end_of_day=False)
        ts_to = date_to_ms(chunk_end, end_of_day=True)

        params: dict[str, Any] = {
            "filter": [
                f"createdTime>={ts_from}",
                f"createdTime<={ts_to}",
                "result=SUCCESS",
            ],
        }

        async for raw in client.iterate("/payments", limit=100, **params):
            # Counts only SUCCESS payments — FAIL/AUTH/PRE_AUTH excluded by filter
            gross_cents += raw.get("amount", 0)
            tip_cents += raw.get("tipAmount", 0)
            tax_cents += raw.get("taxAmount", 0)
            payment_count += 1

            if raw.get("offline"):
                has_offline = True

            tender_label = "UNKNOWN"
            if isinstance(raw.get("tender"), dict):
                tender_label = raw["tender"].get("label") or raw["tender"].get("id") or "UNKNOWN"
            by_tender[tender_label] = by_tender.get(tender_label, 0) + raw.get("amount", 0)

    # Collect voided payments in the same windows
    for chunk_start, chunk_end in split_window(d_from, d_to):
        ts_from = date_to_ms(chunk_start, end_of_day=False)
        ts_to = date_to_ms(chunk_end, end_of_day=True)

        void_params: dict[str, Any] = {
            "filter": [
                f"createdTime>={ts_from}",
                f"createdTime<={ts_to}",
                "voided=true",
            ],
        }

        async for _ in client.iterate("/payments", limit=100, **void_params):
            void_count += 1

    # ponytail: refunds via the amount<0 SUCCESS heuristic — unverified against a
    # sandbox with no transaction data. Upgrade path if it proves wrong in prod:
    # query the dedicated GET /v3/merchants/{mId}/refunds endpoint instead.
    for chunk_start, chunk_end in split_window(d_from, d_to):
        ts_from = date_to_ms(chunk_start, end_of_day=False)
        ts_to = date_to_ms(chunk_end, end_of_day=True)

        refund_params: dict[str, Any] = {
            "filter": [
                f"createdTime>={ts_from}",
                f"createdTime<={ts_to}",
                "result=SUCCESS",
                "amount<0",
            ],
        }

        async for raw in client.iterate("/payments", limit=100, **refund_params):
            refund_count += 1
            refund_cents += raw.get("amount", 0)  # negative value

    # Service charges live on the order, not the payment — Clover does not expose
    # them on /payments. Sum serviceCharge.amount across orders in the window.
    for chunk_start, chunk_end in split_window(d_from, d_to):
        ts_from = date_to_ms(chunk_start, end_of_day=False)
        ts_to = date_to_ms(chunk_end, end_of_day=True)

        order_params: dict[str, Any] = {
            "filter": [
                f"createdTime>={ts_from}",
                f"createdTime<={ts_to}",
            ],
            "expand": "serviceCharge",
        }

        async for raw in client.iterate("/orders", limit=100, **order_params):
            sc = raw.get("serviceCharge")
            if isinstance(sc, dict):
                service_charge_cents += sc.get("amount") or 0

    # net_sales: gross minus absolute refund amount
    net_cents = gross_cents + refund_cents  # refund_cents is negative

    avg_ticket = (gross_cents // payment_count) if payment_count > 0 else 0

    by_tender_fmt = {label: _money(amount, currency) for label, amount in by_tender.items()}

    result: dict[str, Any] = {
        "window": {
            "from": d_from.isoformat(),
            "to": d_to.isoformat(),
            "timezone": timezone,
        },
        "currency": currency,
        "gross_sales": _money(gross_cents, currency),
        "net_sales": _money(net_cents, currency),
        "tax_collected": _money(tax_cents, currency),
        "tips_collected": _money(tip_cents, currency),
        "service_charges_collected": _money(service_charge_cents, currency),
        "refund_amount": _money(abs(refund_cents), currency),
        "payment_count": payment_count,
        "refund_count": refund_count,
        "void_count": void_count,
        "average_ticket": _money(avg_ticket, currency),
        "by_tender": by_tender_fmt,
    }

    if has_offline:
        result["note"] = "includes offline payments pending sync"

    return result


async def list_payments(
    client: CloverClient,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """List payments within an optional date window.

    Defaults to today (UTC) when no dates are supplied. Uses 90-day chunking
    so multi-month queries work transparently. Results are limited to `limit`
    total items (default 50, max 200). Only result=SUCCESS payments are
    returned; use get_sales_summary for void/refund counts.

    Allowlisted fields only — card transaction details are never included.
    This tool does NOT support payment capture, refund, or void actions.
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")

    today = _today_utc()
    d_from = _parse_date(date_from, "date_from") if date_from else today
    d_to = _parse_date(date_to, "date_to") if date_to else today

    if d_from > d_to:
        raise ValueError(f"date_from ({d_from}) must be ≤ date_to ({d_to})")

    results: list[dict[str, Any]] = []

    for chunk_start, chunk_end in split_window(d_from, d_to):
        if len(results) >= limit:
            break
        ts_from = date_to_ms(chunk_start, end_of_day=False)
        ts_to = date_to_ms(chunk_end, end_of_day=True)

        params: dict[str, Any] = {
            "filter": [
                f"createdTime>={ts_from}",
                f"createdTime<={ts_to}",
                "result=SUCCESS",
            ],
        }

        chunk_limit = min(100, limit - len(results))
        async for raw in client.iterate("/payments", limit=chunk_limit, **params):
            results.append(shape_payment(raw))
            if len(results) >= limit:
                break

    return results
