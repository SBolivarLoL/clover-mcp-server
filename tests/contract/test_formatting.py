"""Contract tests: money formatting and timestamp conversion."""

from clover_mcp.formatting import format_money, ms_to_local_iso, ms_to_utc_iso


def test_format_money_usd() -> None:
    assert format_money(1050, "USD") == "$10.50"


def test_format_money_eur() -> None:
    assert format_money(999, "EUR") == "€9.99"


def test_format_money_brl() -> None:
    assert format_money(2000, "BRL") == "R$20.00"


def test_format_money_unknown_currency() -> None:
    result = format_money(500, "XYZ")
    assert "5.00" in result
    assert "XYZ" in result


def test_format_money_zero() -> None:
    assert format_money(0, "USD") == "$0.00"


def test_format_money_large() -> None:
    result = format_money(100_000_00, "USD")  # $100,000.00
    assert result == "$100,000.00"


def test_ms_to_utc_iso() -> None:
    # 2024-01-01 00:00:00 UTC
    result = ms_to_utc_iso(1704067200000)
    assert result.startswith("2024-01-01T00:00:00")
    assert result.endswith("+00:00") or result.endswith("Z") or "UTC" in result or "+00" in result


def test_ms_to_local_iso_new_york() -> None:
    # 2024-01-01 12:00:00 UTC → 07:00:00 EST
    result = ms_to_local_iso(1704110400000, "America/New_York")
    assert "2024-01-01" in result
    assert "07:00:00" in result


def test_ms_to_local_iso_unknown_tz_falls_back_to_utc() -> None:
    result = ms_to_local_iso(1704067200000, "Not/AReal_TZ")
    assert "2024-01-01" in result
