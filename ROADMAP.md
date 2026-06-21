# Roadmap

Working list of what's next. Shipped state: **v0.1.3** on PyPI + the MCP Registry
(14 tools, both auth modes, security hardened). Full design context lives in the
private build plan; this file is the actionable backlog.

Each tool follows the same recipe: **audit the endpoint → add a shaper projection
→ implement → annotate (`ToolAnnotations`) → tests (happy + error) → add the
permission probe → record the row in `docs/endpoints.md`.**

---

## Near-term follow-ups (small, do anytime)

- [ ] **Verify `service_charges_collected` against real payment data.** Currently
      summed from orders but never exercised with a paid order (sandbox can't seed
      card payments). Confirm on a real merchant.
- [ ] **Verify refund detection.** `get_sales_summary` uses an `amount<0` SUCCESS
      heuristic (unverified — see the `ponytail:` note in `tools/reporting.py`).
      Upgrade path: query `GET /v3/merchants/{mId}/refunds` directly.
- [ ] **OAuth refresh live-soak.** Confirmed once end-to-end; let a token expire
      naturally in real use and confirm transparent refresh + store rotation.

---

## v1.1 — expanded read surface (opt-in, none gate v1)

New read tools + their permission scopes:

- [ ] `list_employees`, `get_employee` — `EMPLOYEES_R` (shaper already drops PINs)
- [ ] `list_shifts(employee_id?, date_from?, date_to?)`, `list_active_shifts` — `EMPLOYEES_R`
- [ ] `list_categories`, `list_modifiers` — `INVENTORY_R`
- [ ] `get_top_items` — aggregate across orders/line items (`ORDERS_R`)
- [ ] `list_devices`, `list_taxes` — `MERCHANT_R` / `INVENTORY_R` as applicable

Housekeeping for v1.1:
- [ ] Re-add the `EMPLOYEES_R` row to the README permission matrix once those tools land.
- [ ] Add startup permission probe for `EMPLOYEES_R`.
- [ ] No customer/item/employee **updates** beyond v1 — those need more write-safety UX thought.

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
