# Clover API Endpoint Audit

> **M1 gate**: No tool beyond `get_merchant_info` ships until its row is filled in
> by hitting the endpoint against the sandbox and recording the actual response shape.

Sandbox base URL: `https://apisandbox.dev.clover.com`

---

## Status legend
- ✅ Verified — hit against sandbox, response shape confirmed
- 🔲 Pending — not yet audited
- ⚠️ Mismatch — documented shape differs from actual response (note discrepancy)

---

## Merchant

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}` | GET | 🔲 | Returns merchant info: name, currency, timezone, country |

---

## Orders

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/orders` | GET | ✅ | `{elements:[],href}`. Pagination offset/limit; page while `len==limit`. AND filters via **repeated** `?filter=X&filter=Y` (no `filter[]=`). Time: `filter=createdTime>=<ms>&filter=createdTime<=<ms>`. `state=open` valid. expand=lineItems,payments. Empty list → 200, never 404. |
| `/v3/merchants/{mId}/orders/{orderId}` | GET | ✅ | expand=lineItems,payments. 404 body `{"message":"Not Found","details":"Order not found"}`. Never expand customers.cards. |

---

## Payments

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/payments` | GET | ✅ | `{elements:[],href}`. offset/limit pagination. Repeated `?filter=` ANDed. `filter=createdTime>=<ms>&filter=createdTime<=<ms>`; `result=SUCCESS`; `voided=true` valid. Allowed filter fields in `X-Clover-Allowed-Filter-Fields` header. Empty → 200. ⚠️ refund detection via `amount<0` accepted by sandbox but unverified (no data) — confirm against prod or filter client-side. |
| `/v3/merchants/{mId}/orders/{orderId}/payments` | GET | 🔲 | Payments for a specific order |

---

## Inventory / Items

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/items` | GET | ✅ | `{elements:[],href}`. offset/limit. expand=itemStock,categories. Name search `filter=name=<val>` (supports `*` wildcard suffix). ⚠️ category filter is `filter=categoryId=<id>` — `filter=categories.id=` returns 400. Empty → 200. |
| `/v3/merchants/{mId}/items/{itemId}` | GET | ✅ | expand=itemStock,categories; `itemStock.quantity` present when expanded. 404 body `{"message":"invalid ID"}`. |
| `/v3/merchants/{mId}/items/{itemId}` | PUT | 🔲 | Update price: body `{ "price": <cents> }` |
| `/v3/merchants/{mId}/item_stocks/{itemId}` | GET | 🔲 | Current stock quantity |
| `/v3/merchants/{mId}/item_stocks/{itemId}` | PUT | 🔲 | Set stock: body `{ "quantity": <int> }` — ABSOLUTE value, not delta |
| `/v3/merchants/{mId}/categories` | GET | 🔲 | List categories |

---

## Customers

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/customers` | GET | ✅ | `{elements:[],href}`. offset/limit. expand=emailAddresses,phoneNumbers,addresses,orders. ⚠️ filter fields are **flat**: `filter=phoneNumber=`, `filter=emailAddress=`, `filter=fullName=` (NOT nested `phoneNumbers.phoneNumber`). Supported: customerSince, deletedTime, emailAddress, firstName, fullName, id, lastName, marketingAllowed, phoneNumber. |
| `/v3/merchants/{mId}/customers/{customerId}` | GET | ✅ | expand=emailAddresses,phoneNumbers,addresses,orders. 404 body `{"message":"Not Found","details":"Customer not found"}`. Cards never returned by shaper. |
| `/v3/merchants/{mId}/customers` | POST | 🔲 | Create customer: body fields TBD |

---

## Employees

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/employees` | GET | 🔲 | List employees |
| `/v3/merchants/{mId}/employees/{employeeId}` | GET | 🔲 | Single employee |
| `/v3/merchants/{mId}/employees/{employeeId}/shifts` | GET | 🔲 | Shifts for employee; filter=serverCreatedTime>=X |
| `/v3/merchants/{mId}/shifts` | GET | 🔲 | All shifts across merchant (check if supported) |

---

## Response shape notes (to fill in during audit)

For each endpoint above, record:
- Exact field names in response (especially money fields — cents vs dollars)
- Pagination style (offset/limit or cursor)
- Whether `expand` params are supported and exact expand token names
- Rate limit observed (check response headers: `X-RateLimit-*`)
- Any undocumented required headers or query params
