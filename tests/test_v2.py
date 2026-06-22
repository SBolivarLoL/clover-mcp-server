"""Tests for v2 remote/hosted plumbing: transport + auth config, the http
security gate, the merchant store, and per-request merchant resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clover_mcp.config import Config, load_config
from clover_mcp.remote import (
    MerchantStore,
    build_auth_provider,
    config_for_merchant,
    extract_merchant_id,
)

_VARS = [
    "CLOVER_MERCHANT_ID",
    "CLOVER_ACCESS_TOKEN",
    "CLOVER_REGION",
    "CLOVER_SANDBOX",
    "CLOVER_AUTH_MODE",
    "CLOVER_REFRESH_TOKEN",
    "CLOVER_OAUTH_CLIENT_ID",
    "CLOVER_OAUTH_CLIENT_SECRET",
    "CLOVER_TOKEN_STORE",
    "CLOVER_TRANSPORT",
    "CLOVER_MULTI_MERCHANT",
    "CLOVER_HTTP_HOST",
    "CLOVER_HTTP_PORT",
    "CLOVER_HTTP_PATH",
    "CLOVER_AUTH_ISSUER",
    "CLOVER_AUTH_JWKS_URI",
    "CLOVER_AUTH_AUDIENCE",
    "CLOVER_AUTH_SCOPES",
    "CLOVER_MERCHANT_CLAIM",
    "CLOVER_MERCHANT_STORE",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for v in _VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def _base_config(**over: object) -> Config:
    defaults: dict[str, object] = dict(
        merchant_id="",
        access_token="",
        region="na",
        sandbox=True,
        auth_mode="oauth_refresh",
        refresh_token="",
        oauth_client_id="cid",
        oauth_client_secret="csec",
        token_store=Path("/tmp/clover-mcp-test/tokens.json"),
    )
    defaults.update(over)
    return Config(**defaults)  # type: ignore[arg-type]


# ── config parsing ────────────────────────────────────────────────────────────


def test_transport_defaults_to_stdio(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_ACCESS_TOKEN", "tok")
    cfg = load_config()
    assert cfg.transport == "stdio"
    assert cfg.multi_merchant is False


def test_http_transport_parsed(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_ACCESS_TOKEN", "tok")
    clean_env.setenv("CLOVER_TRANSPORT", "http")
    clean_env.setenv("CLOVER_HTTP_PORT", "9000")
    cfg = load_config()
    assert cfg.transport == "http"
    assert cfg.http_port == 9000


def test_multi_merchant_requires_http(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MULTI_MERCHANT", "true")  # but transport stays stdio
    with pytest.raises(RuntimeError, match="requires CLOVER_TRANSPORT=http"):
        load_config()


def test_multi_merchant_drops_merchant_id_requirement(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_TRANSPORT", "http")
    clean_env.setenv("CLOVER_MULTI_MERCHANT", "true")
    # No CLOVER_MERCHANT_ID / CLOVER_ACCESS_TOKEN — must still load.
    cfg = load_config()
    assert cfg.multi_merchant is True
    assert cfg.merchant_id == ""


def test_auth_scopes_parsed(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_TRANSPORT", "http")
    clean_env.setenv("CLOVER_MULTI_MERCHANT", "true")
    clean_env.setenv("CLOVER_AUTH_SCOPES", "read, write  admin")
    cfg = load_config()
    assert cfg.auth_scopes == ("read", "write", "admin")


# ── auth provider security gate ───────────────────────────────────────────────


def test_auth_provider_none_for_stdio() -> None:
    assert build_auth_provider(_base_config(transport="stdio")) is None


def test_http_without_idp_is_refused() -> None:
    with pytest.raises(RuntimeError, match="Refusing to serve an unauthenticated"):
        build_auth_provider(_base_config(transport="http"))


def test_http_partial_idp_is_refused() -> None:
    # jwks present but no issuer/public_url → still refused, names what's missing.
    with pytest.raises(RuntimeError, match="CLOVER_PUBLIC_URL"):
        build_auth_provider(
            _base_config(transport="http", auth_jwks_uri="https://idp.example.com/jwks")
        )


def test_http_with_full_idp_builds_provider() -> None:
    provider = build_auth_provider(
        _base_config(
            transport="http",
            auth_jwks_uri="https://idp.example.com/.well-known/jwks.json",
            auth_issuer="https://idp.example.com/",
            auth_audience="clover-mcp",
            public_url="https://mcp.example.com",
        )
    )
    assert provider is not None


@pytest.mark.asyncio
async def test_create_server_fails_closed_without_idp(clean_env: pytest.MonkeyPatch) -> None:
    """The hosted factory must refuse to construct without an IdP, even if
    CLOVER_TRANSPORT isn't set — a managed deploy can't serve unauthenticated."""
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_ACCESS_TOKEN", "tok")
    from clover_mcp.server import create_server

    with pytest.raises(RuntimeError, match="Refusing to serve an unauthenticated"):
        await create_server()


@pytest.mark.asyncio
async def test_create_server_builds_authed_with_tools(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MERCHANT_ID", "M1")
    clean_env.setenv("CLOVER_ACCESS_TOKEN", "tok")
    clean_env.setenv("CLOVER_AUTH_JWKS_URI", "https://idp.example.com/.well-known/jwks.json")
    clean_env.setenv("CLOVER_AUTH_ISSUER", "https://idp.example.com/")
    clean_env.setenv("CLOVER_PUBLIC_URL", "https://clover.fastmcp.app")
    from clover_mcp.server import create_server

    server = await create_server()
    assert server.auth is not None
    # tools were copied from the module server
    assert await server.get_tool("get_merchant_info") is not None


def test_http_app_serves_protected_resource_metadata() -> None:
    """The provider must wire RFC 9728 Protected Resource Metadata into the app."""
    import fastmcp

    provider = build_auth_provider(
        _base_config(
            transport="http",
            auth_jwks_uri="https://idp.example.com/.well-known/jwks.json",
            auth_issuer="https://idp.example.com/",
            public_url="https://mcp.example.com",
        )
    )
    app = fastmcp.FastMCP("Clover POS", auth=provider).http_app(path="/mcp")
    paths = {str(getattr(r, "path", getattr(r, "path_format", ""))) for r in app.routes}
    assert any("oauth-protected-resource" in p for p in paths)


# ── merchant resolution ───────────────────────────────────────────────────────


def test_extract_merchant_id_prefers_claim() -> None:
    assert extract_merchant_id({"clover_merchant_id": "M9"}, "sub1", "clover_merchant_id") == "M9"


def test_extract_merchant_id_falls_back_to_subject() -> None:
    assert extract_merchant_id({}, "MSUB", "clover_merchant_id") == "MSUB"


def test_extract_merchant_id_raises_when_absent() -> None:
    with pytest.raises(PermissionError, match="no merchant id"):
        extract_merchant_id({}, None, "clover_merchant_id")


def test_merchant_store_get(tmp_path: Path) -> None:
    store_path = tmp_path / "merchants.json"
    store_path.write_text(json.dumps({"M1": {"access_token": "a", "refresh_token": "r"}}))
    store = MerchantStore(store_path)
    assert store.get("M1") == {"access_token": "a", "refresh_token": "r"}
    assert store.get("M2") is None


def test_config_for_merchant_builds_scoped_config(tmp_path: Path) -> None:
    store_path = tmp_path / "merchants.json"
    store_path.write_text(
        json.dumps({"M1": {"access_token": "a1", "refresh_token": "r1", "sandbox": True}})
    )
    base = _base_config(transport="http", multi_merchant=True, merchant_store=store_path)
    scoped = config_for_merchant(base, "M1")
    assert scoped.merchant_id == "M1"
    assert scoped.access_token == "a1"
    assert scoped.refresh_token == "r1"
    assert scoped.multi_merchant is False  # per-merchant config is single
    assert scoped.token_store == tmp_path / "tokens-M1.json"  # isolated rotation


def test_config_for_merchant_unprovisioned_raises(tmp_path: Path) -> None:
    base = _base_config(
        transport="http", multi_merchant=True, merchant_store=tmp_path / "absent.json"
    )
    with pytest.raises(PermissionError, match="not provisioned"):
        config_for_merchant(base, "GHOST")
