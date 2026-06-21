# Roadmap

Working list of what's next. Shipped state: **v0.1.3** on PyPI + the MCP Registry
(14 tools, both auth modes, security hardened). Full design context lives in the
private build plan; this file is the actionable backlog.

Each tool follows the same recipe: **audit the endpoint → add a shaper projection
→ implement → annotate (`ToolAnnotations`) → tests (happy + error) → add the
permission probe → record the row in `docs/endpoints.md`.**

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

- [ ] **Streamable HTTP transport** (vs. stdio).
- [ ] **Multi-merchant**: per-merchant token storage + routing.
- [ ] **MCP-level (layer-1) OAuth — mandatory once network-reachable.** Distinct
      from the upstream Clover auth. Per the MCP authorization spec:
  - [ ] OAuth 2.1 + PKCE (S256); no implicit grant
  - [ ] Act as a **resource server only** — delegate to an external authorization server / IdP
  - [ ] Publish Protected Resource Metadata (RFC 9728) at `/.well-known/oauth-protected-resource`
  - [ ] Support RFC 8414 (AS metadata) + RFC 8707 (resource indicators, audience-bound tokens)
- [ ] **OAuth onboarding** (auth-code + PKCE w/ hosted callback) replacing manual token paste.
- [ ] **Webhook → SSE bridge** (optional) for push updates.

---

## Out of scope (deliberate non-goals)

Refunds, voids, payment capture, charge creation, record deletes, the Ecommerce
API, device-paired endpoints. Revisit only with proven confirmation UX.
