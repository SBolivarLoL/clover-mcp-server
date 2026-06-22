# Remote / hosted deployment (v2)

The default install is **local stdio, single merchant** — nothing here is
required for that. There are two ways to run it remotely:

- **A. FastMCP Cloud / Horizon (recommended)** — the platform handles OAuth,
  HTTPS, and transport for you. Your server just exposes the tools. **Use this
  unless you need self-hosting.**
- **B. Self-host with your own IdP** — you run the HTTP server and clover-mcp
  acts as an OAuth 2.1 resource server validating your IdP's tokens.

---

## A. FastMCP Cloud / Horizon (managed auth)

Horizon runs `fastmcp run <entrypoint>` and provides **built-in OAuth** — enable
authentication during setup so only authenticated users in your org can connect.
You do **not** configure an IdP and you do **not** set any `CLOVER_AUTH_*`,
`CLOVER_TRANSPORT`, or `CLOVER_PUBLIC_URL` vars — the platform owns auth/transport.

```
Entrypoint:   server.py:mcp        (or src/clover_mcp/server.py:mcp)
Requirements: pyproject.toml
```

> ⚠️ Do **not** use `server.py:create_server` on Horizon, and do **not** set
> `CLOVER_TRANSPORT=http`. Those build *our own* resource-server auth, which
> requires an IdP you don't have on Horizon — **the server will fail to start.**
> `create_server` is only for self-hosting (section B).

> ⚠️ **Turn Horizon's authentication ON.** Raw MCP-over-HTTP is public by default;
> the platform only protects the endpoint if you enable its auth. After deploy,
> verify an unauthenticated request to `https://<your>.fastmcp.app/mcp` is rejected.

**Environment Variables** (single merchant — your own business):

```
CLOVER_MERCHANT_ID=<your Clover merchant id>
CLOVER_ACCESS_TOKEN=<long-lived Clover API token>
CLOVER_AUTH_MODE=token
CLOVER_REGION=na          # na | eu | la
CLOVER_SANDBOX=false      # true while testing against the sandbox
```

> **Ephemeral filesystem.** Horizon containers don't persist disk between
> restarts. Prefer `CLOVER_AUTH_MODE=token` (a long-lived token, no disk needed).

### Multi-tenant on Horizon (many merchants, one deploy)

Horizon's auth identifies the *user* who connects, not a Clover merchant — so
multi-tenant works by **mapping each authenticated user → their Clover merchant**.
The map lives in an **env var** (Horizon env survives restarts; the disk doesn't),
and each merchant uses a **permanent API token** (no refresh-to-disk needed).

**Step 1 — discover the identity Horizon gives you.** Deploy with:
```
CLOVER_MULTI_MERCHANT=true
CLOVER_TENANTS_JSON={}
```
Connect (Inspector/client) and call the **`whoami`** tool. It returns the
authenticated identity and the *names* of available claims (no secrets), e.g.:
```json
{ "authenticated": true, "subject": "...", "claim_keys": ["email","sub",...],
  "tenant_key_source": "email→subject", "resolved_tenant_key": "you@store.com" }
```
That `resolved_tenant_key` is what you key the tenant map on. If you'd rather key
on a different claim, set `CLOVER_TENANT_CLAIM=<claim_name>`.

**Step 2 — provide the tenant map.** Set `CLOVER_TENANTS_JSON` to a JSON object
keyed by that identity, each entry holding the merchant's **permanent** token:
```
CLOVER_TENANTS_JSON={"you@store.com":{"merchant_id":"ABC123","access_token":"<permanent>","sandbox":false,"region":"na"},"other@store.com":{"merchant_id":"XYZ789","access_token":"<permanent>"}}
```
Redeploy. Each authenticated user now transparently gets *their* merchant's data;
an unmapped user is refused (fail-closed). Re-run `whoami` to confirm
`tenant_provisioned: true`.

> Don't set `CLOVER_TRANSPORT` or `CLOVER_AUTH_*` for this — Horizon owns auth.
> A flat env blob is fine for a handful of merchants; for many, swap `load_tenants`
> in `remote.py` for a database/secret-manager lookup (same `{key: entry}` shape).

---

## B. Self-host with your own IdP

clover-mcp is an OAuth 2.1 **resource server**: it validates bearer tokens issued
by *your* Identity Provider and never sees user credentials. FastMCP handles token
validation and serves Protected Resource Metadata (RFC 9728); this server adds
per-merchant routing on top. Use entrypoint `server.py:create_server` (fail-closed
— refuses to start without an IdP).

```
MCP client ──token──> clover-mcp (resource server) ──validates JWT──> your IdP (JWKS)
                            │
                            └─ merchant id from token claim ─> merchant store ─> Clover API
```

### What you must decide / provide

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
