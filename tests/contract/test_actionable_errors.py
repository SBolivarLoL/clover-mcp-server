"""§1.4 actionable errors: a 404 on an id-bearing path names the failing input
and the read tool that lists valid ids, while keeping Clover's verbatim message."""

from __future__ import annotations

import httpx
import pytest

from clover_mcp.errors import CloverAPIError, raise_for_status


def _resp(status: int, path: str, message: str = "not found") -> httpx.Response:
    return httpx.Response(
        status,
        json={"message": message},
        request=httpx.Request("GET", f"https://x{path}"),
    )


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("/items/ABC", "list_items"),
        ("/orders/XYZ", "list_orders"),
        ("/customers/C1", "search_customers"),
        ("/categories/K1", "list_categories"),
        ("/employees/E1", "list_employees"),
        ("/orders/O1/line_items/L1", "get_order"),
    ],
)
def test_404_carries_remedy_and_verbatim(path: str, needle: str) -> None:
    with pytest.raises(CloverAPIError) as exc:
        raise_for_status(_resp(404, path, "Item not found"), context=f"GET {path}")
    msg = exc.value.message
    assert needle in msg  # actionable next step
    assert "Item not found" in msg  # Clover's verbatim message preserved (CLAUDE.md rule)


def test_404_unmapped_path_has_no_remedy_but_still_verbatim() -> None:
    with pytest.raises(CloverAPIError) as exc:
        raise_for_status(_resp(404, "/taxes/T1", "gone"), context="GET /taxes/T1")
    assert "—" not in exc.value.message  # no spurious hint for unmapped resources
    assert "gone" in exc.value.message
