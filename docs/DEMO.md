# 5-minute technical demo

Two ways to demo clover-mcp: a **runnable script** (fastest) and a **narrated
walkthrough** for a live session or screen recording.

## Option A — runnable demo (30 seconds)

```bash
uv run python scripts/demo.py
```

Narrates a real operator session against your sandbox — merchant, today's sales,
low stock, catalog, a customer lookup, and a **dry-run price change** — all
read-only or dry-run, so nothing is mutated. Sample output:

```
▶ 1. Who am I connected to?  get_merchant_info
    merchant: {"name": "USA bbq test", "currency": "USD", ...}
▶ 2. How did we do today?  get_sales_summary
    sales: {"gross_sales": {"formatted": "$0.00"}, "net_sales": {"formatted": "$0.00"}, ...}
▶ 6. Change a price — safely  set_item_price_cents(dry_run=True)
    dry_run: {"ok": true, "would_put_body": {"name": "…", "price": 525}}
```

## Option B — narrated walkthrough (~5 minutes, for a recording)

Run against a **sandbox** merchant from any MCP client (Claude Desktop, Cursor).
See [DEPLOY.md](DEPLOY.md) / the README for connecting the client.

| Time | Scene | Say / show |
|---|---|---|
| 0:00–0:30 | **Intro** | "clover-mcp connects a Clover merchant to an AI assistant. Reads are safe by default; writes are guarded; no payment rails." Show the client with the Clover server connected and its tools listed. |
| 0:30–1:30 | **Reporting** | Ask: *"How did we do this week?"* → `get_sales_summary` returns gross/net/refunds/tips/tax. Then *"What sold best?"* → `get_top_items`. Point out money is formatted from the merchant's currency, never defaulted. |
| 1:30–2:30 | **Inventory** | *"What's low on stock?"* → `list_low_stock_items`. *"Show me the drinks category"* → `list_items`. Note pagination + allowlist shaping (lean fields only). |
| 2:30–3:15 | **Customers (privacy)** | *"Look up customer Jane"* → `search_customers` / `get_customer`. **Emphasize: no card data is ever returned** — the allowlist strips it (show the response has no `cards`/PAN). |
| 3:15–4:15 | **A guarded write** | *"Set the price of the latte to $5.25."* Show the **dry-run preview** first, then the **confirmation prompt** (MCP elicitation), then the applied change and a follow-up read confirming it. Call out the optimistic-lock pre-check (refuses on stale data). |
| 4:15–4:45 | **What it won't do** | State on camera: *"It can't capture payments, refund, void, or delete — those stay in the Clover dashboard."* Optionally show a refund request declined by design. |
| 4:45–5:00 | **Observability** | `CLOVER_LATENCY_LOG=true` shows per-call latency; writes emit an audit line; OTel spans with the `otel` extra. Close on the [architecture diagram](ARCHITECTURE.md). |

## What to emphasize

- **Safe by default** — allowlist shaping (no card/PII/PIN leakage), read-mostly.
- **Guarded writes** — dry-run + confirmation + optimistic-lock + bounds; no
  payment rails, no deletes.
- **Production-shaped** — OAuth 2.1 resource server, multi-tenant isolation, audit
  logging, optional distributed tracing, and a published [eval](eval.md) (28/28).

See also: [ARCHITECTURE.md](ARCHITECTURE.md) · the app-submission
[functional-video script](clover-app-submission.md#5-functional-walkthrough-video-script).
