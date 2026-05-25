"""Money and time formatting helpers.

Currency: amounts are stored as integer cents in Clover (e.g. 1050 = $10.50).
Timezone: Clover timestamps are Unix ms UTC; merchant's local TZ is a separate field.
"""

from __future__ import annotations

from datetime import UTC, datetime

_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$",
    "BRL": "R$",
    "MXN": "MX$",
    "ARS": "AR$",
}


def format_money(cents: int, currency: str) -> str:
    """Format an integer cent value as a human-readable currency string.

    Does not default to USD — currency must be supplied (from merchant info).
    """
    symbol = _CURRENCY_SYMBOLS.get(currency.upper(), currency.upper() + " ")
    dollars = cents / 100
    return f"{symbol}{dollars:,.2f}"


def ms_to_utc_iso(ts_ms: int) -> str:
    """Convert a Clover Unix millisecond timestamp to an ISO-8601 UTC string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    return dt.isoformat()


def ms_to_local_iso(ts_ms: int, tz_name: str) -> str:
    """Convert a Clover Unix millisecond timestamp to ISO-8601 in the merchant's timezone.

    Falls back to UTC if the timezone name is unrecognised.
    """
    import zoneinfo

    dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        return dt_utc.astimezone(tz).isoformat()
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return dt_utc.isoformat()
