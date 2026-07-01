# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — observability
- **Audit logging** — every write emits a structured JSON line to stderr
  (`method`, `path`, `status`, `merchant`; no bodies or secrets). On by default;
  disable with `CLOVER_AUDIT_LOG=false`.
- **OpenTelemetry tracing (optional)** — every Clover HTTP call is wrapped in a
  span. Install the `otel` extra and configure an OTLP exporter for real
  distributed traces; without it, tracing is a zero-cost no-op.
- **Latency logging** — `CLOVER_LATENCY_LOG=true` emits per-request `latency_ms`
  lines to stderr.

## [0.6.0] — 2026-07-01
Three read tools closing gaps found in a full Clover-API surface review, plus a
defense-in-depth auth warning and a documented path from sandbox to production.

### Added — reads (sandbox-verified)
- **`list_discounts`** (INVENTORY_R) — the merchant's discount catalogue.
- **`list_tip_suggestions`** (MERCHANT_R) — tip-suggestion presets (percentage or flat).
- **`get_default_service_charge`** (MERCHANT_R) — default service-charge config;
  closes the `get_sales_summary` service-charge gap (orders expose only a percentage).

### Security
- **RFC 8707 audience binding** — http mode now logs a startup WARNING when
  `CLOVER_AUTH_AUDIENCE` is unset, so bearer tokens get bound to this resource.

### Docs
- **docs/DEPLOY.md** — "Path to production" (sandbox → real merchants via the Clover
  Developer Program) with a per-scope permission-justification table.
- **docs/clover-app-submission.md** — app listing copy, permission justifications,
  and a functional-video script for Clover app approval.
- **docs/research/** — MCP best-practices + full Clover-API-surface research and a
  consolidated gap analysis.

## [0.5.0] — 2026-06-25
Multi-tenant security hardening — the gate to hosting real merchants. The
forwarded-header trust boundary is now fail-closed (verified live: the
FastMCP Cloud / Horizon gateway strips client-supplied identity headers), with
per-tenant credential isolation and a full hardening checklist in docs/SECURITY.md.

### Security — multi-tenant hardening (REQUIRED before hosting real merchants)
- **Forwarded-header identity is now fail-closed.** Routing tenants by a gateway
  header (`CLOVER_TENANT_HEADER`, e.g. `horizon-user-email`) is a spoofing risk
  unless the gateway strips client-supplied copies. Without
  `CLOVER_TRUST_IDENTITY_HEADER=true`, the server **boots but refuses every data
  call** (`request_tenant_key` fails closed) and logs a startup warning — it does
  not hard-fail, so `whoami` stays reachable to run the header-spoofing test that
  the opt-in requires. `whoami` surfaces the trust state and the test procedure.
  (Existing header-based multi-tenant deploys must set this flag after verifying
  their gateway — until then they serve no data.)
- **Per-tenant credential isolation.** Tenant entries can reference each token by
  its own env var (`access_token_env` / `refresh_token_env`) instead of inlining
  every merchant's plaintext token in one `CLOVER_TENANTS_JSON` blob — so each
  secret can be injected individually from a secret manager. Missing reference →
  fail closed.
- **docs/SECURITY.md** — vulnerability reporting + the full multi-tenant hardening
  checklist (spoofing test, prefer-JWT-over-header, encryption-at-rest, one-deploy-
  per-merchant, custodial legal duties).

## [0.4.0] — 2026-06-24
Agent-ready release: the server now spans all four MCP capability layers — tools
(reads + guarded writes), AI/LLM tools via client sampling, predefined prompts,
and elicitation/resources — so a merchant can run their Clover business by
conversation. 44 tools, 6 prompts, 1 resource.

### Added — Layer 4 capabilities (resource + logging)
- **`clover://capabilities`** MCP resource: a read-only cheat-sheet (tools split
  read/write, prompts, guardrails, hard exclusions) built live from the registry
  so an agent can ground itself in one fetch without spending tool calls.
- **Progress logging**: `get_sales_summary` emits per-window log lines via
  `ctx.info` when a query spans more than one 90-day window (guarded — never
  fails if the client doesn't support logging).

### Added — Layer 1 guarded writes + Layer 4 elicitation
- Five guarded write tools (all validate → dry_run preview → **confirm before
  writing**): `create_category`, `create_item`, `create_order`, `add_line_item`,
  `update_customer`. Sandbox-verified live end-to-end 2026-06-24.
- **Confirmation gate** (`confirm.py`): writes confirm via MCP **elicitation**
  (`ctx.elicit`) — the MCP-native guardrail — or an explicit `confirm=True`
  override. Fail-closed: with neither an accepted elicitation nor `confirm=True`,
  the write is refused (`confirmation_required`).
- Still excluded by design: payment capture, refunds, voids, charge creation,
  record deletes, gateway config. `update_customer` uses POST (Clover returns 405
  on PUT/PATCH); email/phone are sub-resources and are not modified here.

### Added — Layer 3 prompts (MCP prompts capability)
- Six predefined `@mcp.prompt` workflows that drive the existing read tools so a
  merchant's agent runs common jobs out of the box (no LLM call inside a prompt):
  `daily_briefing`, `weekly_sales_report`, `inventory_health_check`,
  `end_of_day_closeout`, `customer_lookup(query)`, `monthly_tax_summary(month)`.

### Added — Layer 2 AI/LLM tools (MCP sampling)
- Five tools that reason over Clover data via `ctx.sample()` — the **server holds
  no LLM key** and makes no paid API call; it asks the connected client's model.
  `summarize_sales`, `suggest_item_categories`, `inventory_reorder_suggestions`,
  `detect_sales_anomalies`, `draft_customer_message(intent)`. All read-only, with
  bounded prompts and a graceful fallback (data + note) when the client can't sample.

### Added — Layer 1 expanded reads (API coverage)
- **`list_order_types`**, **`list_opening_hours`**, **`list_cash_events`** (MERCHANT_R):
  reference data agents ask about ("are we open?", cash-drawer log).
- **`list_attributes`** (item variant axes + options) and **`list_tags`** (INVENTORY_R).
- `get_order` now expands **discounts** and per-line-item **modifications/discounts**,
  and surfaces the line item's catalog `item_id`.

## [0.3.0] — 2026-06-24
### Fixed
- `get_order` now returns the order's **payments** (allowlist-shaped via
  `shape_payment`, so card data is still stripped). The tool expanded `payments`
  and its docstring promised a "payment summary", but `shape_order` silently
  dropped them — the field never reached the caller.

### Added — expanded read surface (API coverage)
- **`list_refunds`** (PAYMENTS_R): list refunds in a date window. Clover refunds
  are separate objects with a positive `amount` (cents); `transactionInfo` is
  dropped by the shaper.
- **`list_tenders`** (MERCHANT_R): list the merchant's tender types (cash,
  credit, custom payment methods).
- **`list_roles`** (EMPLOYEES_R): list employee roles (name + system role).
- **`get_merchant_properties`** (MERCHANT_R): merchant POS settings (currency,
  tips, stock tracking, closeout, locale, support contacts). The shaper allowlist
  deliberately excludes the banking/account fields in the raw payload.
- **`list_item_groups`** (INVENTORY_R): list item groups (item variant sets).

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

[Unreleased]: https://github.com/SBolivarLoL/clover-mcp-server/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/SBolivarLoL/clover-mcp-server/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/SBolivarLoL/clover-mcp-server/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SBolivarLoL/clover-mcp-server/compare/v0.2.0...v0.3.0
[0.1.0]: https://github.com/SBolivarLoL/clover-mcp-server/releases/tag/v0.1.0
