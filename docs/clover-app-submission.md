# Clover app submission kit

Everything needed to submit **clover-mcp** as a production Clover app for approval.
Fill the `«placeholders»`; the rest is tailored to this server's actual behaviour.
See [DEPLOY.md → Path to production](DEPLOY.md#path-to-production-sandbox--real-clover-merchants)
for the surrounding process and checklist.

> Reminder: do this only when you have a polished app and (ideally) a first
> merchant lined up. Submitting prematurely gets bounced.

---

## 1. App identity

| Field | Value |
|---|---|
| App name | «clover-mcp» (or a merchant-friendly name, e.g. "AI Assistant for Clover") |
| Tagline | Talk to your Clover data — sales, inventory, orders, customers — from any AI assistant. |
| Category | Reporting / Business tools |
| Pricing | «free / subscription» |
| Support email | «mikeldev62@gmail.com» |
| Support phone + hours | «+1 …», «Mon–Fri 9–5 CT» (Clover requires a real phone + hours) |
| Website / privacy policy | «https://…» |

## 2. App description (App Market listing)

**Short (1–2 lines):**
> Connect your Clover account to an AI assistant (Claude, Cursor, ChatGPT, and
> other MCP clients) to ask about sales, inventory, orders, and customers — and
> make safe, confirmed changes — all in plain language.

**Long:**
> clover-mcp is a Model Context Protocol (MCP) server that gives an AI assistant
> secure, read-mostly access to your Clover merchant data. Ask "how did we do this
> week?", "what's low on stock?", or "look up this customer" and get answers drawn
> live from your Clover account. It can also make a small set of **guarded** changes
> — update a price or stock level, create an item/category/customer, open an order —
> each of which previews first and requires your explicit confirmation before it
> writes. Sensitive data (payment card numbers, employee PINs, bank/account numbers)
> is never returned. The app **cannot** capture payments, issue refunds, void
> transactions, or delete records — those stay in your Clover dashboard.

## 3. Points of integration (list on the submission form)

Read: Merchant profile & properties, Orders & line items, Payments & refunds,
Inventory (items, stock, categories, modifiers, taxes, discounts, tags, attributes,
item groups), Devices, Tenders, Order types, Opening hours, Cash events, Tip
suggestions, Service charge, Customers, Employees/roles/shifts.
Write (guarded): create/update customer, create item/category, set item price,
set item stock, create order, add line item.
**Not used:** Sale, Auth, Void, Refund, Payment capture, any delete.

## 4. Permission justifications (paste per requested permission)

Request only what you ship. Read-only deployments need no `*_W` scopes.

| Scope | Justification |
|---|---|
| `MERCHANT_R` | Read merchant profile, devices, tenders, order types, opening hours, cash events, tip presets, and service-charge config for reporting and setup display. |
| `INVENTORY_R` | Read items, stock, categories, modifiers, taxes, tags, attributes, and discounts to answer inventory and catalog questions. |
| `ORDERS_R` | Read orders, line items, and best-sellers for order history and sales analysis. |
| `PAYMENTS_R` | Read payments and refunds to produce sales summaries and reconciliation. |
| `CUSTOMERS_R` | Look up customers by name/phone/email for service and marketing. Payment card data is never read. |
| `EMPLOYEES_R` *(optional)* | Read employees, roles, and shifts for staffing reports. |
| `INVENTORY_W` | Update item price/stock and create items/categories — each guarded by dry-run preview, explicit confirmation, and an optimistic-lock check. |
| `CUSTOMERS_W` | Create/update customer records — guarded by duplicate detection and confirmation. |
| `ORDERS_W` | Create orders and add line items — guarded by confirmation; never captures payment. |

**Selling point for the reviewer:** the app requests **no** payment-capture/refund/
void scopes and performs **no** deletes. Card data, PINs, and bank/account numbers
are stripped by an allowlist before anything leaves the server (contract-tested).

## 5. Functional walkthrough video (script)

Clover wants a short screen recording that shows the app working end-to-end. Record
against a **sandbox test merchant**. Target 2–4 minutes. Suggested scenes:

1. **Intro (0:00–0:20)** — "This is clover-mcp, an MCP server that connects a Clover
   merchant to an AI assistant. I'll connect it and run a few real queries and one
   guarded change." Show the assistant/client with the Clover server connected.
2. **OAuth install/connect (0:20–0:50)** — Show a merchant authorizing the app via
   Clover OAuth (the consent screen listing the requested permissions), then the
   client showing the tools are available.
3. **Read query (0:50–1:30)** — Ask "How did we do today?" → show `get_sales_summary`
   returning gross/net/refunds/tips/tax. Then "What's low on stock?" → `list_low_stock_items`.
4. **Customer lookup (1:30–2:00)** — "Look up customer «name»" → `search_customers` /
   `get_customer`; point out **no card data** is shown.
5. **Guarded write (2:00–2:50)** — "Set the price of «item» to $«X»." Show the
   **dry-run preview**, then the **confirmation prompt**, then the applied change and
   a follow-up read confirming the new price. Emphasize the optimistic-lock guard.
6. **What it won't do (2:50–3:10)** — State on camera: "It cannot capture payments,
   refund, void, or delete records — those stay in the Clover dashboard." Optionally
   show a refund request being declined by design.
7. **Close (3:10–end)** — Support contact + recap.

Tips: narrate each permission as it's exercised (reviewers map the video to your
permission justifications); keep the merchant test data realistic; no real card data
on screen (there is none — but say so).

## 6. Pre-submission checklist

- [ ] Production developer account approved (ID + proof of address).
- [ ] Production app created; **REST Configuration → Default OAuth Response = Code**; OAuth redirect URL set.
- [ ] Only the permissions above enabled, each with its justification pasted in.
- [ ] Support phone + hours and support email set.
- [ ] Privacy policy URL live (covers what data is accessed and how it's handled).
- [ ] Functional video recorded against a sandbox test merchant and uploaded.
- [ ] App description + points of integration entered.
- [ ] Verified an unauthenticated request to the hosted endpoint is rejected (401).
- [ ] Multi-tenant: confirmed cross-merchant isolation (a token for merchant A cannot read merchant B) — see docs/SECURITY.md.

## 7. Notes for reviewers (optional cover note)

> clover-mcp is an independent MCP server (not affiliated with Clover/Fiserv; "Clover"
> used nominatively). It is read-mostly with a small set of confirmation-gated writes,
> requests no payment or delete scopes, and strips card/PIN/bank data via a tested
> allowlist. Source and security notes: «repo URL» / docs/SECURITY.md.
