# clover-mcp

MCP server for the Clover POS REST API — gives AI assistants (Claude, Cursor, etc.) read and safe-write access to a Clover merchant's sales, inventory, orders, and customers.

> **Status:** v1 candidate — 14 tools, both auth modes, 152 tests. Single-merchant, local (stdio). See [docs/endpoints.md](docs/endpoints.md) for the sandbox-verified endpoint contracts.

> ⚠️ **Independent project — not affiliated with, endorsed by, or sponsored by Clover Network, LLC or Fiserv, Inc.** "Clover" is a trademark of its respective owner and is used here only nominatively to describe interoperability. Provided **as is**, without warranty — see [Legal & disclaimer](#legal--disclaimer).

## What it can do

- Sales summaries and payment reports
- Inventory lookups and low-stock alerts
- Order history and open-order inspection
- Customer search and creation
- Safe writes: update item prices, set stock quantities, create customers

**What it cannot do (by design):** process refunds, capture payments, void charges, delete records. Those stay in the Clover dashboard. Employee/shift reporting and a multi-merchant hosted mode are planned (v1.1 / v2).

## Tools

| Tool | Kind | Notes |
|---|---|---|
| `get_merchant_info` | read | name, currency, timezone, country |
| `get_sales_summary` | read | aggregated window (see [Sales summary semantics](#sales-summary-semantics)) |
| `list_payments` | read | SUCCESS payments in a window |
| `list_orders` / `get_order` / `list_open_orders` | read | order history + detail |
| `list_items` / `get_item` / `list_low_stock_items` | read | inventory + stock |
| `search_customers` / `get_customer` | read | cards never returned |
| `create_customer` | write | additive; idempotency dup-check + `dry_run` |
| `set_item_price_cents` | write | optimistic-lock pre-check, bounds, `dry_run` |
| `set_item_stock_quantity` | write | absolute (not delta), pre-check, `dry_run` |

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
- **`oauth_refresh`** — supply a refresh token + OAuth client credentials; the server auto-refreshes on expiry and persists the new token pair to `CLOVER_TOKEN_STORE` (default: `~/.config/clover-mcp/tokens.json`, mode 0600). Clover refresh tokens are single-use, so the rotated pair is written back after each refresh.

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
| `ORDERS_R` | `list_orders`, `get_order`, `list_open_orders`, `get_sales_summary` |
| `PAYMENTS_R` | `list_payments`, `get_sales_summary` |
| `INVENTORY_R` | `list_items`, `get_item`, `list_low_stock_items` |
| `INVENTORY_W` | `set_item_price_cents`, `set_item_stock_quantity` |
| `CUSTOMERS_R` | `search_customers`, `get_customer` |
| `CUSTOMERS_W` | `create_customer` |

Read scopes (`*_R`) are probed at startup; the server reports any missing ones and exits. Write scopes (`*_W`) are **not** probed (a probe would mutate data) — a missing write scope surfaces as a 403 the first time you call that tool. Permission changes on a Clover app require the merchant to reinstall the app.

## Sales summary semantics

`get_sales_summary` makes the accounting explicit so the LLM can explain it:

- **Gross** = sum of `result=SUCCESS` payment amounts. `FAIL`/`AUTH`/uncaptured `PRE_AUTH` are excluded.
- **Voids and refunds are reported separately** (`void_count`, `refund_count`, `refund_amount`) — never silently netted into `payment_count`.
- **Tips and taxes** are broken out as their own line items.
- **Service charges** are summed from orders (Clover does not expose them on payments) and reported as `service_charges_collected` — requires `ORDERS_R`.
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
