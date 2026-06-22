# Remote / hosted deployment (v2)

The default install is **local stdio, single merchant** — nothing here is
required for that. This guide is for running clover-mcp as a **network-reachable
HTTP server** that multiple merchants connect to, with OAuth.

clover-mcp is an OAuth 2.1 **resource server**: it validates bearer tokens
issued by *your* Identity Provider and never sees user credentials. FastMCP
handles token validation and serves Protected Resource Metadata (RFC 9728);
this server adds per-merchant routing on top.

```
MCP client ──token──> clover-mcp (resource server) ──validates JWT──> your IdP (JWKS)
                            │
                            └─ merchant id from token claim ─> merchant store ─> Clover API
```

## What you must decide / provide

1. **A host** with a public HTTPS URL (Fly.io, Render, Cloud Run, Railway, a
   VPS behind a TLS proxy…). That URL is `CLOVER_PUBLIC_URL` — the OAuth
   *resource* identity. TLS is mandatory.
2. **An Identity Provider** (the Authorization Server). FastMCP ships providers
   for Auth0, Clerk, WorkOS, AWS Cognito, Azure, Keycloak, Google, Descope,
   Supabase, Scalekit, PropelAuth. Create an API/app there and note its
   **issuer**, **JWKS URI**, and the **audience** you'll mint tokens for.
3. **A merchant claim**: configure the IdP to put each user's Clover merchant id
   into a token claim (default name `clover_merchant_id`). This is how a request
   is bound to one merchant's data.
4. **A distributable Clover app** + a place to store each merchant's Clover
   refresh token (the merchant store — see below). Each merchant installs your
   Clover app once; you record their token.

## Environment variables

| Var | Required (http) | Meaning |
|---|---|---|
| `CLOVER_TRANSPORT` | yes | set to `http` |
| `CLOVER_PUBLIC_URL` | yes | this server's public https URL, e.g. `https://mcp.acme.com` |
| `CLOVER_AUTH_ISSUER` | yes | your IdP issuer URL (advertised in PRM) |
| `CLOVER_AUTH_JWKS_URI` | yes | your IdP JWKS endpoint (token signature keys) |
| `CLOVER_AUTH_AUDIENCE` | recommended | expected token audience |
| `CLOVER_AUTH_SCOPES` | optional | required scopes, space/comma separated |
| `CLOVER_MULTI_MERCHANT` | for SaaS | `true` to route by token claim |
| `CLOVER_MERCHANT_CLAIM` | optional | claim holding the merchant id (default `clover_merchant_id`) |
| `CLOVER_MERCHANT_STORE` | multi-merchant | path to the per-merchant credentials JSON |
| `CLOVER_HTTP_HOST` / `CLOVER_HTTP_PORT` / `CLOVER_HTTP_PATH` | optional | bind address / port / path (defaults `127.0.0.1` / `8000` / `/mcp`) |

The server **refuses to start** in http mode unless `CLOVER_AUTH_JWKS_URI`,
`CLOVER_AUTH_ISSUER`, and `CLOVER_PUBLIC_URL` are all set — a remote MCP server
must not run unauthenticated.

## Merchant store

`CLOVER_MERCHANT_STORE` points at a JSON file keyed by Clover merchant id:

```json
{
  "MERCHANTID1": {
    "access_token": "...",
    "refresh_token": "...",
    "oauth_client_id": "...",
    "oauth_client_secret": "...",
    "auth_mode": "oauth_refresh",
    "region": "na",
    "sandbox": false
  }
}
```

Rotated refresh tokens are written to `tokens-<merchantId>.json` next to this
file, so single-use rotation stays isolated per merchant. A flat file is fine
for a handful of merchants; swap `MerchantStore` in `remote.py` for a database
or secret-manager lookup when you outgrow it (only `.get()` is called).

## Verify after deploy

```bash
# Protected Resource Metadata is public:
curl https://YOUR_PUBLIC_URL/.well-known/oauth-protected-resource/mcp

# An unauthenticated call returns 401 with a WWW-Authenticate pointer to the PRM:
curl -i -X POST https://YOUR_PUBLIC_URL/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Still local? Do nothing.

`uvx clover-mcp` (stdio, single merchant) is unchanged and needs none of the
above.
