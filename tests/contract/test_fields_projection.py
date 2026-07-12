"""Contract tests: `project()` fields projection — a narrowing-only operation.

`project` intersects a caller-requested field list with already-shaped rows.
This is a security invariant: it must be able to DROP keys but never ADD or
un-redact one, so a caller can never use `fields` to widen past the shaping
allowlist (e.g. request "cardNumber" and get it back).
"""

from clover_mcp.shaping import project


def test_project_keeps_only_requested_fields() -> None:
    rows = [
        {"id": "1", "total": 100, "note": "a"},
        {"id": "2", "total": 200, "note": "b"},
    ]
    result = project(rows, ["id", "total"])
    assert result == [{"id": "1", "total": 100}, {"id": "2", "total": 200}]


def test_project_none_returns_rows_unchanged() -> None:
    rows = [{"id": "1", "total": 100}]
    assert project(rows, None) == rows


def test_project_empty_list_returns_rows_unchanged() -> None:
    rows = [{"id": "1", "total": 100}]
    assert project(rows, []) == rows


def test_project_cannot_widen_past_shaped_rows() -> None:
    """Security invariant: requesting a field absent from the shaped row (e.g. a
    banned field that was already stripped upstream) must NOT cause it to appear."""
    rows = [{"id": "1"}]
    result = project(rows, ["id", "cardNumber"])
    assert result == [{"id": "1"}]
    assert "cardNumber" not in result[0]


def test_project_preserves_row_order() -> None:
    rows = [{"id": "3"}, {"id": "1"}, {"id": "2"}]
    result = project(rows, ["id"])
    assert [r["id"] for r in result] == ["3", "1", "2"]
