# Current state — what clover-mcp already has (v0.5.0)

Baseline inventory, captured from source. Used to mark "already have" in the
gap analysis. Generated as part of the research pass. **This is the pre-pass
baseline (44 tools); the pass added 3 → 47. See [gap-analysis.md](gap-analysis.md).**

## Tools (44)

### Reads (31)
| Tool | Resource | Notes |
|---|---|---|
| `whoami` | identity | multi-tenant diagnostic, no secrets |
| `get_merchant_info` | merchant | primes currency/timezone cache |
| `get_merchant_properties` | merchant props | banking fields stripped |
| `get_sales_summary` | payments+refunds | 90-day chunked aggregation |
| `list_payments` | payments | SUCCESS only, no card data |
| `list_refunds` | refunds | positive-amount objects |
| `list_tenders` | tenders | payment methods |
| `list_orders` | orders | date/state filter |
| `get_order` | order | expands lineItems + payments |
| `list_open_orders` | orders | state=open convenience |
| `list_order_types` | order types | Dine In / Take Out |
| `get_top_items` | orders | best-sellers by units |
| `list_items` | items | name/category filter, paginated |
| `get_item` | item | includes stock |
| `list_low_stock_items` | items | threshold scan |
| `list_categories` | categories | |
| `list_modifiers` | modifier groups | with modifiers |
| `list_item_groups` | item groups | variant sets |
| `list_attributes` | attributes | variant axes + options |
| `list_tags` | tags/labels | |
| `list_taxes` | tax rates | raw + computed percent |
| `list_devices` | devices | terminals |
| `list_opening_hours` | opening hours | per-day ranges |
| `list_cash_events` | cash events | drawer log |
| `list_employees` | employees | PINs never returned |
| `get_employee` | employee | PINs never returned |
| `list_shifts` | shifts | by employee/date |
| `list_active_shifts` | shifts | clocked-in |
| `list_roles` | roles | |
| `search_customers` | customers | by name/phone/email, no cards |
| `get_customer` | customer | include addresses/orders, no cards |

### AI / sampling (5, read-only via ctx.sample)
`summarize_sales`, `suggest_item_categories`, `inventory_reorder_suggestions`,
`detect_sales_anomalies`, `draft_customer_message`. Graceful fallback when the
client can't sample.

### Writes (8, guarded: dry_run + confirm/elicit + pre-check + bounds)
| Tool | Guard |
|---|---|
| `create_customer` | dup-check on email/phone |
| `update_customer` | elicit confirm; partial update |
| `create_item` | bounds, elicit confirm |
| `create_category` | elicit confirm |
| `create_order` | elicit confirm; empty order |
| `add_line_item` | elicit confirm; copies catalog price |
| `set_item_price_cents` | optimistic-lock pre-check + bounds |
| `set_item_stock_quantity` | optimistic-lock pre-check + bounds |

## Prompts (6, layer 3)
daily_briefing, weekly_sales_report, inventory_health_check,
end_of_day_closeout, customer_lookup, monthly_tax_summary.

## Resources (1)
`clover://capabilities` — capability cheat-sheet.

## Shapers (allowlist projection, `shaping.py`)
merchant, merchant_properties, item, item_group, order, line_item, order_type,
opening_hours, cash_event, attribute, tag, payment, refund, tender, customer,
employee, shift, category, modifier_group, device, tax, role.
**Excluded by allowlist:** card PAN/cardTransaction, employee pin/unhashedPin,
merchant aba/dda account numbers, billing flags, href URLs.

## Security / hardening already in place
- **Allowlist response shaping** — drop-by-default; contract-tested leak gate.
- **Guarded writes** — `dry_run`, MCP elicitation (`ctx.elicit`) or `confirm=True`,
  optimistic-lock pre-checks, numeric bounds. Never retried on 5xx.
- **No payment rails / no deletes** — by design; `delete()` exists on client but no
  tool exposes it.
- **OAuth 2.1 resource server** (layer-1) — JWKS + issuer + audience validation,
  RFC 9728 Protected Resource Metadata, fail-closed: http transport refuses to
  start without an IdP.
- **Multi-tenant isolation** — per-tenant client cache, per-tenant credential
  isolation (token-by-env-var-name references), fail-closed forwarded-header guard
  (`CLOVER_TRUST_IDENTITY_HEADER`), header-spoofing self-test via `whoami`.
- **Least-privilege scopes** — startup read-scope probes (warn, non-fatal); write
  scopes surface 403 at call time (no mutating probe).
- **Logging hygiene** — stderr only (stdio uses stdout for protocol); never logs
  tokens/PII/card data.
- **Tool annotations** — readOnlyHint / destructiveHint / idempotentHint /
  openWorldHint on every tool.

## Client behaviour (`client.py`)
- 30s timeout, pinned User-Agent.
- 401 → token refresh once (oauth_refresh mode).
- 429 → single retry if `Retry-After` ≤ 5s.
- 5xx → single retry on **reads only**; writes never retried (non-idempotent).
- `iterate()` pagination helper (limit/offset, elements envelope).
- Merchant info cache (currency/timezone).

## Tests
226 test functions. Contract tests for region resolution, windowing, shaping
allowlist (leak gate), money formatting. respx-mocked httpx; no real network.

## Config surface (`config.py`)
Region (na/eu/la) + sandbox URL resolution, token vs oauth_refresh auth, http
transport + multi-merchant, layer-1 OAuth (issuer/jwks/audience/scopes/public_url),
tenant routing (claim or forwarded header), token store (0600).
