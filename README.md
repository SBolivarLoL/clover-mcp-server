# clover-mcp

MCP server for the Clover POS REST API — gives AI assistants (Claude, Cursor, etc.) read and safe-write access to a Clover merchant's sales, inventory, orders, customers, and employee shifts.

> **Status:** v0 — skeleton in development. See [docs/endpoints.md](docs/endpoints.md) for the M1 endpoint audit gate.

## What it can do

- Sales summaries and payment reports
- Inventory lookups and low-stock alerts
- Order history and open-order inspection
- Customer search and creation
- Employee shift tracking
- Safe writes: update item prices, set stock quantities, create customers

**What it cannot do (by design):** process refunds, capture payments, void charges, delete records. Those stay in the Clover dashboard.

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
- **`oauth_refresh`** — supply a refresh token + OAuth client credentials; the server auto-refreshes on expiry and persists the new token pair to `CLOVER_TOKEN_STORE` (default: `~/.config/clover-mcp/tokens.json`, mode 0600).

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
| `EMPLOYEES_R` | `list_employees`, `list_shifts`, `list_active_shifts` |

Permission changes on a Clover app require the merchant to reinstall the app.

## Development

```bash
uv pip install -e ".[dev]"
pytest
ruff check src/
mypy src/clover_mcp/
```

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy.

## License

MIT
