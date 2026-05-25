"""Configuration loading and region → base-URL resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REGION_PROD: dict[str, str] = {
    "na": "https://api.clover.com",
    "eu": "https://api.eu.clover.com",
    "la": "https://api.la.clover.com",
}
_SANDBOX_URL = "https://apisandbox.dev.clover.com"


def resolve_base_url(region: str, sandbox: bool) -> str:
    """Return the Clover REST base URL for the given region and environment.

    All non-US regions share the same sandbox URL — Clover provides one
    unified sandbox regardless of merchant's production region.
    """
    if sandbox:
        return _SANDBOX_URL
    try:
        return _REGION_PROD[region.lower()]
    except KeyError:
        valid = ", ".join(_REGION_PROD)
        raise ValueError(f"Unknown CLOVER_REGION {region!r}. Valid values: {valid}") from None


@dataclass(frozen=True)
class Config:
    merchant_id: str
    access_token: str
    region: str
    sandbox: bool
    auth_mode: str  # "token" | "oauth_refresh"
    # OAuth refresh fields (required only in oauth_refresh mode)
    refresh_token: str
    oauth_client_id: str
    oauth_client_secret: str
    token_store: Path
    base_url: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", resolve_base_url(self.region, self.sandbox))

    @property
    def merchant_base(self) -> str:
        return f"{self.base_url}/v3/merchants/{self.merchant_id}"


def load_config() -> Config:
    """Load and validate configuration from environment variables."""
    errors: list[str] = []

    def require(name: str) -> str:
        val = os.getenv(name, "").strip()
        if not val:
            errors.append(f"  • {name} is required but not set")
        return val

    def optional(name: str, default: str = "") -> str:
        return os.getenv(name, default).strip()

    merchant_id = require("CLOVER_MERCHANT_ID")
    access_token = require("CLOVER_ACCESS_TOKEN")
    region = optional("CLOVER_REGION", "na")
    sandbox = optional("CLOVER_SANDBOX", "false").lower() in ("1", "true", "yes")
    auth_mode = optional("CLOVER_AUTH_MODE", "token").lower()

    if auth_mode not in ("token", "oauth_refresh"):
        errors.append(f"  • CLOVER_AUTH_MODE must be 'token' or 'oauth_refresh', got {auth_mode!r}")

    refresh_token = optional("CLOVER_REFRESH_TOKEN")
    oauth_client_id = optional("CLOVER_OAUTH_CLIENT_ID")
    oauth_client_secret = optional("CLOVER_OAUTH_CLIENT_SECRET")

    if auth_mode == "oauth_refresh":
        for name, val in [
            ("CLOVER_REFRESH_TOKEN", refresh_token),
            ("CLOVER_OAUTH_CLIENT_ID", oauth_client_id),
            ("CLOVER_OAUTH_CLIENT_SECRET", oauth_client_secret),
        ]:
            if not val:
                errors.append(f"  • {name} is required when CLOVER_AUTH_MODE=oauth_refresh")

    token_store = Path(
        optional("CLOVER_TOKEN_STORE", "~/.config/clover-mcp/tokens.json")
    ).expanduser()

    # validate region (triggers ValueError we convert to config error)
    try:
        resolve_base_url(region, sandbox)
    except ValueError as exc:
        errors.append(f"  • {exc}")

    if errors:
        msg = "clover-mcp configuration errors:\n" + "\n".join(errors)
        raise RuntimeError(msg)

    return Config(
        merchant_id=merchant_id,
        access_token=access_token,
        region=region,
        sandbox=sandbox,
        auth_mode=auth_mode,
        refresh_token=refresh_token,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
        token_store=token_store,
    )
