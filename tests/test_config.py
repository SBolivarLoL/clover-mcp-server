"""Tests for load_config validation, incl. oauth_refresh tokens from the store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clover_mcp.config import load_config

_CLOVER_VARS = [
    "CLOVER_MERCHANT_ID",
    "CLOVER_ACCESS_TOKEN",
    "CLOVER_REGION",
    "CLOVER_SANDBOX",
    "CLOVER_AUTH_MODE",
    "CLOVER_REFRESH_TOKEN",
    "CLOVER_OAUTH_CLIENT_ID",
    "CLOVER_OAUTH_CLIENT_SECRET",
    "CLOVER_TOKEN_STORE",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Clear all CLOVER_* env vars (the real .env may be loaded at import)."""
    for v in _CLOVER_VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_token_mode_requires_access_token(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_AUTH_MODE", "token")
    with pytest.raises(RuntimeError, match="CLOVER_ACCESS_TOKEN"):
        load_config()


def test_token_mode_ok(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_AUTH_MODE", "token")
    clean_env.setenv("CLOVER_ACCESS_TOKEN", "tok")
    cfg = load_config()
    assert cfg.auth_mode == "token"
    assert cfg.access_token == "tok"


def test_oauth_refresh_missing_everything_errors(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_AUTH_MODE", "oauth_refresh")
    clean_env.setenv("CLOVER_TOKEN_STORE", str(tmp_path / "absent.json"))
    with pytest.raises(RuntimeError) as exc:
        load_config()
    msg = str(exc.value)
    assert "CLOVER_ACCESS_TOKEN" in msg
    assert "CLOVER_REFRESH_TOKEN" in msg
    assert "CLOVER_OAUTH_CLIENT_ID" in msg


def test_oauth_refresh_tokens_from_store(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """access/refresh may come from the token store instead of env."""
    store = tmp_path / "tokens.json"
    store.write_text(json.dumps({"access_token": "a", "refresh_token": "r"}))
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_AUTH_MODE", "oauth_refresh")
    clean_env.setenv("CLOVER_TOKEN_STORE", str(store))
    clean_env.setenv("CLOVER_OAUTH_CLIENT_ID", "cid")
    clean_env.setenv("CLOVER_OAUTH_CLIENT_SECRET", "csec")
    # No CLOVER_ACCESS_TOKEN / CLOVER_REFRESH_TOKEN in env — must still succeed.
    cfg = load_config()
    assert cfg.auth_mode == "oauth_refresh"


def test_oauth_refresh_requires_client_id(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    store.write_text(json.dumps({"access_token": "a", "refresh_token": "r"}))
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_AUTH_MODE", "oauth_refresh")
    clean_env.setenv("CLOVER_TOKEN_STORE", str(store))
    clean_env.setenv("CLOVER_OAUTH_CLIENT_SECRET", "csec")
    with pytest.raises(RuntimeError, match="CLOVER_OAUTH_CLIENT_ID"):
        load_config()
