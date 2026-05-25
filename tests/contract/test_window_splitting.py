"""Contract tests: 90-day window splitting and ms timestamp conversion."""

from datetime import date

import pytest

from clover_mcp.windowing import date_to_ms, split_window


def test_single_chunk_within_90_days() -> None:
    chunks = split_window(date(2024, 1, 1), date(2024, 3, 1))
    assert len(chunks) == 1
    assert chunks[0] == (date(2024, 1, 1), date(2024, 3, 1))


def test_exactly_90_days_is_one_chunk() -> None:
    chunks = split_window(date(2024, 1, 1), date(2024, 3, 30))
    assert len(chunks) == 1


def test_91_days_splits_into_two_chunks() -> None:
    chunks = split_window(date(2024, 1, 1), date(2024, 4, 1))
    assert len(chunks) == 2
    # Chunks are contiguous
    assert chunks[0][1].toordinal() + 1 == chunks[1][0].toordinal()


def test_full_year_covers_all_days() -> None:
    start = date(2023, 1, 1)
    end = date(2023, 12, 31)
    chunks = split_window(start, end)
    # Reconstruct all covered dates
    covered: set[date] = set()
    for s, e in chunks:
        d = s
        while d <= e:
            covered.add(d)
            from datetime import timedelta

            d += timedelta(days=1)
    expected = set()
    d = start
    while d <= end:
        expected.add(d)
        from datetime import timedelta

        d += timedelta(days=1)
    assert covered == expected


def test_same_day_is_one_chunk() -> None:
    chunks = split_window(date(2024, 6, 1), date(2024, 6, 1))
    assert chunks == [(date(2024, 6, 1), date(2024, 6, 1))]


def test_inverted_range_raises() -> None:
    with pytest.raises(ValueError, match="must be"):
        split_window(date(2024, 6, 2), date(2024, 6, 1))


def test_date_to_ms_utc_midnight() -> None:
    ts = date_to_ms(date(2024, 1, 1))
    # 2024-01-01 00:00:00 UTC = 1704067200000 ms
    assert ts == 1704067200000


def test_date_to_ms_end_of_day() -> None:
    ts = date_to_ms(date(2024, 1, 1), end_of_day=True)
    # Should be the last ms of the day
    assert ts > date_to_ms(date(2024, 1, 1))
    assert ts < date_to_ms(date(2024, 1, 2))
