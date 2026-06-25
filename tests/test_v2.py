"""Tests for v2 remote/hosted plumbing: transport + auth config, the http
security gate, the merchant store, and per-request merchant resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clover_mcp.config import Config, load_config
from clover_mcp.remote import (
    build_auth_provider,
    load_tenants,
    tenant_config,
    tenant_key,
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
    "CLOVER_TENANT_CLAIM",
    "CLOVER_TENANTS_JSON",
    "CLOVER_TENANT_HEADER",
    "CLOVER_TRUST_IDENTITY_HEADER",
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


def test_multi_merchant_allowed_on_default_transport(clean_env: pytest.MonkeyPatch) -> None:
    # Managed platforms (Horizon) provide auth/transport themselves, so
    # multi_merchant must be allowed with CLOVER_TRANSPORT unset.
    clean_env.setenv("CLOVER_MULTI_MERCHANT", "true")
    cfg = load_config()
    assert cfg.multi_merchant is True
    assert cfg.transport == "stdio"


def test_multi_merchant_drops_merchant_id_requirement(clean_env: pytest.MonkeyPatch) -> None:
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


# ── multi-tenant resolution ───────────────────────────────────────────────────


def test_tenant_key_uses_configured_claim() -> None:
    assert (
        tenant_key({"clover_merchant_id": "M9", "email": "x@y.z"}, "sub1", "clover_merchant_id")
        == "M9"
    )


def test_tenant_key_defaults_to_email_then_subject() -> None:
    assert tenant_key({"email": "a@b.c"}, "sub1", "") == "a@b.c"
    assert tenant_key({}, "SUBONLY", "") == "SUBONLY"


def test_tenant_key_raises_when_absent() -> None:
    with pytest.raises(PermissionError, match="no tenant identity"):
        tenant_key({}, None, "")


def test_load_tenants_from_env_overrides_file(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "merchants.json"
    store.write_text(json.dumps({"a@b.c": {"merchant_id": "FILE"}}))
    clean_env.setenv("CLOVER_TENANTS_JSON", json.dumps({"a@b.c": {"merchant_id": "ENV"}}))
    base = _base_config(merchant_store=store)
    tenants = load_tenants(base)
    assert tenants["a@b.c"]["merchant_id"] == "ENV"  # env wins


def test_load_tenants_bad_env_json_raises(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_TENANTS_JSON", "{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        load_tenants(_base_config())


def test_tenant_config_builds_scoped_single_merchant() -> None:
    tenants = {"a@b.c": {"merchant_id": "M1", "access_token": "tok1", "sandbox": True}}
    scoped = tenant_config(_base_config(region="na"), tenants, "a@b.c")
    assert scoped.merchant_id == "M1"
    assert scoped.access_token == "tok1"
    assert scoped.auth_mode == "token"  # tenants default to permanent tokens
    assert scoped.sandbox is True
    assert scoped.multi_merchant is False
    # per-tenant token store isolation (no cross-tenant clobber on oauth_refresh)
    assert scoped.token_store.name == "tokens-a_b_c.json"


def test_tenant_config_unprovisioned_raises() -> None:
    with pytest.raises(PermissionError, match="No Clover merchant provisioned"):
        tenant_config(_base_config(), {}, "ghost@nowhere")


def test_request_tenant_key_from_header(monkeypatch: pytest.MonkeyPatch) -> None:
    import clover_mcp.remote as remote

    monkeypatch.setattr(remote, "_request_headers", lambda: {"x-forwarded-email": "u@store.com"})
    cfg = _base_config(tenant_header="x-forwarded-email", trust_identity_header=True)
    assert remote.request_tenant_key(cfg) == "u@store.com"


def test_request_tenant_key_missing_header_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import clover_mcp.remote as remote

    monkeypatch.setattr(remote, "_request_headers", lambda: {})
    cfg = _base_config(tenant_header="x-forwarded-email", trust_identity_header=True)
    with pytest.raises(PermissionError, match="no 'x-forwarded-email' header"):
        remote.request_tenant_key(cfg)


def test_request_tenant_key_untrusted_header_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY: header routing without the trust opt-in must refuse, even if the
    header is present — never trust a spoofable header by default."""
    import clover_mcp.remote as remote

    monkeypatch.setattr(remote, "_request_headers", lambda: {"x-forwarded-email": "attacker@evil"})
    cfg = _base_config(tenant_header="x-forwarded-email", trust_identity_header=False)
    with pytest.raises(PermissionError, match="CLOVER_TRUST_IDENTITY_HEADER is not set"):
        remote.request_tenant_key(cfg)


def test_config_boots_with_untrusted_header(clean_env: pytest.MonkeyPatch) -> None:
    """SECURITY: header routing without the trust opt-in must still BOOT (so the
    whoami diagnostic works for the spoofing test) — it is NOT a hard startup
    error. The fail-closed enforcement is at request time (see
    test_request_tenant_key_untrusted_header_fails_closed)."""
    clean_env.setenv("CLOVER_MULTI_MERCHANT", "true")
    clean_env.setenv("CLOVER_TENANT_HEADER", "horizon-user-email")
    cfg = load_config()  # must not raise
    assert cfg.tenant_header == "horizon-user-email"
    assert cfg.trust_identity_header is False


def test_config_allows_header_routing_with_trust(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLOVER_MULTI_MERCHANT", "true")
    clean_env.setenv("CLOVER_TENANT_HEADER", "horizon-user-email")
    clean_env.setenv("CLOVER_TRUST_IDENTITY_HEADER", "true")
    cfg = load_config()
    assert cfg.tenant_header == "horizon-user-email"
    assert cfg.trust_identity_header is True


def test_tenant_config_reads_token_from_env_reference(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Per-tenant credential isolation: an entry can reference its token via its own
    env var instead of inlining it in the shared CLOVER_TENANTS_JSON blob."""
    clean_env.setenv("CLOVER_TOKEN_FOR_M1", "secret-token-from-env")
    tenants = {"a@b.c": {"merchant_id": "M1", "access_token_env": "CLOVER_TOKEN_FOR_M1"}}
    scoped = tenant_config(_base_config(), tenants, "a@b.c")
    assert scoped.access_token == "secret-token-from-env"


def test_tenant_config_missing_env_reference_fails_closed(
    clean_env: pytest.MonkeyPatch,
) -> None:
    tenants = {"a@b.c": {"merchant_id": "M1", "access_token_env": "CLOVER_TOKEN_MISSING"}}
    with pytest.raises(PermissionError, match="unset/empty"):
        tenant_config(_base_config(), tenants, "a@b.c")
