"""Shared pytest fixtures: mock config and CloverClient backed by respx."""

from __future__ import annotations

import pytest
import respx
import httpx

from clover_mcp.config import Config
from clover_mcp.client import CloverClient


TEST_MERCHANT_ID = "TESTMERCHANT1"
TEST_TOKEN = "test_access_token"
TEST_BASE = "https://apisandbox.dev.clover.com"


@pytest.fixture
def test_config() -> Config:
    from pathlib import Path
    return Config(
        merchant_id=TEST_MERCHANT_ID,
        access_token=TEST_TOKEN,
        region="na",
        sandbox=True,
        auth_mode="token",
        refresh_token="",
        oauth_client_id="",
        oauth_client_secret="",
        token_store=Path("/tmp/clover-mcp-test-tokens.json"),
    )


@pytest.fixture
def mock_http():
    """Activate respx mock router for httpx calls during the test."""
    with respx.mock(base_url=TEST_BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(test_config: Config, mock_http: respx.Router) -> CloverClient:
    """A CloverClient wired to the test config and respx mock router."""
    return CloverClient(test_config)
