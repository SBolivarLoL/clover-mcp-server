"""v2 remote/hosted plumbing: layer-1 OAuth (resource server), multi-merchant.

This is the glue around FastMCP's built-in auth. FastMCP acts as an OAuth 2.1
*resource server*: it validates bearer JWTs against an external Authorization
Server (the operator's IdP) and auto-serves Protected Resource Metadata
(RFC 9728). We never see user credentials and issue no tokens ourselves.

In multi-merchant mode each request's validated token carries the Clover
merchant id (in a configurable claim); we look that merchant's Clover
credentials up in a per-merchant store and build a request-scoped client.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
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
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[config.auth_issuer],
        base_url=config.public_url,
        scopes_supported=scopes,
        resource_name="Clover POS MCP",
    )


class MerchantStore:
    """Read-only view of per-merchant Clover credentials, keyed by merchant id.

    JSON shape: ``{ "<merchantId>": {"access_token", "refresh_token",
    "oauth_client_id"?, "oauth_client_secret"?, "auth_mode"?, "region"?,
    "sandbox"?}, ... }``.

    ponytail: a flat JSON file is the laziest store that works for a handful of
    merchants. Swap this class for a DB/secret-manager lookup when you outgrow
    it — the rest of the code only calls .get().
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, merchant_id: str) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
        except Exception:
            return None
        entry = data.get(merchant_id) if isinstance(data, dict) else None
        return entry if isinstance(entry, dict) else None


def extract_merchant_id(claims: dict[str, Any] | None, subject: str | None, claim_name: str) -> str:
    """Pick the Clover merchant id from a validated token's claims.

    Prefers the configured claim, falls back to the token subject. Raises if the
    token identifies no merchant — never default to some other merchant's data.
    """
    merchant_id = (claims or {}).get(claim_name) or subject
    if not merchant_id:
        raise PermissionError(
            f"Authenticated token carries no merchant id (claim {claim_name!r} / subject). "
            "The IdP must put the Clover merchant id in the token."
        )
    return str(merchant_id)


def merchant_id_from_request(config: Config) -> str:
    """Resolve the merchant id for the current authenticated request."""
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    if token is None:  # pragma: no cover — auth middleware should guarantee a token
        raise PermissionError("No authenticated token on request.")
    return extract_merchant_id(
        getattr(token, "claims", None), getattr(token, "subject", None), config.merchant_claim
    )


def config_for_merchant(base: Config, merchant_id: str) -> Config:
    """Build a request-scoped Config for one merchant from the merchant store."""
    creds = MerchantStore(base.merchant_store).get(merchant_id)
    if not creds:
        raise PermissionError(f"Merchant {merchant_id!r} is not provisioned in the merchant store.")
    # Rotated refresh tokens persist to a per-merchant token store so single-use
    # rotation stays isolated between merchants.
    token_store = base.merchant_store.parent / f"tokens-{merchant_id}.json"
    return dataclasses.replace(
        base,
        merchant_id=merchant_id,
        access_token=str(creds.get("access_token", "")),
        refresh_token=str(creds.get("refresh_token", "")),
        oauth_client_id=str(creds.get("oauth_client_id", base.oauth_client_id)),
        oauth_client_secret=str(creds.get("oauth_client_secret", base.oauth_client_secret)),
        auth_mode=str(creds.get("auth_mode", "oauth_refresh")),
        region=str(creds.get("region", base.region)),
        sandbox=bool(creds.get("sandbox", base.sandbox)),
        token_store=token_store,
        multi_merchant=False,  # the per-merchant config is single-merchant
    )
