# Clover API Endpoint Audit

> **M1 gate**: No tool beyond `get_merchant_info` ships until its row is filled in
> by hitting the endpoint against the sandbox and recording the actual response shape.

Sandbox base URL: `https://apisandbox.dev.clover.com`

---

## Status legend
- ✅ Verified — hit against sandbox, response shape confirmed
- 🟡 Implemented, unverified — shipped from API docs; live sandbox audit still owed
- 🔲 Pending — not yet audited
- ⚠️ Mismatch — documented shape differs from actual response (note discrepancy)

---

## Merchant

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}` | GET | 🔲 | Returns merchant info: name, currency, timezone, country |
| `/v3/merchants/{mId}/properties` | GET | ✅ | `get_merchant_properties` (MERCHANT_R). Single object (not paginated). Sandbox-verified 2026-06-24: POS config — currency, timezone, locale, tips, stock tracking, closeout, support contacts. ⚠️ payload **also carries banking fields** (`abaAccountNumber`, `ddaAccountNumber`); the shaper allowlist deliberately excludes them and `href`/`merchantRef`. |

---

## Orders

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/orders` | GET | ✅ | `{elements:[],href}`. Pagination offset/limit; page while `len==limit`. AND filters via **repeated** `?filter=X&filter=Y` (no `filter[]=`). Time: `filter=createdTime>=<ms>&filter=createdTime<=<ms>`. `state=open` valid. expand=lineItems,payments. Empty list → 200, never 404. |
| `/v3/merchants/{mId}/orders/{orderId}` | GET | ✅ | expand=lineItems.modifications,lineItems.discounts,payments,discounts. `get_order` surfaces `line_items` (with `item_id`, `modifications`, `discounts`), `payments` (shaped via `shape_payment` → no card data), and order-level `discounts`. Live order 2026-06-24: line item carries `item.id`/`name`/`price`/`refunded`/`exchanged`/`isRevenue`. 404 body `{"message":"Not Found","details":"Order not found"}`. Never expand customers.cards. ⚠️ `serviceCharge` (expandable) is a **percentage** definition `{id,name,enabled,percentageDecimal}` — no per-order computed dollar amount, so service charges aren't summed in `get_sales_summary`. |

---

## Payments

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/payments` | GET | ✅ | `{elements:[],href}`. offset/limit pagination. Repeated `?filter=` ANDed. `filter=createdTime>=<ms>&filter=createdTime<=<ms>`; `result=SUCCESS`; `voided=true` valid. Allowed filter fields in `X-Clover-Allowed-Filter-Fields` header. Empty → 200. |
| `/v3/merchants/{mId}/refunds` | GET | ✅ | `{elements:[],href}`. Refunds are **separate objects** with a positive `amount` (cents) — NOT negative payments. Used by `get_sales_summary` for refund totals and exposed via `list_refunds` (covered by PAYMENTS_R). Standard `createdTime` filter. Shape `{id,amount,taxAmount,createdTime,order_id,payment_id,employee_id}` — `transactionInfo` dropped. Sandbox empty. |
| `/v3/merchants/{mId}/orders/{orderId}/payments` | GET | 🔲 | Payments for a specific order |

---

## Inventory / Items

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/items` | GET | ✅ | `{elements:[],href}`. offset/limit. expand=itemStock,categories. Name search `filter=name=<val>` (supports `*` wildcard suffix). ⚠️ category filter is `filter=categoryId=<id>` — `filter=categories.id=` returns 400. Empty → 200. |
| `/v3/merchants/{mId}/items/{itemId}` | GET | ✅ | expand=itemStock,categories; `itemStock.quantity` present when expanded. 404 body `{"message":"invalid ID"}`. |
| `/v3/merchants/{mId}/items/{itemId}` | PUT | ✅ | ⚠️ body needs `{"name": <str>, "price": <cents>}` — **`name` is required**, 400 without it (pre-check GET supplies it). Returns full item. Negative price → 400. Requires INVENTORY_W. |
| `/v3/merchants/{mId}/item_stocks/{itemId}` | GET | ✅ | `{item:{id}, stockCount, quantity(float), modifiedTime}`. If stock never set, only `{item:{id}}` (no quantity key). |
| `/v3/merchants/{mId}/item_stocks/{itemId}` | PUT | ✅ | body `{"quantity": <int>}` — ABSOLUTE (overwrites, not delta; confirmed). `quantity` returned as **float**. No stock-tracking/autoManage prerequisite — works on any item. Requires INVENTORY_W. |
| `/v3/merchants/{mId}/categories` | GET | ✅ | v1.1 `list_categories`. `{elements:[]}`; shape `{id,name,sortOrder}`. POST `{name}` creates. Sandbox-verified 2026-06-21. |
| `/v3/merchants/{mId}/item_groups` | GET | ✅ | `list_item_groups` (INVENTORY_R). Sets of item variants (size/color). Endpoint verified 2026-06-24 — `{elements:[]}`, **empty** on this sandbox (no groups provisioned). Shape `{id,name}` (element shape from docs; none live to confirm fields beyond id/name). |
| `/v3/merchants/{mId}/modifier_groups` | GET | ✅ | v1.1 `list_modifiers`. expand=modifiers returns `{id,name,showByDefault,...,modifiers:[{id,name,price}]}`. POST modifier at `/modifier_groups/{id}/modifiers`. Sandbox-verified. |
| `/v3/merchants/{mId}/tax_rates` | GET | ✅ | v1.1 `list_taxes`. shape `{id,name,rate,isDefault,rate_percent}`. ✅ **unit confirmed**: seeded `rate=825000` → `rate_percent=8.25`, i.e. `rate/100000` (10_000_000==100%). Sandbox always includes a `NO_TAX_APPLIED` rate. |
| `/v3/merchants/{mId}/devices` | GET | ✅ | v1.1 `list_devices` (MERCHANT_R). Returns `{elements:[]}`; empty on a sandbox with no provisioned hardware (devices can't be created via REST). Shape `{id,name,serial,model,productName,deviceTypeName}`. Sandbox-verified (empty). |
| `/v3/merchants/{mId}/tenders` | GET | ✅ | `list_tenders` (MERCHANT_R). `{elements:[],href}`. Sandbox-verified 2026-06-24: 14 default tenders (Cash, Credit Card, Check, gift cards, etc.). Element keys `{id,editable,labelKey,label,opensCashDrawer,enabled,visible,supportsCashDiscount,href}`; shaper keeps all but `href` (`labelKey` e.g. `com.clover.tender.cash`). |
| `/v3/merchants/{mId}/order_types` | GET | 🟡 | `list_order_types` (MERCHANT_R). Endpoint reachable 2026-06-24 (200, `{elements:[],href}`) but **empty** on this sandbox. Shape `{id,label,taxable,isDefault,isHidden,filterCategories}` from API docs — live element shape unconfirmed. |
| `/v3/merchants/{mId}/opening_hours` | GET | 🟡 | `list_opening_hours` (MERCHANT_R). Reachable 2026-06-24 (200, empty). Shape `{id,name,<day>:[{start,end}]}` per-day arrays, from docs — live shape unconfirmed. |
| `/v3/merchants/{mId}/cash_events` | GET | 🟡 | `list_cash_events` (MERCHANT_R). Reachable 2026-06-24 (200, empty). Shape `{id,type,amount,note,timestamp,employee_id,device_id}` from docs — live shape unconfirmed. `limit` capped 1–500. |
| `/v3/merchants/{mId}/attributes` | GET | 🟡 | `list_attributes` (INVENTORY_R). Reachable 2026-06-24 (200, empty). `expand=options`. Shape `{id,name,options:[{id,name}]}` from docs — live shape unconfirmed. |
| `/v3/merchants/{mId}/tags` | GET | 🟡 | `list_tags` (INVENTORY_R). Reachable 2026-06-24 (200, empty). Shape `{id,name,showInReporting}` from docs — live shape unconfirmed. |

---

## Customers

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/customers` | GET | ✅ | `{elements:[],href}`. offset/limit. expand=emailAddresses,phoneNumbers,addresses,orders. ⚠️ filter fields are **flat**: `filter=phoneNumber=`, `filter=emailAddress=`, `filter=fullName=` (NOT nested `phoneNumbers.phoneNumber`). Supported: customerSince, deletedTime, emailAddress, firstName, fullName, id, lastName, marketingAllowed, phoneNumber. |
| `/v3/merchants/{mId}/customers/{customerId}` | GET | ✅ | expand=emailAddresses,phoneNumbers,addresses,orders. 404 body `{"message":"Not Found","details":"Customer not found"}`. Cards never returned by shaper. |
| `/v3/merchants/{mId}/customers` | POST | ✅ | body: `firstName`/`lastName` top-level; ⚠️ email/phone are **sub-resources** not flat fields — `emailAddresses:[{emailAddress}]`, `phoneNumbers:[{phoneNumber}]` in the create body (flat strings silently ignored). Response omits contacts unless `?expand=emailAddresses,phoneNumbers`. `marketingAllowed` ignored on sandbox. PUT/PATCH on customer → 405. Requires CUSTOMERS_W. |

---

## Employees

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/employees` | GET | ✅ | v1.1 `list_employees`/`get_employee`. `{elements:[]}`; shaper drops `pin`/`unhashedPin` (none leaked live). `isOwner`/`role` present. EMPLOYEES_R (optional scope). Sandbox-verified 2026-06-21. |
| `/v3/merchants/{mId}/employees/{employeeId}` | GET | ✅ | Single employee. POST works (created a seed employee with `{name,role:EMPLOYEE}`). |
| `/v3/merchants/{mId}/roles` | GET | ✅ | `list_roles` (EMPLOYEES_R). Sandbox-verified 2026-06-24: 3 system roles (Employee/Manager/Admin). Element keys `{id,name,systemRole,merchant,href}`; shaper keeps `{id,name,systemRole}` (drops empty `merchant` + `href`). |
| `/v3/merchants/{mId}/employees/{employeeId}/shifts` | GET | ✅ | v1.1 `list_shifts`/`list_active_shifts`. ⚠️ no merchant-level `/shifts` — listings iterate employees. Shift payload carries `employee:{id}` only (no name) → tools inject the name from the iterated employee. Active = falsy `outTime`. POST `{}` clocks in (open shift). Sandbox-verified. |

---

## OAuth (auth_mode=oauth_refresh)

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `{base_url}/oauth/v2/refresh` | POST | ✅ | Same host as REST API (sandbox/na/eu/la follow base_url). Body JSON `{"client_id", "refresh_token"}` — **no client_secret**. Returns `{access_token, access_token_expiration, refresh_token, refresh_token_expiration}` (Unix ts). ⚠️ refresh_token is **single-use** — rotated pair must be persisted (token store handles this). Verified against docs.clover.com/dev/docs/refresh-access-tokens. |

---

## Response shape notes (to fill in during audit)

For each endpoint above, record:
- Exact field names in response (especially money fields — cents vs dollars)
- Pagination style (offset/limit or cursor)
- Whether `expand` params are supported and exact expand token names
- Rate limit observed (check response headers: `X-RateLimit-*`)
- Any undocumented required headers or query params
