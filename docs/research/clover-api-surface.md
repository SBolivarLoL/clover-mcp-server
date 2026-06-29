# Clover REST API Surface Catalogue

**Purpose:** Comprehensive endpoint inventory for `clover-mcp` planning — covers the full Clover Platform REST API v3 surface, classified by MCP exposure potential.

**Sources:**
- API Reference overview: https://docs.clover.com/dev/reference/api-reference-overview
- REST API conventions: https://docs.clover.com/dev/docs/making-rest-api-calls
- Pagination: https://docs.clover.com/dev/docs/paginating-elements
- Filters: https://docs.clover.com/dev/docs/applying-filters
- Expand fields: https://docs.clover.com/dev/docs/expanding-fields
- Rate limits: https://docs.clover.com/dev/docs/api-usage-rate-limits
- Webhooks: https://docs.clover.com/dev/docs/webhooks
- Permissions (EU): https://docs.clover.com/dev/docs/customers-api-eu-permissions
- LLM index: https://docs.clover.com/llms.txt

---

## API Conventions

### Base URLs

| Environment | Base URL |
|---|---|
| Sandbox | `https://apisandbox.dev.clover.com` |
| Production — North America | `https://api.clover.com` |
| Production — Europe | `https://api.eu.clover.com` |
| Production — Latin America | `https://api.la.clover.com` |

### Authentication

OAuth 2.0 Bearer tokens. Production requires expiring access/refresh tokens. Sandbox accepts merchant-scoped test API tokens. All calls must use HTTPS.

### Pagination

- Parameters: `limit` (default 100, max 1000) and `offset` (0-based).
- Response envelope: `{ "elements": [...] }`.
- **Nested fields cap at 100 items** — cannot paginate nested collections directly.
- Ecommerce API uses cursor-style pagination (`starting_after` / `ending_before`) with `limit` 1–100.

### expand Parameter

- Syntax: `?expand=field1%2Cfield2` (comma-encoded) or `?expand=parent.child` for nested.
- **Maximum 3 fields per call.**
- Not supported on Ecommerce API (objects fully expanded by default).

### filter Parameter

- Syntax: `?filter=field>=value&filter=field<value`.
- Operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, and `AND` for date ranges.
- Supported fields vary by endpoint; check `X-Clover-Allowed-Filter-Fields` response header.
- **90-day window enforced** on time-based filters for Orders and Payments.

### Timestamps

All timestamps are Unix epoch in **milliseconds** (ms). Use `modifiedTime` filters for incremental sync.

### Rate Limits

| Scope | Per-second | Concurrent |
|---|---|---|
| Per app (all tokens combined) | 50 req/s | 10 concurrent |
| Per token | 16 req/s | 5 concurrent |

HTTP 429 is returned on breach; `Retry-After` header gives seconds to wait. Use exponential backoff. **Best practice:** use webhooks + `modifiedTime` filters to avoid polling.

### Webhook Event Keys

| Key | Resource | Required Permission |
|---|---|---|
| A | Apps (install/uninstall) | MERCHANT_R |
| C | Customers | CUSTOMERS_R |
| CA | Cash adjustments | MERCHANT_R |
| E | Employees | EMPLOYEES_R |
| I | Inventory items | INVENTORY_R |
| IC | Inventory categories | INVENTORY_R |
| IG | Inventory modifier groups | INVENTORY_R |
| IM | Inventory modifiers | INVENTORY_R |
| M | Merchants | MERCHANT_R |
| O | Orders | ORDERS_R |
| P | Payments | PAYMENTS_R |
| SH | Service hours | MERCHANT_R |

---

## Recommendation Legend

| Code | Meaning |
|---|---|
| `HAVE-CANDIDATE` | Good read tool to expose in MCP |
| `GUARDED-WRITE` | Write tool exposable with `dry_run` + confirm + pre-check |
| `AVOID` | Payment rails, deletes, banking, or out-of-scope |
| `MAYBE` | Niche/low value — expose only if a use-case demands it |

---

## 1. Merchants

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}` | Get merchant details | R | `HAVE-CANDIDATE` | MERCHANT_R | `expand=address,properties,owner,tenders,tipSuggestions,openingHours,gateway,printers,tags` |
| GET | `/v3/merchants/{mId}/address` | Get merchant address | R | `HAVE-CANDIDATE` | MERCHANT_R | — |
| GET | `/v3/merchants/{mId}/properties` | Get merchant properties (locale, currency, tips enabled, etc.) | R | `HAVE-CANDIDATE` | MERCHANT_R | — |
| POST | `/v3/merchants/{mId}/properties` | Update merchant properties | W | `AVOID` | MERCHANT_W | — |
| GET | `/v3/merchants/{mId}/gateway` | Get payment gateway configuration | R | `AVOID` | MERCHANT_R | — (sensitive: banking/processing config) |
| GET | `/v3/merchants/{mId}/tip_suggestions` | List tip suggestion presets (flat/%) | R | `HAVE-CANDIDATE` | MERCHANT_R | `filter`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/opening_hours/{hId}` | Get a set of merchant opening hours | R | `HAVE-CANDIDATE` | MERCHANT_R | — |
| POST | `/v3/merchants/{mId}/opening_hours` | Create opening hours | W | `GUARDED-WRITE` | MERCHANT_W | — |
| POST | `/v3/merchants/{mId}/opening_hours/{hId}` | Update opening hours | W | `GUARDED-WRITE` | MERCHANT_W | — |
| GET | `/v3/merchants/{mId}/order_types` | List order types (dine-in, to-go, delivery, etc.) | R | `HAVE-CANDIDATE` | MERCHANT_R | `filter`, `expand=hours,attributes,categories`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/tenders` | List accepted payment tenders | R | `HAVE-CANDIDATE` | MERCHANT_R | `filter`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/default_service_charge` | Get default service charge configuration | R | `HAVE-CANDIDATE` | MERCHANT_R | — |

**Notes:**
- `GET /v3/merchants/{mId}` with `expand=bankProcessing` exposes sensitive banking fields — AVOID that expand.
- `gateway` endpoint returns payment processor credentials — AVOID.

---

## 2. Inventory — Items

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/items` | List all inventory items | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter=modifiedTime,hidden,available,price,sku,name,itemGroup.id`, `expand=tags,categories,taxRates,modifierGroups,itemStock,options`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/items/{itemId}` | Get a single item | R | `HAVE-CANDIDATE` | INVENTORY_R | `expand=tags,categories,taxRates,modifierGroups,itemStock,options` |
| POST | `/v3/merchants/{mId}/items` | Create inventory item | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/items/{itemId}` | Update inventory item | W | `GUARDED-WRITE` | INVENTORY_W | — |
| DELETE | `/v3/merchants/{mId}/items/{itemId}` | Delete inventory item | W | `AVOID` | INVENTORY_W | — |

**Notes:**
- `GET /items` is the core read tool. Filter by `modifiedTime` for incremental sync. 90-day window does NOT apply here (payments/orders only).
- `expand=itemStock` returns live stock quantities — very valuable.
- Price is in **cents** (integer).

---

## 3. Inventory — Item Stock

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/item_stocks/{itemId}` | Get stock for a single item | R | `HAVE-CANDIDATE` | INVENTORY_R | — |
| POST | `/v3/merchants/{mId}/item_stocks/{itemId}` | Update stock quantity for an item | W | `GUARDED-WRITE` | INVENTORY_W | — |

**Notes:**
- Stock can be fractional (decimal). `stockCount` is deprecated — use `quantity`.
- `autoManage` flag on item controls whether stock is tracked.
- Stock is also accessible via `GET /items?expand=itemStock`.

---

## 4. Inventory — Categories

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/categories` | List all categories | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter=modifiedTime,deleted,sortOrder,name,colorCode,id`, `expand=items`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/categories/{categoryId}` | Get a single category | R | `HAVE-CANDIDATE` | INVENTORY_R | `expand=items` |
| GET | `/v3/merchants/{mId}/categories/{categoryId}/items` | List items in a category | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter`, `limit`, `expand` |
| POST | `/v3/merchants/{mId}/categories` | Create category | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/category_items` | Associate items with a category | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/category_items?delete=true` | Remove item-category association | W | `AVOID` | INVENTORY_W | — |

---

## 5. Inventory — Modifier Groups & Modifiers

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/modifier_groups` | List all modifier groups | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter=modifiedTime,category.id,item.id,name,id`, `expand=modifiers,items`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/modifier_groups/{modGroupId}` | Get a single modifier group | R | `HAVE-CANDIDATE` | INVENTORY_R | `expand=modifiers,items` |
| GET | `/v3/merchants/{mId}/modifier_groups/{modGroupId}/items` | List items in a modifier group | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter`, `expand` |
| GET | `/v3/merchants/{mId}/modifier_groups/{modGroupId}/modifiers` | List modifiers in a group | R | `HAVE-CANDIDATE` | INVENTORY_R | `expand=modifierGroup` |
| POST | `/v3/merchants/{mId}/modifier_groups` | Create modifier group | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/modifier_groups/{modGroupId}/modifiers` | Create a modifier | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/item_modifier_groups` | Associate items with modifier groups | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/item_modifier_groups?delete=true` | Remove item-modifier group association | W | `AVOID` | INVENTORY_W | — |

**Notes from search:** `GET /modifier_groups/{id}/modifiers` also available at `/v3/merchants/{mId}/modifiers` (all modifiers across all groups).

---

## 6. Inventory — Item Groups, Attributes & Options

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/item_groups` | List item groups (variant families) | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter`, `expand=items,attributes`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/item_groups/{itemGroupId}` | Get a single item group | R | `HAVE-CANDIDATE` | INVENTORY_R | `expand=items,attributes` |
| POST | `/v3/merchants/{mId}/item_groups` | Create item group | W | `GUARDED-WRITE` | INVENTORY_W | — |
| GET | `/v3/merchants/{mId}/attributes` | List attributes (e.g., Size, Color) | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter`, `expand=options`, `limit`, `offset` |
| POST | `/v3/merchants/{mId}/attributes` | Create an attribute | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/attributes/{attributeId}/options` | Create attribute option (e.g., "Large") | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/option_items` | Associate option with item | W | `GUARDED-WRITE` | INVENTORY_W | — |

---

## 7. Inventory — Tags (Labels)

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/tags` | List all tags (item labels / printer labels) | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter=modifiedTime,deleted,name,showInReporting,id`, `expand=items,printers`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/tag_items` | List all tag-to-item mappings | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter` |
| POST | `/v3/merchants/{mId}/tags` | Create a tag | W | `GUARDED-WRITE` | INVENTORY_W | — |
| POST | `/v3/merchants/{mId}/tag_items` | Associate tag with item | W | `GUARDED-WRITE` | INVENTORY_W | — |

---

## 8. Inventory — Tax Rates

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/tax_rates` | List all tax rates | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter`, `expand`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/tax_rates/{taxRateId}` | Get a single tax rate | R | `HAVE-CANDIDATE` | INVENTORY_R | — |
| POST | `/v3/merchants/{mId}/tax_rates` | Create a tax rate | W | `GUARDED-WRITE` | INVENTORY_W | — |

---

## 9. Inventory — Discounts

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/discounts` | List all inventory-level discounts | R | `HAVE-CANDIDATE` | INVENTORY_R | `filter=amount,modifiedtime,percentage,id`, `limit`, `offset` |
| POST | `/v3/merchants/{mId}/discounts` | Create a discount | W | `GUARDED-WRITE` | INVENTORY_W | — |

---

## 10. Orders

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/orders` | List orders | R | `HAVE-CANDIDATE` | ORDERS_R | `filter=createdTime,modifiedTime,employee.id,payType`, `expand=employee,payments,lineItems,customers,discounts,serviceCharges,orderType`, `limit`, `offset` (90-day filter window) |
| GET | `/v3/merchants/{mId}/orders/{orderId}` | Get a single order | R | `HAVE-CANDIDATE` | ORDERS_R | `expand=lineItems,serviceCharge,discounts,credits,payments,customers,refunds` |
| POST | `/v3/merchants/{mId}/orders` | Create an order | W | `GUARDED-WRITE` | ORDERS_W | — |
| POST | `/v3/merchants/{mId}/atomic_order/orders` | Create complete order atomically (items, mods, discounts) | W | `GUARDED-WRITE` | ORDERS_W | — |
| POST | `/v3/merchants/{mId}/orders/{orderId}` | Update an order | W | `GUARDED-WRITE` | ORDERS_W | — |
| DELETE | `/v3/merchants/{mId}/orders/{orderId}` | Delete/void an order | W | `AVOID` | ORDERS_W | — |

---

## 11. Orders — Line Items

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/orders/{orderId}/line_items` | List all line items on an order | R | `HAVE-CANDIDATE` | ORDERS_R | `expand=employee,orderType,discounts,modifications,taxRates,payments` |
| GET | `/v3/merchants/{mId}/orders/{orderId}/line_items/{lineItemId}` | Get a single line item | R | `HAVE-CANDIDATE` | ORDERS_R | `expand=employee,orderType,discounts,modifications,taxRates,payments` |
| POST | `/v3/merchants/{mId}/orders/{orderId}/line_items` | Add a line item to an order | W | `GUARDED-WRITE` | ORDERS_W | — |
| POST | `/v3/merchants/{mId}/orders/{orderId}/bulk_line_items` | Add multiple line items at once | W | `GUARDED-WRITE` | ORDERS_W | — |
| POST | `/v3/merchants/{mId}/orders/{orderId}/line_items/{lineItemId}/modifications` | Add modifier to a line item | W | `GUARDED-WRITE` | ORDERS_W | — |
| DELETE | `/v3/merchants/{mId}/orders/{orderId}/line_items/{lineItemId}` | Remove a line item | W | `AVOID` | ORDERS_W | — |

---

## 12. Orders — Discounts & Service Charges

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/orders/{orderId}/discounts` | List discounts on an order | R | `HAVE-CANDIDATE` | ORDERS_R | — |
| POST | `/v3/merchants/{mId}/orders/{orderId}/discounts` | Apply discount to order | W | `GUARDED-WRITE` | ORDERS_W | — |
| POST | `/v3/merchants/{mId}/orders/{orderId}/line_items/{lineItemId}/discounts` | Apply discount to line item | W | `GUARDED-WRITE` | ORDERS_W | — |
| POST | `/v3/merchants/{mId}/orders/{orderId}/service_charge` | Apply service charge to order | W | `GUARDED-WRITE` | ORDERS_W | — |

---

## 13. Orders — Print Events

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| POST | `/v3/merchants/{mId}/print_event` | Submit print request for an order | W | `MAYBE` | ORDERS_W | body: `orderRef.id` |
| GET | `/v3/merchants/{mId}/print_event/{eventId}` | Get print job status | R | `MAYBE` | ORDERS_R | — |

**Notes:** Useful only when merchant has a Clover device online. Only returns status for CREATED / PRINTING / FAILED states.

---

## 14. Payments

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/payments` | List all payments | R | `HAVE-CANDIDATE` | PAYMENTS_R | `filter=createdTime,modifiedTime,result,voided,amount,cardType,employee.id,tender.id`, `expand=tender,cardTransaction,refunds,lineItemPayments,transactionInfo,order,additionalCharges`, `limit`, `offset` (90-day window) |
| GET | `/v3/merchants/{mId}/payments/{paymentId}` | Get a single payment | R | `HAVE-CANDIDATE` | PAYMENTS_R | `expand=tender,cardTransaction,refunds,transactionInfo,additionalCharges` |
| GET | `/v3/merchants/{mId}/orders/{orderId}/payments` | List payments for an order | R | `HAVE-CANDIDATE` | PAYMENTS_R | `filter=amount,result,createdTime,tender.id`, `expand=tender,refunds,employee,cardTransaction` |

**Notes:**
- `result` field values: `SUCCESS`, `FAIL`, `AUTH`, `VOIDED`.
- `expand=cardTransaction` returns masked card data (last 4, card type, auth code) — allow in shaping allowlist; never return raw PAN.
- `expand=additionalCharges` returns surcharge and convenience fee detail (CREDIT_SURCHARGE, CONVENIENCE_FEE, INTERAC_V2).
- 90-day filter window strictly enforced; always supply `createdTime` filter or Clover will return only recent 90 days.

---

## 15. Refunds (Read-Only — No Write)

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/refunds` | List all refunds | R | `HAVE-CANDIDATE` | PAYMENTS_R | `filter`, `expand=payment,employee,lineItems,serviceCharge`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/refunds/{refundId}` | Get a single refund | R | `HAVE-CANDIDATE` | PAYMENTS_R | `expand=payment,germanInfo,appTracking,employee,lineItems,transactionInfo` |
| POST | `/v3/merchants/{mId}/orders/{orderId}/payments/{paymentId}/refund` | Issue a refund on a payment | W | `AVOID` | PAYMENTS_W | — (payment rails) |
| POST | `/v3/merchants/{mId}/payments/{paymentId}/voids` | Void a payment | W | `AVOID` | PAYMENTS_W | — (payment rails) |

---

## 16. Ecommerce API — Charges & Refunds (Separate Base URL)

> Base: `https://scl-sandbox.dev.clover.com` (sandbox) — separate from the v3 platform API.

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v1/orders` | List ecommerce orders | R | `MAYBE` | ECOMM | `created`, `customer`, `status`, `limit`, `starting_after`, `ending_before` |
| GET | `/v1/orders/{orderId}` | Get a single ecommerce order | R | `MAYBE` | ECOMM | `expand` |
| POST | `/v1/orders` | Create ecommerce order | W | `AVOID` | ECOMM | — |
| POST | `/v1/orders/{orderId}/pay` | Pay for ecommerce order | W | `AVOID` | ECOMM | — (payment rails) |
| GET | `/v1/charges` | List charges | R | `MAYBE` | ECOMM | `created`, `customer`, `limit` |
| GET | `/v1/charges/{chargeId}` | Get a charge | R | `MAYBE` | ECOMM | — |
| POST | `/v1/charges` | Create a charge | W | `AVOID` | ECOMM | — (payment rails) |
| POST | `/v1/charges/{chargeId}/capture` | Capture an authorized charge | W | `AVOID` | ECOMM | — (payment rails) |
| POST | `/v1/refunds` | Issue a refund | W | `AVOID` | ECOMM | — (payment rails) |
| GET | `/v1/refunds/{refundId}` | Get a refund | R | `MAYBE` | ECOMM | — |
| POST | `/v1/orders/{orderId}/returns` | Return items on ecommerce order | W | `AVOID` | ECOMM | — (payment rails) |

---

## 17. Customers

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/customers` | List all customers | R | `HAVE-CANDIDATE` | CUSTOMERS_R | `filter=customerSince,firstName,lastName,emailAddress,phoneNumber,marketingAllowed,fullName,id,deletedTime`, `expand=addresses,emailAddresses,phoneNumbers,cards,metadata`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/customers/{customerId}` | Get a single customer | R | `HAVE-CANDIDATE` | CUSTOMERS_R | `expand=addresses,emailAddresses,phoneNumbers,cards,metadata` |
| POST | `/v3/merchants/{mId}/customers` | Create customer | W | `GUARDED-WRITE` | CUSTOMERS_W | — |
| POST | `/v3/merchants/{mId}/customers/{customerId}` | Update customer | W | `GUARDED-WRITE` | CUSTOMERS_W | — |
| DELETE | `/v3/merchants/{mId}/customers/{customerId}` | Delete customer | W | `AVOID` | CUSTOMERS_W | — |

---

## 18. Customers — Sub-Resources (PII)

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| POST | `/v3/merchants/{mId}/customers/{customerId}/addresses` | Add address to customer | W | `GUARDED-WRITE` | CUSTOMERS_ADDRESS_W | — |
| POST | `/v3/merchants/{mId}/customers/{customerId}/addresses/{addressId}` | Update a customer address | W | `GUARDED-WRITE` | CUSTOMERS_ADDRESS_W | — |
| POST | `/v3/merchants/{mId}/customers/{customerId}/email_addresses` | Add email to customer | W | `GUARDED-WRITE` | CUSTOMERS_EMAIL_W | — |
| POST | `/v3/merchants/{mId}/customers/{customerId}/email_addresses/{emailId}` | Update customer email | W | `GUARDED-WRITE` | CUSTOMERS_EMAIL_W | — |
| POST | `/v3/merchants/{mId}/customers/{customerId}/phone_numbers` | Add phone number to customer | W | `GUARDED-WRITE` | CUSTOMERS_PHONE_W | — |
| POST | `/v3/merchants/{mId}/customers/{customerId}/phone_numbers/{phoneId}` | Update customer phone | W | `GUARDED-WRITE` | CUSTOMERS_PHONE_W | — |

**Notes on `expand=cards`:**
- Returns tokenized card-on-file data: last 4 digits, expiry, card type, token — **never raw PAN**.
- AVOID returning `cards` in MCP responses; strip via shaping allowlist.
- To create a card-on-file use the Ecommerce tokenization flow, not a direct v3 write.

**EU region:** Requires granular scopes per sub-resource (CUSTOMERS_ADDRESS_R/W, CUSTOMERS_EMAIL_R/W, CUSTOMERS_PHONE_R/W, CUSTOMERS_CARDS_R/W, CUSTOMERS_MARKETING_R/W, CUSTOMERS_NOTE_R/W, CUSTOMERS_BUSINESSNAME_R/W, CUSTOMERS_BIRTHDATE_R/W).

---

## 19. Employees

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/employees` | List all employees | R | `HAVE-CANDIDATE` | EMPLOYEES_R | `filter=modifiedTime,role,name,id,email`, `expand=roles,shifts`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/employees/{employeeId}` | Get a single employee | R | `HAVE-CANDIDATE` | EMPLOYEES_R | `expand=roles,shifts` |
| POST | `/v3/merchants/{mId}/employees` | Create employee | W | `GUARDED-WRITE` | EMPLOYEES_W | — |
| POST | `/v3/merchants/{mId}/employees/{employeeId}` | Update employee | W | `GUARDED-WRITE` | EMPLOYEES_W | — |
| DELETE | `/v3/merchants/{mId}/employees/{employeeId}` | Delete employee | W | `AVOID` | EMPLOYEES_W | — |

**Shaping note:** Strip `pin` field from all employee responses — never expose employee PINs.

---

## 20. Employees — Roles

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/roles` | List all roles (system + custom) | R | `HAVE-CANDIDATE` | EMPLOYEES_R | `filter=modifiedTime,systemRole,name,id,deletedTime`, `expand=employees`, `limit`, `offset` |
| GET | `/v3/merchants/{mId}/roles/{roleId}` | Get a single role | R | `HAVE-CANDIDATE` | EMPLOYEES_R | `expand=employees` |
| POST | `/v3/merchants/{mId}/roles` | Create a role | W | `GUARDED-WRITE` | EMPLOYEES_W | — |

---

## 21. Employees — Shifts

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/employees/{empId}/shifts` | List shifts for an employee | R | `HAVE-CANDIDATE` | EMPLOYEES_R | `filter=employee.id,inTime,outTime,name`, `expand=employee,overrideEmployee` |
| POST | `/v3/merchants/{mId}/employees/{empId}/shifts` | Create shift for an employee | W | `GUARDED-WRITE` | EMPLOYEES_W | — |
| POST | `/v3/merchants/{mId}/employees/{empId}/shifts/{shiftId}` | Update a single shift | W | `GUARDED-WRITE` | EMPLOYEES_W | — |
| DELETE | `/v3/merchants/{mId}/employees/{empId}/shifts/{shiftId}` | Delete a shift | W | `AVOID` | EMPLOYEES_W | — |

---

## 22. Cash Events

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/employees/{empId}/cash_events` | List cash events for an employee | R | `HAVE-CANDIDATE` | MERCHANT_R | `filter=employee.id,note,amountChange,type,device.id,timestamp`, `expand=employee,device` |
| GET | `/v3/merchants/{mId}/devices/{deviceId}/cash_events` | List cash events for a device | R | `HAVE-CANDIDATE` | MERCHANT_R | `filter=employee.id,note,amountChange,type,device.id,timestamp`, `expand=employee,device` |

**Note:** Cash event `type` values include cash drawer open, cash in, cash out. Useful for end-of-day reconciliation.

---

## 23. Devices

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/devices` | List devices registered to merchant | R | `MAYBE` | MERCHANT_R | `filter`, `limit`, `offset` |

**Note:** Devices accessible via `expand=devices` on merchant endpoint too.

---

## 24. App Billing & Metered Events

| Method | Path | Purpose | R/W | Recommendation | Scope | Key Query Params |
|---|---|---|---|---|---|---|
| POST | `/v3/apps/{appId}/merchants/{mId}/metereds/{meteredId}` | Create a metered billing event | W | `AVOID` | APP_BILLING | `count` (default 1) |
| GET | `/v3/apps/{appId}/merchants/{mId}/metereds/{meteredId}` | Get all events for a metered type | R | `AVOID` | APP_BILLING | — |
| GET | `/v3/apps/{appId}/merchants/{mId}/metereds/{meteredId}/events/{eventId}` | Get a single metered event | R | `AVOID` | APP_BILLING | — |

**Note:** App billing is a developer infrastructure concern, not merchant-facing data. AVOID in MCP.

---

## 25. Ecommerce — Tokens & Subscriptions (AVOID all)

| Method | Path | Purpose | R/W | Recommendation | Notes |
|---|---|---|---|---|---|
| POST | `/v1/tokens` | Tokenize a card | W | `AVOID` | Payment rails |
| POST | `/v1/charges/{chargeId}/capture` | Capture auth | W | `AVOID` | Payment rails |
| POST | `/v1/plans` | Create subscription plan | W | `AVOID` | Billing infra |
| POST | `/v1/subscriptions` | Create subscription | W | `AVOID` | Billing infra |
| GET | `/v1/plans` | List plans | R | `AVOID` | Billing infra, out-of-scope |
| GET | `/v1/subscriptions/{id}` | Get subscription | R | `AVOID` | Billing infra |

---

## 26. REST Pay Display API (Semi-integration — AVOID all)

These endpoints control physical Clover devices in semi-integrated POS setups.

| Method | Path | Purpose | R/W | Recommendation |
|---|---|---|---|---|
| POST | `/v1/pay` | Initiate payment on device | W | `AVOID` |
| POST | `/v1/capture` | Capture on device | W | `AVOID` |
| POST | `/v1/refund` | Refund via device | W | `AVOID` |
| POST | `/v1/void` | Void via device | W | `AVOID` |
| POST | `/v1/read_signature` | Capture signature | W | `AVOID` |
| POST | `/v1/read_tip` | Prompt for tip | W | `AVOID` |

---

## 27. Gift Cards (AVOID all)

| Method | Path | Purpose | R/W | Recommendation |
|---|---|---|---|---|
| POST | `/v1/gift_cards/activation` | Activate gift card | W | `AVOID` |
| GET | `/v1/gift_cards/balance_inquiry` | Check balance | R | `AVOID` |
| POST | `/v1/gift_cards/reload` | Reload gift card | W | `AVOID` |

---

## 28. Ecommerce Config

| Method | Path | Purpose | R/W | Recommendation | Notes |
|---|---|---|---|---|---|
| GET | `/v3/merchants/{mId}/ecomm_payment_configs` | Get surcharging config and rates | R | `MAYBE` | Useful if merchant uses surcharging; exposes `surcharging.supported` and `rate` |

---

## Summary: Priority HAVE-CANDIDATE Endpoints (Not Yet in Project)

Based on a review of `docs/endpoints.md` and comparison with the above catalogue, the following read endpoints are high-value candidates that may not yet be implemented:

1. **GET `/v3/merchants/{mId}/tip_suggestions`** — Merchant tip presets
2. **GET `/v3/merchants/{mId}/opening_hours/{hId}`** — Opening hours
3. **GET `/v3/merchants/{mId}/discounts`** — Merchant-level discount catalogue
4. **GET `/v3/merchants/{mId}/item_groups`** — Item variant groups
5. **GET `/v3/merchants/{mId}/attributes`** — Item attributes (Size, Color, etc.)
6. **GET `/v3/merchants/{mId}/tag_items`** — Tag-to-item mapping
7. **GET `/v3/merchants/{mId}/roles`** — Employee roles
8. **GET `/v3/merchants/{mId}/employees/{empId}/shifts`** — Employee time-clock data
9. **GET `/v3/merchants/{mId}/employees/{empId}/cash_events`** — Cash drawer activity per employee
10. **GET `/v3/merchants/{mId}/devices/{deviceId}/cash_events`** — Cash events per device
11. **GET `/v3/merchants/{mId}/refunds`** — All refunds list (read-only, safe)
12. **GET `/v3/merchants/{mId}/orders/{orderId}/discounts`** — Discounts on a specific order
13. **GET `/v3/merchants/{mId}/default_service_charge`** — Merchant service charge config
14. **GET `/v3/merchants/{mId}/properties`** — Merchant locale/currency/feature settings

Priority GUARDED-WRITE candidates (not yet implemented):
- **POST `/v3/merchants/{mId}/item_stocks/{itemId}`** — Update stock quantity (with `expected_current_quantity` pre-check)
- **POST `/v3/merchants/{mId}/items/{itemId}`** — Update item price/availability (with `expected_current_price_cents` pre-check)
