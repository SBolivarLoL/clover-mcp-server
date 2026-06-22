"""v2 remote/hosted plumbing: layer-1 OAuth (resource server), multi-merchant.

This is the glue around FastMCP's built-in auth. FastMCP acts as an OAuth 2.1
*resource server*: it validates bearer JWTs against an external Authorization
Server (the operator's IdP) and auto-serves Protected Resource Metadata
(RFC 9728). We never see user credentials and issue no tokens ourselves.

In multi-tenant mode each request is mapped to one Clover merchant by the
authenticated identity in its validated token (for a managed platform like
FastMCP Cloud / Horizon that's the user's email/subject, not a merchant id).
That identity keys a tenant map (env blob or file) holding the merchant's
credentials, from which we build a request-scoped client.
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any

from clover_mcp.config import Config


def build_auth_provider(config: Config) -> Any | None:
    """Return a FastMCP auth provider for http mode, or None for stdio.

    Security gate: a network-reachable MCP server MUST authenticate. We act as an
    OAuth 2.1 *resource server* — validating JWTs against the operator's IdP and
    publishing Protected Resource Metadata (RFC 9728) so MCP clients can discover
    where to get a token. All three of jwks_uri (validation), issuer (the AS to
    advertise), and public_url (this server's resource identity) are required.
    """
    if config.transport != "http":
        return None

    required = {
        "CLOVER_AUTH_JWKS_URI": config.auth_jwks_uri,
        "CLOVER_AUTH_ISSUER": config.auth_issuer,
        "CLOVER_PUBLIC_URL": config.public_url,
    }
    missing = [name for name, val in required.items() if not val]
    if missing:
        raise RuntimeError(
            "CLOVER_TRANSPORT=http requires layer-1 OAuth (resource server). Missing: "
            + ", ".join(missing)
            + ". Refusing to serve an unauthenticated remote MCP server."
        )

    # Imported lazily so stdio installs never pay for the auth stack.
    from fastmcp.server.auth import RemoteAuthProvider
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    scopes = list(config.auth_scopes) or None
    verifier = JWTVerifier(
        jwks_uri=config.auth_jwks_uri,
        issuer=config.auth_issuer,
        audience=config.auth_audience or None,
        required_scopes=scopes,
    )
    # Pydantic coerces the issuer str into AnyHttpUrl at runtime; a list[Any]
    # local keeps mypy happy without a type-ignore.
    authorization_servers: list[Any] = [config.auth_issuer]
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=authorization_servers,
        base_url=config.public_url,
        scopes_supported=scopes,
        resource_name="Clover POS MCP",
    )


# ── Multi-tenant (phase 2) ────────────────────────────────────────────────────
# A "tenant" is one authenticated principal mapped to one Clover merchant + its
# credentials. The tenant map is keyed by a value pulled from the request's
# validated token — for FastMCP Cloud / Horizon that's the *user* identity
# (email / subject), since the platform authenticates org users, not merchants.
#
# The map is loaded from (in increasing precedence):
#   1. CLOVER_MERCHANT_STORE — a JSON file (self-host, where disk persists)
#   2. CLOVER_TENANTS_JSON   — a JSON blob in an env var (Horizon: env survives
#      restarts even though the filesystem does not)
# Each entry: {"merchant_id", "access_token", "auth_mode"?, "refresh_token"?,
#              "region"?, "sandbox"?}. Use a permanent Clover API token
# (auth_mode "token", the default here) so no refresh-to-disk is needed.


def load_tenants(config: Config) -> dict[str, Any]:
    """Load the tenant map (file store overlaid by the env blob)."""
    tenants: dict[str, Any] = {}

    if config.merchant_store and config.merchant_store.exists():
        try:
            data = json.loads(config.merchant_store.read_text())
            if isinstance(data, dict):
                tenants.update(data)
        except Exception:  # noqa: BLE001 — a broken file shouldn't crash the server
            pass

    raw = os.getenv("CLOVER_TENANTS_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CLOVER_TENANTS_JSON is not valid JSON: {exc}") from exc
        if isinstance(data, dict):
            tenants.update(data)

    return tenants


def tenant_key(claims: dict[str, Any] | None, subject: str | None, claim_name: str) -> str:
    """The identity value that selects a tenant.

    If ``claim_name`` is set, use that claim; otherwise fall back to the ``email``
    claim and then the token subject. Raises if the token identifies nobody —
    never default to another tenant's data.
    """
    claims = claims or {}
    value = claims.get(claim_name) if claim_name else (claims.get("email") or subject)
    if not value:
        which = repr(claim_name) if claim_name else "email/subject"
        raise PermissionError(
            f"Authenticated token carries no tenant identity ({which}). "
            "Configure CLOVER_TENANT_CLAIM to a claim your IdP/platform actually sets."
        )
    return str(value)


def tenant_config(base: Config, tenants: dict[str, Any], key: str) -> Config:
    """Build a request-scoped single-merchant Config from the tenant entry."""
    entry = tenants.get(key)
    if not isinstance(entry, dict) or not entry.get("merchant_id"):
        raise PermissionError(
            f"No Clover merchant provisioned for {key!r}. Add it to CLOVER_TENANTS_JSON."
        )
    return dataclasses.replace(
        base,
        merchant_id=str(entry["merchant_id"]),
        access_token=str(entry.get("access_token", "")),
        auth_mode=str(entry.get("auth_mode", "token")),
        refresh_token=str(entry.get("refresh_token", "")),
        oauth_client_id=str(entry.get("oauth_client_id", base.oauth_client_id)),
        oauth_client_secret=str(entry.get("oauth_client_secret", base.oauth_client_secret)),
        region=str(entry.get("region", base.region)),
        sandbox=bool(entry.get("sandbox", base.sandbox)),
        multi_merchant=False,  # the per-tenant config is single-merchant
    )


# HTTP headers a gateway commonly forwards the authenticated identity in. Used
# only to surface candidate values in `whoami`; the actual one is configured via
# CLOVER_TENANT_HEADER once you see which your platform sends.
_IDENTITY_HEADERS = frozenset(
    {
        "x-forwarded-user",
        "x-forwarded-email",
        "x-forwarded-preferred-username",
        "x-auth-request-user",
        "x-auth-request-email",
        "x-auth-request-preferred-username",
        "x-authenticated-user",
        "x-authenticated-userid",
        "x-user",
        "x-user-id",
        "x-user-email",
        "remote-user",
        "x-remote-user",
        "x-ms-client-principal-name",
        "x-goog-authenticated-user-email",
        # FastMCP Cloud / Horizon gateway-injected identity
        "horizon-user-email",
        "horizon-user-id",
        "horizon-actor-email",
        "horizon-workos-user",
        "fastmcp-cloud-user",
        "fastmcp-cloud-actor",
    }
)


def _request_token() -> Any:
    from fastmcp.server.dependencies import get_access_token

    return get_access_token()


def _request_headers() -> dict[str, str]:
    from fastmcp.server.dependencies import get_http_headers

    return get_http_headers(include_all=True)


def request_tenant_key(config: Config) -> str:
    """Resolve the tenant identity for the current request.

    Two sources: an HTTP header (CLOVER_TENANT_HEADER — for gateway platforms like
    Horizon that authenticate at the edge and forward identity as a header), or a
    validated token claim (a custom IdP). Fails closed if neither yields anything.
    """
    if config.tenant_header:
        headers = _request_headers()
        value = headers.get(config.tenant_header) or headers.get(config.tenant_header.lower())
        if not value:
            raise PermissionError(
                f"Request has no {config.tenant_header!r} header to identify the tenant."
            )
        return str(value)

    token = _request_token()
    if token is None:
        raise PermissionError(
            "No authenticated identity on request: no validated token, and "
            "CLOVER_TENANT_HEADER is not set. Run `whoami` to see what your platform forwards."
        )
    return tenant_key(
        getattr(token, "claims", None), getattr(token, "subject", None), config.tenant_claim
    )


def auth_context(config: Config, tenants: dict[str, Any]) -> dict[str, Any]:
    """Non-secret view of the current request's auth, for the `whoami` tool.

    Returns the authenticated identity, the *names* of available claims (never
    their values), scopes, and whether a tenant is provisioned for it. This is
    how you discover what identity the platform (e.g. Horizon) actually provides
    so you can key CLOVER_TENANTS_JSON correctly.
    """
    headers = _request_headers()
    # Header NAMES are safe to surface; show VALUES only for known identity headers
    # (never authorization/cookie). This reveals what a gateway forwards.
    identity_headers = {k: v for k, v in headers.items() if k.lower() in _IDENTITY_HEADERS}
    token = _request_token()

    # Preview the exact resolution a tool would do (header source or token claim).
    try:
        key: str | None = request_tenant_key(config)
    except PermissionError:
        key = None

    out: dict[str, Any] = {
        "authenticated": token is not None,
        "tenant_count": len(tenants),
        "http_header_names": sorted(headers),
        "identity_headers": identity_headers,
        "tenant_key_source": config.tenant_header or config.tenant_claim or "email→subject",
        "resolved_tenant_key": key,
        "tenant_provisioned": bool(key and key in tenants),
    }

    if token is not None:
        claims = getattr(token, "claims", None) or {}
        out["subject"] = getattr(token, "subject", None)
        out["claim_keys"] = sorted(claims.keys())
        out["scopes"] = list(getattr(token, "scopes", None) or [])

    if key is None:
        out["note"] = (
            "No tenant identity resolved. Set CLOVER_TENANT_HEADER to the header that "
            "carries your identity (see identity_headers / http_header_names) — or "
            "CLOVER_TENANT_CLAIM if your platform forwards a validated token."
        )
    return out
