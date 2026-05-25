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
| `/v3/merchants/{mId}/orders` | GET | 🔲 | Supports filter=createdTime>=X, expand=lineItems,payments,customers |
| `/v3/merchants/{mId}/orders/{orderId}` | GET | 🔲 | expand=lineItems,payments |

---

## Payments

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/payments` | GET | 🔲 | Supports filter=createdTime>=X; result=SUCCESS; expand=tender,employee,order |
| `/v3/merchants/{mId}/orders/{orderId}/payments` | GET | 🔲 | Payments for a specific order |

---

## Inventory / Items

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/items` | GET | 🔲 | expand=itemStock,categories; filter=name~query |
| `/v3/merchants/{mId}/items/{itemId}` | GET | 🔲 | Full item detail |
| `/v3/merchants/{mId}/items/{itemId}` | PUT | 🔲 | Update price: body `{ "price": <cents> }` |
| `/v3/merchants/{mId}/item_stocks/{itemId}` | GET | 🔲 | Current stock quantity |
| `/v3/merchants/{mId}/item_stocks/{itemId}` | PUT | 🔲 | Set stock: body `{ "quantity": <int> }` — ABSOLUTE value, not delta |
| `/v3/merchants/{mId}/categories` | GET | 🔲 | List categories |

---

## Customers

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/v3/merchants/{mId}/customers` | GET | 🔲 | filter=emailAddress=X or phoneNumber=X; expand=emailAddresses,phoneNumbers |
| `/v3/merchants/{mId}/customers/{customerId}` | GET | 🔲 | Full customer detail |
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
