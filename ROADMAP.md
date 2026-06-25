# Roadmap

Working list of what's next. Shipped state: **0.2.0** on PyPI + the MCP Registry;
**0.3.0 cut and merged on `main`** (29 tools, both auth modes, multi-tenant + hosted
OAuth, security hardened), awaiting the `v0.3.0` tag to publish. Full design context
lives in the private build plan; this file is the actionable backlog.

Each tool follows the same recipe: **audit the endpoint → add a shaper projection
→ implement → annotate (`ToolAnnotations`) → tests (happy + error) → add the
permission probe → record the row in `docs/endpoints.md`.**

## North star — a complete, agent-ready MCP server

The product goal: a merchant or business owner connects this server to their agent
(Claude, ChatGPT, their own cloud) and runs their Clover business by conversation,
for whatever merchant(s) they own. "Complete v1.0" means three layers, not one:

1. **API access** — broad, safe coverage of the Clover surface (reads + guarded
   writes), with the allowlist shaping and confirmation guardrails already in place.
2. **AI/LLM tools** — tools that need model inference (summarize sales, auto-categorize
   items) done via **MCP sampling**, so the server itself never holds an LLM key.
3. **Prompts & workflows** — predefined, parameterized prompts (daily briefing, low-stock
   check, today's open orders) that orchestrate the tools so a merchant's agent works
   out of the box.

Sections below break each layer into concrete, recipe-sized work.

---

## Near-term follow-ups (small, do anytime)

- [x] **Service charges** — _resolved 2026-06-21._ Live audit showed an order's
      `serviceCharge` is a percentage definition (`percentageDecimal`) with no
      computed amount, so the old `serviceCharge.amount` sum was always 0. Removed
      `service_charges_collected` (the paid amount is already in `gross_sales`);
      dropped the `ORDERS_R` dependency from `get_sales_summary`.
- [x] **Refund detection** — _resolved 2026-06-21._ Switched `get_sales_summary`
      from the wrong `amount<0` payment heuristic to the dedicated
      `GET /v3/merchants/{mId}/refunds` endpoint (positive `amount`).
- [x] **OAuth refresh live-soak** — _verified 2026-06-21._ A real `get_merchant_info`
      call succeeded in `oauth_refresh` mode against live Clover (earlier the full
      401 → refresh → rotate → retry path was proven end-to-end).

---

## v1.1 — expanded read surface (opt-in, none gate v1) — **shipped 0.1.5**

New read tools + their permission scopes:

- [x] `list_employees`, `get_employee` — `EMPLOYEES_R` (shaper drops PINs)
- [x] `list_shifts(employee_id?, date_from?, date_to?)`, `list_active_shifts` — `EMPLOYEES_R`
- [x] `list_categories`, `list_modifiers` — `INVENTORY_R`
- [x] `get_top_items` — aggregate across orders/line items (`ORDERS_R`)
- [x] `list_devices`, `list_taxes` — `MERCHANT_R` / `INVENTORY_R`

Housekeeping for v1.1:
- [x] Re-add the `EMPLOYEES_R` row to the README permission matrix.
- [x] Add startup permission probe for `EMPLOYEES_R` (optional — warns, never blocks startup).
- [x] No customer/item/employee **updates** beyond v1 — still deliberately deferred.

Follow-up:
- [x] Live sandbox shape-verification for the 9 new endpoints — _done 2026-06-21
      (PR #15)._ All 9 verified ✅ in `docs/endpoints.md` via `scripts/seed_sandbox.py`.
      Confirmed: `tax_rates.rate` unit is `rate/100000` (10_000_000 == 100%); there
      is **no** merchant-level `/shifts` (listings iterate employees); the shift
      payload carries `employee.id` only, so tools inject the name; `list_devices`
      is empty on a sandbox with no provisioned hardware.

---

## v2 — remote / hosted server (bigger effort)

**Phase 1 shipped (released in 0.2.0, opt-in, stdio default unchanged):** transport
switch and layer-1 OAuth via FastMCP's resource-server support. See
[docs/DEPLOY.md](docs/DEPLOY.md). Live-verified PRM + 401 discovery.

- [x] **Streamable HTTP transport** (vs. stdio) — `CLOVER_TRANSPORT=http`.
- [x] **Multi-tenant routing** — per-request merchant by authenticated identity
      (`remote.py`: `load_tenants`, `tenant_config`, `request_tenant_key`, per-tenant
      client cache). _See phase 2 below._
- [x] **MCP-level (layer-1) OAuth — mandatory once network-reachable.** Via FastMCP
      `RemoteAuthProvider` + `JWTVerifier` (resource server only; http refuses to
      start without an IdP):
  - [x] OAuth 2.1 bearer JWT validation against an external AS/IdP (no implicit grant)
  - [x] Resource server only — delegates to the operator's IdP (no token issuance here)
  - [x] Publishes Protected Resource Metadata (RFC 9728) at
        `/.well-known/oauth-protected-resource/mcp`; 401s carry the `resource_metadata` pointer
  - [x] Audience-bound tokens (RFC 8707) + scope enforcement via `JWTVerifier`
- [ ] **OAuth onboarding** (auth-code + PKCE w/ hosted callback) — the IdP owns this;
      remaining glue is provisioning each merchant's row in the merchant store.
- [ ] **Webhook → SSE bridge** (optional) for push updates.

**Phase 2 shipped (multi-tenant):** one deployment serves many merchants by
mapping the authenticated identity → merchant. Tenant map from `CLOVER_TENANTS_JSON`
(env, persists on ephemeral hosts) or a file; identity from `CLOVER_TENANT_HEADER`
(gateway platforms like Horizon) or `CLOVER_TENANT_CLAIM` (custom IdP); `whoami`
probe. **Deployed on FastMCP Cloud / Horizon and sandbox-proven.**

---

## Layer 1 — API coverage (the Clover surface)

Status today: **29 tools**, read-mostly + 3 guarded writes. Goal: cover the surface a
business-owner agent realistically needs. Each row is the standard recipe. Writes carry
a per-endpoint decision: **read-only** / **guarded-write** (dry-run + optimistic lock +
confirmation, see Layer 4 elicitation) / **excluded** (safety).

### Reads to add (read-first; low risk, high agent value)
- [ ] **Order detail sub-resources** — discounts, line-item modifications, voided line
      items, `GET /orders/{id}/payments`. `get_order` already returns line items +
      payments; expose the rest so an agent can fully explain an order. (`ORDERS_R`)
- [ ] **Order types** `GET /order_types` and **merchant settings**: `opening_hours`,
      `tip_suggestions`, `default_service_charge`. (`MERCHANT_R`) — reference data agents
      ask about ("are we open?", "what's the default tip?").
- [ ] **Cash events** `GET /cash_events` — cash-drawer log (paid in/out, no-sale). (`MERCHANT_R` / cash perm)
- [ ] **Inventory depth** — item **attributes & options** (variants), **tags**, item-level
      **discounts**, and item↔modifier-group / item↔tax associations. (`INVENTORY_R`)
- [ ] **Employee time detail** — time cards / per-shift breakdown beyond `list_shifts`. (`EMPLOYEES_R`)
- [ ] **Credits / authorizations** (low priority) — `GET /credits`, payment auths. (`PAYMENTS_R`)

### Writes to decide (the real "run your business" surface)
These unlock an agent that *operates* the POS, not just reports on it. All gated behind
dry-run + confirmation (Layer 4) and opt-in scopes:
- [ ] **Orders** — create order, add/void line item, apply discount, mark paid. Big and
      high-value, but the riskiest writes; needs the strongest confirmation UX. (`ORDERS_W`)
- [ ] **Inventory** — create/update item, create category/modifier, manage tags. Extends
      the existing price/stock writes. (`INVENTORY_W`)
- [ ] **Customers** — update customer, add/remove email/phone/address. (`CUSTOMERS_W`)
- [ ] **Employees** — create/update employee, manage roles — likely **excluded** (sensitive). 

### Stays excluded (safety; revisit only with hardened confirmation UX)
Refunds, voids, payment capture, charge creation, record **deletes**, gateway/processing
config, the Ecommerce API, device-paired endpoints. The "complete coverage" goal forces an
explicit, logged decision on each — it does not mean "expose everything."

---

## Layer 2 — AI/LLM tools (via MCP sampling)

Some tools need model reasoning, not just data. Implement them with **MCP sampling**:
the tool gathers Clover data via the existing client, then calls `ctx.sample(...)` to ask
the **connected client's** model to reason — so this server never holds an LLM provider key
or makes a paid API call itself.

Design contract for every sampling tool:
- Gather data with existing read tools/shapers → build a **bounded** prompt (cap rows/tokens).
- Call `ctx.sample()`; return **structured** output, clearly labeled as a suggestion.
- **Read-only**: never auto-act on the model's output (no writes from a sampling tool).
- **Capability fallback**: if the client doesn't support sampling, return the raw data +
  a note ("connect a sampling-capable client for the narrative") — never hard-fail.

Candidate tools:
- [ ] `summarize_sales(period)` — sales summary + top items + tenders → a plain-language
      briefing with notable movements.
- [ ] `suggest_item_categories` — for uncategorized items, propose categories from the
      merchant's existing taxonomy (suggestion only; applying it is a separate guarded write).
- [ ] `inventory_reorder_suggestions` — low-stock × recent sales velocity → a reorder list.
- [ ] `detect_sales_anomalies(period)` — flag unusual refund/void/discount/sales patterns.
- [ ] `draft_customer_message(intent)` — promo / win-back copy from customer + sales context.

Prereq: thread a FastMCP `Context` parameter into tool signatures (none use it today).

---

## Layer 3 — Prompts & workflows (MCP prompts capability)

Predefined, parameterized prompts (`@mcp.prompt`) the merchant's agent can invoke directly.
These contain **no LLM call** themselves — they're vetted instructions that drive the
existing tools, so common workflows work out of the box and consistently.

- [ ] `daily_briefing` — today's sales summary + low-stock + open orders.
- [ ] `weekly_sales_report` — 7-day summary, top items, tender breakdown, vs. prior week.
- [ ] `inventory_health_check` — low stock + uncategorized items + slow movers.
- [ ] `end_of_day_closeout` — reconcile today's payments / refunds / voids; cash events.
- [ ] `customer_lookup(query)` — find a customer and summarize their history.
- [ ] `monthly_tax_summary(month)` — tax collected, by rate.

Prompts should take arguments (date ranges, IDs) and reference tools by name so the agent
chains them deterministically.

---

## Layer 4 — MCP capabilities checklist (what makes v1.0 "complete")

A complete agent-ready server:
- [x] **Tools** — 44 (36 read-only incl. 5 AI/sampling + 8 guarded write), allowlist-shaped, annotated.
- [x] **Prompts** — Layer 3. Six `@mcp.prompt` workflows shipped.
- [x] **Sampling** — Layer 2 (client-side LLM; server stays key-free). Five tools shipped.
- [x] **Elicitation** — mid-tool confirmation for guarded writes (`confirm.py`,
      `ctx.elicit`; fail-closed with a `confirm=True` override). Shipped with the
      Layer 1 write surface.
- [x] **Resources** — `clover://capabilities` cheat-sheet (built live from the registry).
- [x] **Progress + logging** — `get_sales_summary` logs per 90-day window (guarded).
- [ ] **Structured output schemas** — partly implicit today via return type hints; explicit
      JSON-Schema formalization for stricter client parsing is deferred (low priority).

---

## Plan to production multi-tenant (real merchants)

Sequence: **(A) full API coverage → (B) security hardening → (C) go prod.** Do
NOT host real merchants' data until B is done. (Layers 2–4 above are product features
that can land in parallel with A; none gate B/C.)

### A. Expand API coverage (the main remaining build)
See **[Layer 1 — API coverage](#layer-1--api-coverage-the-clover-surface)** below for the
concrete endpoint-by-endpoint inventory (what's covered, what's missing, read vs.
guarded-write). That is the bulk of the pre-prod build.

### B. Security hardening (REQUIRED before real merchants — none optional)
See **[docs/SECURITY.md](docs/SECURITY.md)** for the full checklist + procedures.
- [x] **Header-spoofing guard.** Header routing now **fails closed** — the server
      boots (so `whoami` can run the spoofing test) but `request_tenant_key` refuses
      every data call unless `CLOVER_TRUST_IDENTITY_HEADER=true` (opt-in after verifying
      the gateway strips client copies). `whoami` emits the test procedure + startup
      warns. ⚙️ Operator must still **run the test** on their gateway.
- [x] **Per-tenant credential isolation** — tenant entries can reference each token by
      its own env var (`access_token_env`/`refresh_token_env`) instead of one plaintext
      blob. ⚙️ Operator wires those to a secret-manager (encryption at rest is an ops
      task — see SECURITY.md).
- [x] **Prefer cryptographic identity over forwarded headers** — documented + enforced:
      validated-JWT identity (self-host) needs no trust flag; header routing does.
- [ ] 📋 **Legal/compliance** — custodian duties (data-protection, Clover terms,
      disclaimers). Documented in SECURITY.md; requires counsel sign-off, not code.
- [x] **Per-tenant token refresh that survives restarts** — permanent API tokens
      (default) + env/secret-manager references survive ephemeral-disk restarts.
- [x] **One-deploy-per-merchant** documented as the simplest zero-spoofing-surface
      alternative (SECURITY.md §5).

### C. Other hosted follow-ups
- [ ] Pick + wire a concrete IdP provider module if self-hosting auth.
- [ ] Deploy target + CI/CD (Dockerfile, health check) if leaving Horizon.
- [ ] **OAuth onboarding** (auth-code + PKCE w/ hosted callback) to self-provision
      each merchant's tenant row instead of editing `CLOVER_TENANTS_JSON` by hand.
- [ ] **Webhook → SSE bridge** (optional) for push updates.

---

## Out of scope (deliberate non-goals)

The write exclusions are catalogued in **[Layer 1 — Stays excluded](#stays-excluded-safety-revisit-only-with-hardened-confirmation-ux)**
(refunds, voids, payment capture, charge creation, deletes, gateway config, Ecommerce
API, device-paired endpoints). Revisit only with the Layer 4 elicitation guardrail in
place. Note: AI/LLM tools and prompts (Layers 2–3) are now explicitly **in** scope —
earlier versions of this roadmap treated the server as tools-only.
