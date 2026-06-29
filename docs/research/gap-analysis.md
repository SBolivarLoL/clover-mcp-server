# Gap analysis — what clover-mcp should & can have

Synthesises [mcp-best-practices.md](mcp-best-practices.md) (MCP spec/security) and
[clover-api-surface.md](clover-api-surface.md) (Clover REST API) against
[current-state.md](current-state.md) (what we ship today, v0.5.0).

Legend: ✅ **HAVE** · 🟢 **DONE this pass** · 🔵 **SHOULD** (worth doing) ·
⚪ **COULD** (niche / low value) · ⛔ **WON'T** (out of scope by design).

---

## A. MCP protocol & security

| Item | Status | Notes |
|---|---|---|
| Token pass-through **avoided** (MUST NOT) | ✅ | Clover creds from env/tenant store; the client's bearer token is never forwarded to Clover. |
| `readOnlyHint` on all reads | ✅ | 31 read + 5 AI tools annotated `_READ`. |
| `destructiveHint`/`idempotentHint` on writes | ✅ | `_WRITE_ADD` / `_WRITE_SET`. |
| No retry on non-idempotent writes (MUST) | ✅ | `client._send(is_write=True)` never retries 5xx. |
| Multi-tenant isolation by validated identity (MUST) | ✅ | Tenant key from token claim / verified header; per-tenant client + token store. |
| RFC 9728 Protected Resource Metadata | ✅ | `RemoteAuthProvider` serves it; http refuses to start without IdP. |
| Sampling capability fallback | ✅ | AI tools degrade to raw data if the client can't sample (`_narrate`). |
| Elicitation carries no secrets (MUST NOT) | ✅ | `ctx.elicit` only confirms; collects no passwords/tokens/PAN. |
| Logging hygiene — stderr only, no secrets | ✅ | |
| `outputSchema` / `structuredContent` | ✅ | FastMCP auto-derives for all 47 tools (loose `object`/`array`). Rich typed schemas = 47-tool refactor for marginal gain → ⚪ skip. |
| RFC 8707 audience binding | 🟢 | `audience` validated when set; **now warns at startup in http mode when unset** (defense in depth). Operators should set `CLOVER_AUTH_AUDIENCE`. |
| Origin / Host validation (DNS-rebinding, MUST for Streamable HTTP) | 🔵 | `mcp` ships `TransportSecurityMiddleware` but it's **off by default** and FastMCP doesn't wire it. Practical risk is low here (every request needs a valid bearer JWT) — documented in DEPLOY/SECURITY as a reverse-proxy responsibility rather than hand-rolled middleware. |
| Tool `title` (display name) | ⚪ | 0/47 set. Cosmetic; clients fall back to `name`. Add only if a client UX needs it. |
| Resource templates (`clover://items/{id}`) | ⚪ | One static capabilities resource today. Tools already cover item-by-id; a template duplicates that. |
| `completions` (argument autocomplete) | ⚪ | Niche; prompts have few args. |
| Confused-deputy consent screen | ⛔ | N/A — we're a pure resource server validating an external IdP's JWTs; we don't proxy Clover's OAuth with a shared client id. |

## B. Clover API — reads

| Capability | Status | Tool |
|---|---|---|
| Merchant info / properties | ✅ | `get_merchant_info`, `get_merchant_properties` |
| Sales summary (gross/net/refunds/tips/tax) | ✅ | `get_sales_summary` |
| Payments / refunds / tenders | ✅ | `list_payments`, `list_refunds`, `list_tenders` |
| Orders / order detail / open orders / order types | ✅ | `list_orders`, `get_order`, `list_open_orders`, `list_order_types` |
| Top sellers | ✅ | `get_top_items` |
| Items / item detail / low stock | ✅ | `list_items`, `get_item`, `list_low_stock_items` |
| Categories / modifiers / item groups / attributes / tags / taxes | ✅ | `list_*` |
| Devices / opening hours / cash events | ✅ | `list_devices`, `list_opening_hours`, `list_cash_events` |
| Employees / shifts / active shifts / roles | ✅ | `list_employees`, `get_employee`, `list_shifts`, `list_active_shifts`, `list_roles` |
| Customers (search/detail, no cards) | ✅ | `search_customers`, `get_customer` |
| **Discount catalogue** | 🟢 | `list_discounts` (new, INVENTORY_R, sandbox-verified) |
| **Tip-suggestion presets** | 🟢 | `list_tip_suggestions` (new, MERCHANT_R, sandbox-verified) |
| **Default service charge** | 🟢 | `get_default_service_charge` (new, MERCHANT_R, sandbox-verified) — closes the `get_sales_summary` service-charge gap |
| Order-level payments (`/orders/{id}/payments`) | ⚪ | `get_order` already expands `payments`; standalone tool is redundant. |
| Single opening-hours by id | ⚪ | `list_opening_hours` returns all sets already. |
| Tag→item mapping (`/tag_items`) | ⚪ | Niche; `list_tags` + item categories cover most needs. |
| Per-employee / per-device cash events | ⚪ | Merchant-level `list_cash_events` covers the common case. |

## C. Clover API — writes

| Capability | Status | Tool |
|---|---|---|
| Create customer (dup-guarded) | ✅ | `create_customer` |
| Update customer (POST, confirmed) | ✅ | `update_customer` |
| Create item / category / order; add line item | ✅ | guarded creates |
| Set item price / stock (optimistic-lock) | ✅ | `set_item_price_cents`, `set_item_stock_quantity` |
| Create discount / apply discount to order | ⚪ | Possible `GUARDED-WRITE` later; needs sandbox-verified pre-check. Not requested yet. |
| Apply service charge to order | ⚪ | Same — defer until there's a use case. |
| Payment capture / refund / void / charge | ⛔ | Out of scope by design — stays in the Clover dashboard. |
| Any DELETE | ⛔ | Out of scope by design. |
| Gateway / `bankProcessing` / ecommerce tokens | ⛔ | Sensitive; never exposed. |

## D. Conventions confirmed (from the Clover research)

- **Always window Payments/Orders** by `filter=createdTime>=…&filter=createdTime<=…` — repeated `filter` params are ANDed; unfiltered calls truncate. ✅ (`windowing.py` + 90-day chunking).
- Pagination: default 100, hard max 1000; nested collections cap at 100 (not paginable). ✅ (`iterate()`).
- ms-epoch timestamps; money in integer cents. ✅ (`formatting.py`).
- Rate limits ≈ 16 req/s per token, 5 concurrent. Our tools are sequential per call; the single-retry policy (429 ≤5s, one 5xx retry on reads) is appropriate. ⚪ no token-bucket needed at current usage.
- `expand=cards` / `bankProcessing` expose sensitive data — never expanded; allowlist drops them anyway. ✅
- Webhooks exist for cache invalidation — ⛔ not applicable to a request-scoped MCP server (no long-lived cache beyond per-process merchant info).

---

## Actions taken this pass
1. `list_discounts`, `list_tip_suggestions`, `get_default_service_charge` — implemented, shaped, sandbox-verified, tested, documented (47 tools, 231 tests).
2. Startup **audience-binding warning** in http mode when `CLOVER_AUTH_AUDIENCE` is unset.
3. DEPLOY/SECURITY note on Origin/Host validation being the reverse-proxy's job.

## Deliberately not done (with rationale)
- Rich typed `outputSchema` per tool — 47-tool refactor, marginal LLM benefit (KISS).
- Tool `title`s — cosmetic, clients fall back to `name`.
- New write tools (discounts, service charge on orders) — no current use case; writes are a privilege, added on demand with sandbox-verified pre-checks.
- Custom DNS-rebinding middleware — bearer-JWT auth already gates every request; proxy handles Host/Origin.
