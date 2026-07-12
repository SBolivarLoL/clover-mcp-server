"""Shared pytest fixtures: mock config and CloverClient backed by respx."""

from __future__ import annotations

import os

import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.config import Config

TEST_MERCHANT_ID = "TESTMERCHANT1"
TEST_TOKEN = "test_access_token"
TEST_BASE = "https://apisandbox.dev.clover.com"


@pytest.fixture(autouse=True)
def _scrub_clover_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may see real CLOVER_* credentials from the developer's shell or
    .env — scrub them before every test. Tests that need config set their own.

    load_config() calls load_dotenv() at call time, so we also neutralize it here;
    otherwise the developer's real .env would repopulate the vars mid-test."""
    monkeypatch.setattr("clover_mcp.config.load_dotenv", lambda *a, **k: False)
    for key in list(os.environ):
        if key.startswith("CLOVER_"):
            monkeypatch.delenv(key, raising=False)


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
