"""Contract tests: region → base URL resolution.

These cover every cell in the region × sandbox matrix defined in config.py.
If Clover changes their hostnames, this test will catch it at the config layer
before any tool code is touched.
"""

import pytest

from clover_mcp.config import resolve_base_url


@pytest.mark.parametrize(
    "region, sandbox, expected",
    [
        ("na", False, "https://api.clover.com"),
        ("eu", False, "https://api.eu.clover.com"),
        ("la", False, "https://api.la.clover.com"),
        ("na", True, "https://apisandbox.dev.clover.com"),
        ("eu", True, "https://apisandbox.dev.clover.com"),
        ("la", True, "https://apisandbox.dev.clover.com"),
    ],
)
def test_resolve_base_url(region: str, sandbox: bool, expected: str) -> None:
    assert resolve_base_url(region, sandbox) == expected


def test_unknown_region_raises() -> None:
    with pytest.raises(ValueError, match="Unknown CLOVER_REGION"):
        resolve_base_url("xx", False)


def test_region_case_insensitive() -> None:
    assert resolve_base_url("NA", False) == "https://api.clover.com"
    assert resolve_base_url("EU", True) == "https://apisandbox.dev.clover.com"
