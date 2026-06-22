# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]
### Added — multi-tenant (v2 phase 2)
- Map each authenticated request to its own Clover merchant by token identity,
  so one deployment can serve many merchants. The tenant map loads from
  `CLOVER_TENANTS_JSON` (an env var — persists on platforms with ephemeral disk
  like FastMCP Cloud) overlaid on the optional `CLOVER_MERCHANT_STORE` file.
  Each tenant entry holds a merchant id + permanent token (no refresh-to-disk).
- `CLOVER_TENANT_CLAIM` selects which validated-token claim keys the tenant map
  (defaults to the `email` claim, then the subject — right for Horizon's user auth).
- New **`whoami`** tool: returns the authenticated identity, available claim
  *names* (no values), scopes, and whether a tenant is mapped — so you can
  discover what identity your platform provides and key the map correctly.
- `CLOVER_MULTI_MERCHANT=true` no longer requires `CLOVER_TRANSPORT=http`; it
  works under a managed platform's auth too, and fails closed (no tenant → no
  data) if no authenticated identity reaches the server.
- docs/DEPLOY.md: step-by-step multi-tenant setup on Horizon.

## [0.2.0] — 2026-06-22
### Changed
- Startup permission self-check is now **non-fatal**: it logs warnings instead of
  calling `sys.exit(1)` on a bad token / missing scope / config error, so a hosted
  platform's pre-flight can always start the server (errors surface as 401/403 on
  the first tool call). Required for FastMCP Cloud / Horizon deploys.
- Docs: clarified FastMCP Cloud (managed auth — use `server.py:mcp`, no IdP) vs
  self-host (`server.py:create_server` with your own IdP). The earlier guidance
  to use `create_server` / `CLOVER_TRANSPORT=http` on Horizon was wrong and made
  the server fail to start.

### Added — v2 remote/hosted (phase 1, opt-in; stdio single-merchant unchanged)
- **HTTP transport**: `CLOVER_TRANSPORT=http` runs a network-reachable Streamable
  HTTP server (host/port/path configurable).
- **Layer-1 OAuth (resource server)**: validates IdP-issued JWTs via FastMCP
  `RemoteAuthProvider` + `JWTVerifier`, and publishes Protected Resource Metadata
  (RFC 9728) at `/.well-known/oauth-protected-resource/mcp`. The server **refuses
  to start** in http mode unless `CLOVER_AUTH_JWKS_URI`, `CLOVER_AUTH_ISSUER`, and
  `CLOVER_PUBLIC_URL` are set — a remote MCP server must not run unauthenticated.
- **Multi-merchant** (`CLOVER_MULTI_MERCHANT=true`): each request is routed to the
  merchant named in a validated token claim (`CLOVER_MERCHANT_CLAIM`, default
  `clover_merchant_id`); per-merchant Clover credentials come from a JSON merchant
  store, with isolated single-use refresh-token rotation per merchant.
- `docs/DEPLOY.md` covers hosting, IdP setup, env vars, and the merchant store.
- Dependency floor raised to `fastmcp>=3.4` (the auth APIs above).

## [0.1.5] — 2026-06-21
### Added
- v1.1 read tools (9), all read-only, allowlist-shaped, annotated, tested:
  - `list_employees`, `get_employee`, `list_shifts`, `list_active_shifts`
    (`EMPLOYEES_R` — PINs never returned; shifts aggregate across employees).
  - `list_categories`, `list_modifiers`, `list_taxes` (`INVENTORY_R`).
  - `list_devices` (`MERCHANT_R`).
  - `get_top_items` (`ORDERS_R`) — best-sellers by units in a date window.
- `EMPLOYEES_R` startup permission probe. It is **optional**: a 403 only warns
  (employee/shift tools are opt-in) and does not block server startup.
### Notes
- The new endpoints are implemented from the Clover API docs and unit-tested
  against mocked responses; live sandbox shape-verification is still owed and
  tracked in [docs/endpoints.md](docs/endpoints.md) (status 🟡).

## [0.1.4] — 2026-06-21
### Security
- `scripts/get_sandbox_token.py` no longer prints access/refresh token values
  (CodeQL `py/clear-text-logging-sensitive-data`); they're written only to the
  0600 token store.
- `oauth_refresh` mode now reads access/refresh tokens from the token store, so
  they never need to be pasted into `.env`. `CLOVER_ACCESS_TOKEN` /
  `CLOVER_REFRESH_TOKEN` env vars are optional when the store has them.
### Fixed
- `get_sales_summary` refund totals now come from the dedicated `/refunds`
  endpoint (Clover refunds are separate objects with a positive amount) instead
  of the incorrect `amount<0` payment heuristic. `net_sales = gross - refunds`.
### Removed
- `service_charges_collected` from `get_sales_summary`. Clover exposes an order's
  service charge only as a percentage (no computed amount), so the old field was
  always 0; the paid amount is already included in `gross_sales`. This also drops
  the `ORDERS_R` requirement from `get_sales_summary`.

## [0.1.3] — 2026-06-21
### Added
- Listed on the official MCP Registry (`server.json` + GitHub-OIDC publish step
  in the release workflow). PyPI README carries the `mcp-name` ownership marker.

## [0.1.2] — 2026-06-21
### Fixed
- `__version__` is now derived from installed package metadata
  (`importlib.metadata`) instead of a hardcoded constant, so it can never drift
  from `pyproject.toml` again. (0.1.1 shipped reporting `0.1.0`.)

## [0.1.1] — 2026-06-21
### Added
- Legal & disclaimer section: nominative trademark / not-affiliated notice,
  AS-IS no-warranty statement, and operator responsibilities (Clover terms,
  data-protection, least-privilege tokens).
- PyPI publishing from the release workflow via trusted publishing (OIDC).
### Fixed
- Release workflow attaches only the wheel + sdist (glob narrowed from `dist/*`).

## [0.1.0] — 2026-06-21 (GitHub release)
### Added
- 11 read tools: `get_merchant_info`, `get_sales_summary`, `list_payments`,
  `list_orders`, `get_order`, `list_open_orders`, `list_items`, `get_item`,
  `list_low_stock_items`, `search_customers`, `get_customer`.
- 3 safe write tools: `create_customer` (idempotency dup-check, `dry_run`),
  `set_item_price_cents`, `set_item_stock_quantity` (optimistic-lock pre-check,
  bounds, `dry_run`, absolute set — not a delta).
- Two auth modes: static `token` and `oauth_refresh` (single-use refresh-token
  rotation, 0600 token store, refresh-on-401).
- MCP tool annotations (`readOnlyHint` / `destructiveHint` / `idempotentHint` /
  `openWorldHint`) on all 14 tools.
- Allowlist response shaping (no card / PII / PIN leakage), 90-day windowing,
  currency-aware money formatting, startup permission self-check.
- Sandbox-verified endpoint audit ([docs/endpoints.md](docs/endpoints.md)).

### Out of scope (by design)
- Refunds, voids, payment capture, charge creation, record deletes.
- Employee/shift tools (planned v1.1), multi-merchant hosted mode + MCP-level
  OAuth 2.1 (planned v2).

[Unreleased]: https://github.com/SBolivarLoL/clover-mcp-server/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SBolivarLoL/clover-mcp-server/releases/tag/v0.1.0
