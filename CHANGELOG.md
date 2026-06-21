# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.3] — unreleased
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
