# Roadmap

Working list of what's next. Released state on PyPI + the MCP Registry: **0.7.0**
(47 tools, 6 prompts, both auth modes, multi-tenant + hosted OAuth, security
hardened). Working tree (unreleased, staged for the next release): **56 tools** —
the roadmap-completion sprint (2026-07-05) added `get_item` include-expansions,
`list_credits`, and five guarded writes (`apply_order_discount`,
`update_item_name`, `create_modifier_group`, `create_modifier`, `create_tag`); see
three reporting-depth reads (`get_sales_by_employee`, `get_tips_by_employee`,
`get_sales_by_hour`) followed; see CHANGELOG.md `[Unreleased]` for the full list.
Full design context lives in the
private build plan; this file is the actionable backlog. Research + gap analysis:
[docs/research/](docs/research/). Fresh idea dump + sequencing (2026-07):
[docs/roadmap-extended.md](docs/roadmap-extended.md).

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
      is **no** merchant-level `/shifts` (listings iterate employees — _corrected
      by the 2026-07-05 audit: it does exist; see "Employee time detail" below_); the shift
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
- [x] **OAuth onboarding** (auth-code + PKCE w/ hosted callback) — _resolved:
      moved, 2026-07-05._ Superseded by the hosted-offering plan in
      [docs/roadmap-extended.md §4](docs/roadmap-extended.md#4-multi-tenant-productization-the-hosted-offering);
      tracked there (see also §C below).
- [x] **Webhook → SSE bridge** (optional) — _resolved: moved, 2026-07-05._
      Design lives in
      [docs/roadmap-extended.md §2.3](docs/roadmap-extended.md#23-webhook-bridge--agent-notifications-the-live-differentiator);
      tracked there (see also §C below).

**Phase 2 shipped (multi-tenant):** one deployment serves many merchants by
mapping the authenticated identity → merchant. Tenant map from `CLOVER_TENANTS_JSON`
(env, persists on ephemeral hosts) or a file; identity from `CLOVER_TENANT_HEADER`
(gateway platforms like Horizon) or `CLOVER_TENANT_CLAIM` (custom IdP); `whoami`
probe. **Deployed on FastMCP Cloud / Horizon and sandbox-proven.**

---

## Layer 1 — API coverage (the Clover surface)

Status today (working tree, unreleased): **56 tools**, read-mostly + 13 guarded
writes. Goal: cover the surface a business-owner agent realistically needs. Each
row is the standard recipe. Writes carry
a per-endpoint decision: **read-only** / **guarded-write** (dry-run + optimistic lock +
confirmation, see Layer 4 elicitation) / **excluded** (safety).

### Reads to add (read-first; low risk, high agent value)
- [x] **Order detail sub-resources** — _shipped._ `get_order` returns line-item
      `modifications` and `discounts` plus order-level `discounts` and `payments`
      (`ORDERS_R`).
  - [x] **Voided line items** — _resolved-excluded, 2026-07-05 audit._ No read
        path exists in the Clover API: `expand=voidedLineItems` on `GET
        /orders/{id}` is silently ignored (200, the key never appears in the
        body) and `GET /orders/{id}/voided_line_items` returns 405. See the
        negative-finding rows in `docs/endpoints.md`.
  - [x] Standalone `GET /orders/{id}/payments` — _resolved-excluded._ Deemed
        redundant since `get_order` already expands `payments` (see gap-analysis.md).
- [x] **Order types** `GET /order_types` and **merchant settings** — _shipped._
      `list_order_types`, `list_opening_hours`, `list_tip_suggestions`,
      `get_default_service_charge` (`MERCHANT_R`).
- [x] **Cash events** `GET /cash_events` — _shipped._ `list_cash_events` (`MERCHANT_R`).
- [x] **Inventory depth** — _partially shipped._ Item **attributes & options**
      (`list_attributes`), **tags** (`list_tags`), and merchant-level **discount
      catalogue** (`list_discounts`) shipped (`INVENTORY_R`).
  - [x] **Item↔modifier-group / item↔tax associations (read)** — _resolved-shipped,
        2026-07-05._ `get_item(item_id, include=[...])` expands both associations
        inline (plus other item sub-resources) instead of adding standalone list
        tools — one endpoint, opt-in expansion, matches `get_order`'s pattern.
- [x] **Employee time detail** — _resolved-no-op, 2026-07-05 audit._ Both
      `GET /time_cards` (merchant-level) and `GET /employees/{id}/timecards`
      return 405 — Clover exposes no time-card resource. Shifts
      (`GET /employees/{id}/shifts`) are the only time-detail Clover has, and
      `list_shifts`/`list_active_shifts` already cover them. Bonus correction
      recorded in `docs/endpoints.md`: the earlier note claiming no
      merchant-level `GET /shifts` exists was wrong — it works (200), but the
      existing per-employee-iteration implementation is kept because it already
      enriches employee names, which the merchant-level shape doesn't carry.
- [x] **Credits / authorizations** — _resolved-shipped, 2026-07-05._ `list_credits`
      (`PAYMENTS_R`). Payment authorizations remain excluded with the rest of the
      payments surface (see "Stays excluded" below).

### Writes to decide (the real "run your business" surface)
These unlock an agent that *operates* the POS, not just reports on it. All gated behind
dry-run + confirmation (Layer 4) and opt-in scopes:
- **Orders** (`ORDERS_W`) — decided 2026-07-05:
  - [x] **Apply discount** — SHIPPED. `apply_order_discount` (guarded: dry_run +
        expected-current pre-check + elicitation, `ORDERS_W`). Notes: Clover
        requires **negative** amounts on the wire for amount-based discounts —
        the tool takes positive cents from the caller and negates internally so
        the public contract stays intuitive. Applying a catalogue discount
        requires sending the discount's inline `name` + `percentage` — Clover
        does not dereference a discount `id` server-side, so the tool resolves
        the id to its name/percentage via `list_discounts` before the write.
  - [x] **Void line item** — EXCLUDED. Clover exposes only the `DELETE` verb for
        this resource; repo policy excludes deletes (see "Stays excluded"), and
        the 2026-07-05 audit found no POST/PUT alternative to void a line item.
  - [x] **Mark paid / payment capture** — EXCLUDED, unchanged. Stays with the
        rest of the payments-writes policy (refunds, voids, charge creation).
  - Create order / add line item were already shipped pre-audit (see Layer 4
    checklist below) and are unaffected by these decisions.
- **Inventory** (`INVENTORY_W`) — decided 2026-07-05:
  - [x] SHIPPED: `update_item_name` (verified the underlying `POST` is a
        non-clobbering partial update — other item fields survive), plus three
        new additive creates: `create_modifier_group`, `create_modifier`,
        `create_tag`.
  - [x] **Item↔modifier-group and tag↔item association writes** —
        EXCLUDED-for-now. The `POST` endpoints return `200 {}`, but the
        resulting association is never observable via any read path (including
        `get_item(include=[...])`), so the mandatory expected-state post-check
        (CLAUDE.md: "Write tools require pre-checks") cannot be implemented.
        Revisit only if Clover's sandbox starts surfacing the association on a
        read.
- [x] **Customers** — _shipped._ `update_customer` (name + marketing opt-in, guarded
      via dry_run + confirmation) (`CUSTOMERS_W`). Add/remove email/phone/address
      still open (those are sub-resources, not covered by `update_customer`).
- [x] **Employees** — decided EXCLUDED, 2026-07-05. Matches the "likely excluded"
      lean already called out here: employee writes touch PINs/roles/access,
      which is sensitive-enough surface that no amount of dry-run/elicitation
      guarding changes the risk calculus. Revisit only alongside a dedicated
      employee-security design, not as part of ordinary write-recipe work.

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
- [x] `summarize_sales(period)` — _shipped._ sales summary + top items → a plain-language
      briefing with notable movements (`tools/ai.py`).
- [x] `suggest_item_categories` — _shipped._ for uncategorized items, propose categories from the
      merchant's existing taxonomy (suggestion only; applying it is a separate guarded write).
- [x] `inventory_reorder_suggestions` — _shipped._ low-stock × recent sales velocity → a reorder list.
- [x] `detect_sales_anomalies(period)` — _shipped._ flags unusual refund/sales patterns.
- [x] `draft_customer_message(intent)` — _shipped._ promo / win-back copy from customer + sales context.

Prereq: thread a FastMCP `Context` parameter into tool signatures — _done, all five above take `ctx`._

---

## Layer 3 — Prompts & workflows (MCP prompts capability)

Predefined, parameterized prompts (`@mcp.prompt`) the merchant's agent can invoke directly.
These contain **no LLM call** themselves — they're vetted instructions that drive the
existing tools, so common workflows work out of the box and consistently.

- [x] `daily_briefing` — _shipped._ today's sales summary + low-stock + open orders (`prompts.py`).
- [x] `weekly_sales_report` — _shipped._ 7-day summary, top items, tender breakdown, vs. prior week.
- [x] `inventory_health_check` — _shipped._ low stock + uncategorized items + missing price/SKU.
- [x] `end_of_day_closeout` — _shipped._ reconciles today's payments / refunds; flags open orders.
- [x] `customer_lookup(query)` — _shipped._ finds a customer and summarizes their history.
- [x] `monthly_tax_summary(month)` — _shipped._ tax collected, by rate.

Prompts should take arguments (date ranges, IDs) and reference tools by name so the agent
chains them deterministically.

---

## Layer 4 — MCP capabilities checklist (what makes v1.0 "complete")

A complete agent-ready server:
- [x] **Tools** — 56 (43 read-only incl. 5 AI/sampling + 13 guarded write; working
      tree, unreleased), allowlist-shaped, annotated.
- [x] **Prompts** — Layer 3. Six `@mcp.prompt` workflows shipped.
- [x] **Sampling** — Layer 2 (client-side LLM; server stays key-free). Five tools shipped.
- [x] **Elicitation** — mid-tool confirmation for guarded writes (`confirm.py`,
      `ctx.elicit`; fail-closed with a `confirm=True` override). Shipped with the
      Layer 1 write surface.
- [x] **Resources** — `clover://capabilities` cheat-sheet (built live from the registry).
- [x] **Progress + logging** — `get_sales_summary` logs per 90-day window (guarded).
- [x] **Structured output schemas** — _decided-deferred, 2026-07-05._ FastMCP
      auto-derives an `outputSchema`/`structuredContent` for every tool today
      (loose `object`/`array`); hand-writing rich, per-tool typed schemas across
      all 56 tools is a full-registry refactor for marginal client-side benefit.
      Rationale recorded in `docs/research/gap-analysis.md` (§ `outputSchema` /
      `structuredContent` row). Revisit only if a client demonstrably needs
      stricter typing to parse responses correctly.

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
- [x] 📋 **Legal/compliance** — _resolved (engineering side), 2026-07-05._ The
      code/doc deliverable is complete: custodian duties (data-protection, Clover
      terms, disclaimers) are documented in SECURITY.md. What remains is counsel
      sign-off — an **operator go-live gate**, not repo work; it is tracked as a
      precondition of hosting real merchants (see the sequence note above), not
      as a backlog item here.
- [x] **Per-tenant token refresh that survives restarts** — permanent API tokens
      (default) + env/secret-manager references survive ephemeral-disk restarts.
- [x] **One-deploy-per-merchant** documented as the simplest zero-spoofing-surface
      alternative (SECURITY.md §5).

### C. Other hosted follow-ups — all resolved 2026-07-05 (n/a on Horizon, or moved)
- [x] Pick + wire a concrete IdP provider module if self-hosting auth —
      _resolved: not applicable while on Horizon._ Horizon provides managed
      auth; this item only re-opens if a self-host target is ever chosen.
- [x] Deploy target + CI/CD (Dockerfile, health check) if leaving Horizon —
      _resolved: not applicable while on Horizon._ `/healthz` already exists;
      a Dockerfile is only needed off-Horizon. Re-opens with the item above.
- [x] **OAuth onboarding** (auth-code + PKCE w/ hosted callback) —
      _resolved: moved._ Superseded by the fuller hosted-offering plan
      (merchant store → onboarding glue → connect page) in
      [docs/roadmap-extended.md §4](docs/roadmap-extended.md#4-multi-tenant-productization-the-hosted-offering);
      tracked there, not here.
- [x] **Webhook → SSE bridge** (optional) — _resolved: moved._ Full design
      (signature-verified receiver, per-tenant ring buffer, tools-first
      exposure) lives in
      [docs/roadmap-extended.md §2.3](docs/roadmap-extended.md#23-webhook-bridge--agent-notifications-the-live-differentiator);
      tracked there, not here.

---

## Out of scope (deliberate non-goals)

The write exclusions are catalogued in **[Layer 1 — Stays excluded](#stays-excluded-safety-revisit-only-with-hardened-confirmation-ux)**
(refunds, voids, payment capture, charge creation, deletes, gateway config, Ecommerce
API, device-paired endpoints). Revisit only with the Layer 4 elicitation guardrail in
place. Note: AI/LLM tools and prompts (Layers 2–3) are now explicitly **in** scope —
earlier versions of this roadmap treated the server as tools-only.
