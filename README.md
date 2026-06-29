# clover-mcp

MCP server for the Clover POS REST API — gives AI assistants (Claude, Cursor, etc.) read and safe-write access to a Clover merchant's sales, inventory, orders, and customers.

<!-- mcp-name: io.github.SBolivarLoL/clover-mcp -->

> **Status:** v0.5.0 — 47 tools, 6 prompts, both auth modes, 233 tests. Runs locally (stdio, single merchant) or remotely over HTTP with OAuth, single- or multi-tenant (see [docs/DEPLOY.md](docs/DEPLOY.md)). Endpoint contracts are sandbox-verified in [docs/endpoints.md](docs/endpoints.md).

> ⚠️ **Independent project — not affiliated with, endorsed by, or sponsored by Clover Network, LLC or Fiserv, Inc.** "Clover" is a trademark of its respective owner and is used here only nominatively to describe interoperability. Provided **as is**, without warranty — see [Legal & disclaimer](#legal--disclaimer).

## What it can do

- Sales summaries, payment and refund reports
- Inventory lookups and low-stock alerts
- Order history and open-order inspection
- Customer search and creation
- Employee, shift, role, category, modifier, tax, tender, and device lookups; best-selling items
- Pricing config lookups: discount catalogue, tip-suggestion presets, default service charge
- Safe writes: update item prices, set stock quantities, create customers/items/categories/orders, add line items, update customers
- AI tools (reason via your client's model — the server holds no LLM key): sales briefings, reorder suggestions, anomaly detection, category suggestions, customer-message drafts
- Predefined prompt workflows: daily briefing, weekly sales report, inventory health check, end-of-day closeout, customer lookup, monthly tax summary

**What it cannot do (by design):** process refunds, capture payments, void charges, delete records. Those stay in the Clover dashboard.

## Tools

| Tool | Kind | Notes |
|---|---|---|
| `get_merchant_info` / `get_merchant_properties` | read | profile + POS config (banking fields never returned) |
| `get_sales_summary` | read | aggregated window (see [Sales summary semantics](#sales-summary-semantics)) |
| `list_payments` / `list_refunds` / `list_tenders` | read | payments, refunds, tender types |
| `list_orders` / `get_order` / `list_open_orders` / `list_order_types` | read | order history + detail |
| `list_items` / `get_item` / `list_low_stock_items` | read | inventory + stock |
| `list_categories` / `list_modifiers` / `list_taxes` / `list_item_groups` / `list_attributes` / `list_tags` / `list_discounts` | read | catalog structure |
| `list_tip_suggestions` / `get_default_service_charge` | read | tip presets + service-charge config |
| `list_devices` / `list_opening_hours` / `list_cash_events` | read | terminals, hours, cash-drawer log |
| `get_top_items` | read | best-sellers by units in a window |
| `list_employees` / `get_employee` / `list_shifts` / `list_active_shifts` / `list_roles` | read | PINs never returned (`EMPLOYEES_R`) |
| `search_customers` / `get_customer` | read | cards never returned |
| `whoami` | read | multi-tenant identity diagnostic (no secrets) |
| `summarize_sales` / `inventory_reorder_suggestions` / `detect_sales_anomalies` / `suggest_item_categories` / `draft_customer_message` | AI | reason via your client's model; read-only suggestions |
| `create_customer` / `update_customer` | write | dup-check + `dry_run`; update confirms via elicitation |
| `create_item` / `create_category` / `create_order` / `add_line_item` | write | guarded: `dry_run` + confirm before writing |
| `set_item_price_cents` / `set_item_stock_quantity` | write | optimistic-lock pre-check, bounds, `dry_run` |

Every tool carries MCP behaviour annotations (`readOnlyHint` / `destructiveHint` / `idempotentHint`) so clients can parallelize reads and prompt before writes.

## Install

```bash
uvx clover-mcp   # coming soon after PyPI publish
```

Or from source:

```bash
git clone https://github.com/SBolivarLoL/clover-mcp-server
cd clover-mcp-server
uv pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required:

| Variable | Description |
|---|---|
| `CLOVER_MERCHANT_ID` | Your Clover merchant ID |
| `CLOVER_ACCESS_TOKEN` | Your Clover API access token |

Optional:

| Variable | Default | Description |
|---|---|---|
| `CLOVER_REGION` | `na` | `na`, `eu`, or `la` |
| `CLOVER_SANDBOX` | `false` | `true` to use the Clover sandbox |
| `CLOVER_AUTH_MODE` | `token` | `token` or `oauth_refresh` |

### Auth modes

- **`token`** — paste a static access token. Works for sandbox and single-merchant production use. If the token expires, regenerate it in the Clover Developer Dashboard.
- **`oauth_refresh`** — the server auto-refreshes on expiry and persists the new token pair to `CLOVER_TOKEN_STORE` (default: `~/.config/clover-mcp/tokens.json`, mode 0600). Clover refresh tokens are single-use, so the rotated pair is written back after each refresh. Run `scripts/get_sandbox_token.py` to obtain tokens — it writes them straight to the store, so you only set `CLOVER_AUTH_MODE`, `CLOVER_OAUTH_CLIENT_ID`, `CLOVER_OAUTH_CLIENT_SECRET`, and `CLOVER_MERCHANT_ID` in `.env` (no token values needed). Pasting `CLOVER_ACCESS_TOKEN` / `CLOVER_REFRESH_TOKEN` into `.env` still works as an alternative.

> **Use a least-privilege token.** Grant only the permission scopes the tools you actually use require (see the table below). A read-only deployment needs no `*_W` scopes at all. Don't reuse a production token in sandbox or vice versa.

## Claude Desktop setup

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "clover": {
      "command": "uvx",
      "args": ["clover-mcp"],
      "env": {
        "CLOVER_MERCHANT_ID": "your_merchant_id",
        "CLOVER_ACCESS_TOKEN": "your_token",
        "CLOVER_REGION": "na"
      }
    }
  }
}
```

## Cursor setup

Add to `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` globally):

```json
{
  "mcpServers": {
    "clover": {
      "command": "uvx",
      "args": ["clover-mcp"],
      "env": {
        "CLOVER_MERCHANT_ID": "your_merchant_id",
        "CLOVER_ACCESS_TOKEN": "your_token"
      }
    }
  }
}
```

## Required Clover permissions

Your token must have the following Clover permission scopes:

| Permission | Used by |
|---|---|
| `MERCHANT_R` | `get_merchant_info` |
| `ORDERS_R` | `list_orders`, `get_order`, `list_open_orders` |
| `PAYMENTS_R` | `list_payments`, `get_sales_summary` (payments + refunds) |
| `ORDERS_R` | …also `get_top_items` |
| `INVENTORY_R` | `list_items`, `get_item`, `list_low_stock_items`, `list_categories`, `list_modifiers`, `list_taxes`, `list_discounts` |
| `INVENTORY_W` | `set_item_price_cents`, `set_item_stock_quantity` |
| `CUSTOMERS_R` | `search_customers`, `get_customer` |
| `CUSTOMERS_W` | `create_customer` |
| `EMPLOYEES_R` | `list_employees`, `get_employee`, `list_shifts`, `list_active_shifts` (optional) |
| `MERCHANT_R` | …also `list_devices`, `list_tenders`, `list_order_types`, `list_opening_hours`, `list_cash_events`, `list_tip_suggestions`, `get_default_service_charge` |

Read scopes (`*_R`) are probed at startup; the server **warns** about any missing ones (it no longer exits — a hosted server must still start) and the affected tools return a 403 when called. `EMPLOYEES_R` is optional. Write scopes (`*_W`) are **not** probed (a probe would mutate data) — a missing write scope surfaces as a 403 the first time you call that tool. Permission changes on a Clover app require the merchant to reinstall the app.

## Remote / hosted (v2)

By default this runs locally over stdio for a single merchant. To run it remotely:

- **FastMCP Cloud / Horizon (easiest):** deploy with entrypoint `server.py:mcp`,
  enable the platform's built-in auth, and set single-merchant Clover env vars.
  The platform handles OAuth, HTTPS, and transport — no IdP setup, and do **not**
  set `CLOVER_TRANSPORT`/`CLOVER_AUTH_*` (that path needs an IdP and will fail).
- **Self-host:** use `server.py:create_server`, which makes clover-mcp an OAuth
  2.1 **resource server** (validates your IdP's JWTs, publishes Protected Resource
  Metadata per RFC 9728, routes by token claim) and **refuses to start without an
  IdP** so it can't run open.

Full setup for both in **[docs/DEPLOY.md](docs/DEPLOY.md)**.

## Sales summary semantics

`get_sales_summary` makes the accounting explicit so the LLM can explain it:

- **Gross** = sum of `result=SUCCESS` payment amounts. `FAIL`/`AUTH`/uncaptured `PRE_AUTH` are excluded.
- **Refunds** come from the dedicated `/refunds` endpoint (Clover refunds are separate objects with a positive amount, not negative payments). **Voids** are counted from voided payments. Both are reported separately (`refund_count`/`refund_amount`, `void_count`) — never netted into `payment_count`. `net_sales = gross_sales - refund_amount`.
- **Tips and taxes** are broken out as their own line items.
- **Service charges** are *not* reported separately: Clover exposes them on the order only as a percentage (no computed amount), and what customers actually paid is already in `gross_sales` via payment totals.
- **Offline payments** are included; a `note` flags the window when any are present.
- **Currency** comes from the merchant record, never defaulted.
- Windows longer than 90 days are split and concatenated transparently.

## Development

```bash
uv pip install -e ".[dev]"
pytest
ruff check src/
mypy src/clover_mcp/
```

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy.

## Legal & disclaimer

> This is not legal advice. The notes below describe the project's intent and the
> operator's responsibilities.

- **Not affiliated.** This is an independent, community project. It is **not**
  affiliated with, endorsed by, or sponsored by Clover Network, LLC or Fiserv, Inc.
  "Clover" and related marks are trademarks of their respective owners and are used
  here only **nominatively** — to state that this software interoperates with the
  Clover REST API. No Clover logos or branding are used.
- **No warranty / no liability.** The software is provided **"AS IS"** under the
  [MIT License](LICENSE), without warranty of any kind. The authors are not liable
  for any claim, damage, or loss arising from its use — including incorrect data,
  unintended writes, downtime, or API changes outside the authors' control.
- **You operate it; you're responsible.** You run this server with **your own**
  Clover account and API credentials. You are solely responsible for: complying
  with Clover's developer/API terms and trademark-usage policy; safeguarding your
  tokens; and meeting any data-protection (e.g. GDPR/CCPA) and tax obligations for
  data you access. The write tools **modify live merchant data** — test in the
  sandbox first and use least-privilege tokens.
- **No card data, no payments.** The server never handles payment card data (the
  shaping layer blocks it) and deliberately cannot capture payments, refund, or
  void. It is **not** a PCI-DSS solution.
- **Third-party API.** This project only calls Clover's public REST API using the
  operator's credentials; it bundles no Clover SDK or proprietary code. Clover may
  change or restrict its API at any time, which may break functionality.

## License

MIT — see [LICENSE](LICENSE).
