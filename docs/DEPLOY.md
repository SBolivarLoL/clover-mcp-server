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

**Step 1 — discover the identity Horizon gives you.** Horizon authenticates at
its *gateway* and forwards the request to your server, so the identity usually
arrives as an **HTTP header**, not a token. Deploy with:
```
CLOVER_MULTI_MERCHANT=true
CLOVER_TENANTS_JSON={}
```
Connect (Inspector/client) and call the **`whoami`** tool. It returns the request
header *names* and the values of any recognized identity headers (no secrets):
```json
{ "authenticated": false,
  "http_header_names": ["host","x-forwarded-email","x-forwarded-user", ...],
  "identity_headers": {"x-forwarded-email": "you@store.com"} }
```
Pick the header that carries your identity (e.g. `x-forwarded-email`) and set
`CLOVER_TENANT_HEADER` to its name. (If instead `authenticated: true` and you see
`claim_keys`, your platform forwards a token — use `CLOVER_TENANT_CLAIM` and the
`resolved_tenant_key` value.) If `identity_headers` is empty *and* nothing in
`http_header_names` looks like a user identity, the platform isn't forwarding one
— multi-tenant then needs self-hosting (section B), where we control auth.

**Step 2 — provide the tenant map.** Set `CLOVER_TENANT_HEADER` (or
`CLOVER_TENANT_CLAIM`) to the identity source from step 1, then `CLOVER_TENANTS_JSON`
to a JSON object keyed by that identity value, each entry holding the merchant's
**permanent** token:
```
CLOVER_TENANT_HEADER=x-forwarded-email
CLOVER_TRUST_IDENTITY_HEADER=true
CLOVER_TENANTS_JSON={"you@store.com":{"merchant_id":"ABC123","access_token":"<permanent>","sandbox":false,"region":"na"},"other@store.com":{"merchant_id":"XYZ789","access_token":"<permanent>"}}
```
Redeploy. Each authenticated user now transparently gets *their* merchant's data;
an unmapped user is refused (fail-closed). Re-run `whoami` to confirm
`tenant_provisioned: true`.

> ⚠️ **SECURITY — `CLOVER_TRUST_IDENTITY_HEADER` is mandatory for header routing.**
> With `CLOVER_TENANT_HEADER` set but this flag unset, the server boots and `whoami`
> works, but **every data tool fails closed** (no merchant data) and a startup warning
> is logged. A forwarded header can be spoofed unless your gateway strips client-supplied
> copies — **run the header-spoofing test in [docs/SECURITY.md](SECURITY.md) using
> `whoami`, then set `CLOVER_TRUST_IDENTITY_HEADER=true`.** For stronger isolation,
> reference each token via its own env var
> (`{"...":{"merchant_id":"ABC123","access_token_env":"CLOVER_TOKEN_ABC123"}}`)
> instead of inlining tokens, and inject them from a secret manager.

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

Multiple replicas may share one token store on a POSIX filesystem: each refresh
takes an exclusive `flock` on the store and re-reads under the lock, so two
replicas can't both spend the same single-use refresh token. (On Windows, or a
filesystem without working `flock` such as some NFS setups, run a single instance
per token store.)

## Verify after deploy

```bash
# Protected Resource Metadata is public:
curl https://YOUR_PUBLIC_URL/.well-known/oauth-protected-resource/mcp

# An unauthenticated call returns 401 with a WWW-Authenticate pointer to the PRM:
curl -i -X POST https://YOUR_PUBLIC_URL/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Path to production (sandbox → real Clover merchants)

Everything above can run against the **sandbox** with zero cost and no business —
that is the intended development/demo environment, and it's a complete, honest
story for a proof-of-concept. Going to **real** Clover data is a separate axis
from where you host the MCP server, and it has hard prerequisites.

### The reality (why you can't just flip `CLOVER_SANDBOX=false`)

- Sandbox and production are **completely walled off** — separate accounts, no
  data migration, production devices provisioned only through a Clover reseller.
- You **cannot fabricate a production merchant.** Production access is gated on
  real identity verification (passport/ID + proof of address) and, for live
  merchants, an underwritten Clover account.
- **As the developer you don't own the merchant.** You go live by publishing an
  **app that real merchants install** (OAuth); their data, their consent. This
  server already implements that model (OAuth 2.1 resource server + per-tenant
  routing — section B and the multi-tenant notes above).

### Two production credential models

| Model | Fits when | Auth | Clover requirements |
|---|---|---|---|
| **Own-merchant API token** | You run it on **your own** Clover business | `CLOVER_AUTH_MODE=token`, paste the token | A real Clover merchant account you control; generate a token in the Dashboard. No app review. |
| **OAuth app** | You serve **other** merchants / want App Market distribution | `CLOVER_AUTH_MODE=oauth_refresh` (or hosted-platform auth) | A **production developer account** + a **production app** that passes Clover's **app approval**. |

If you don't have a business, the OAuth-app model is your only path to real data.

### Actionable checklist (OAuth-app path)

- [ ] **1. Create a Global Developer account** — one login for both sandbox and
      production, switchable from one dashboard. Free; the foundation for
      everything else. ([global platform](https://docs.clover.com/dev/docs/global-developer-platform-get-started))
- [ ] **2. Keep building/validating in sandbox** — you are here. Prove the app
      works against test merchants before any approval. ([test merchants](https://docs.clover.com/dev/docs/use-test-merchants-dashboard))
- [ ] **3. Get the production developer account approved** — submit individual/
      corporate info, a valid ID, and proof of address. ([approval](https://docs.clover.com/dev/docs/approval), [developer accounts](https://docs.clover.com/dev/docs/developer-accounts))
- [ ] **4. Create a production app** — in REST Configuration set the Default OAuth
      Response to **Code**, set the OAuth redirect URL, and declare the permissions
      below. ([create a production app](https://docs.clover.com/dev/docs/creating-a-production-app))
- [ ] **5. Submit the app for approval** — Clover requires a **functional
      walkthrough video**, an **in-line justification per requested permission**
      (table below), and a **support phone + hours**. ([approval](https://docs.clover.com/dev/docs/approval))
- [ ] **6. First merchant installs it** — OAuth issues *their* tokens; route by
      the authenticated identity (multi-tenant) or run one deploy per merchant.
- [ ] **7. Flip config to production** — `CLOVER_SANDBOX=false`, set the correct
      `CLOVER_REGION` (`na`/`eu`/`la`), and supply the merchant's production
      credentials. Verify with `get_merchant_info` returning the real business.

> ⚠️ **Don't submit for approval prematurely.** Approval expects a real,
> demonstrable app (the video + permission justifications are real work). Do
> step 1 now; do steps 3–5 only when you have a polished app and ideally a first
> merchant lined up — the gap to "real" is *one willing merchant + app approval*,
> not a business of your own.

### Permission justifications for this server (ready for app submission)

Request **only** the scopes for the tools you ship (read-only deployments need no
`*_W`). Each line is a paste-ready justification for the approval form:

| Scope | Justification (what the app does with it) |
|---|---|
| `MERCHANT_R` | Read merchant profile, devices, tenders, order types, opening hours, cash events, tip presets, and service-charge config for reporting and setup display. |
| `INVENTORY_R` | Read items, stock, categories, modifiers, taxes, tags, attributes, and discounts to answer inventory and catalog questions. |
| `ORDERS_R` | Read orders, line items, and best-sellers for order history and sales analysis. |
| `PAYMENTS_R` | Read payments and refunds to produce sales summaries and reconciliation. |
| `CUSTOMERS_R` | Look up customers by name/phone/email (card data never read). |
| `EMPLOYEES_R` *(optional)* | Read employees, roles, and shifts for staffing reports. |
| `INVENTORY_W` | Update item price/stock and create items/categories — guarded by dry-run, confirmation, and optimistic-lock pre-checks. |
| `CUSTOMERS_W` | Create/update customer records — guarded by duplicate-check and confirmation. |
| `ORDERS_W` | Create orders and add line items — guarded by confirmation; never captures payment. |

> This server **never** requests payment-capture/refund/void scopes and exposes
> no deletes — call that out in the submission; narrow scopes speed up approval.

> 📋 **Full submission kit** — app description, points of integration, a
> scene-by-scene functional-video script, and a pre-submission checklist:
> [docs/clover-app-submission.md](clover-app-submission.md).

### Recommendation

For now, **stay on sandbox** — the server is fully validated there and it's a
legitimate demo (just label it as sandbox-backed). When you're ready to make it a
real product, do checklist step 1 today (free, unblocks everything), and pursue
steps 3–6 once you have a first merchant or a submission-ready app.

Sources: [Clover environments](https://docs.clover.com/dev/docs/clover-environments) ·
[Production developer accounts](https://docs.clover.com/dev/docs/developer-accounts) ·
[Account & app approval](https://docs.clover.com/dev/docs/approval) ·
[Create a production app](https://docs.clover.com/dev/docs/creating-a-production-app) ·
[Test merchants](https://docs.clover.com/dev/docs/use-test-merchants-dashboard) ·
[Global developer platform](https://docs.clover.com/dev/docs/global-developer-platform-get-started)

## Still local? Do nothing.

`uvx clover-mcp` (stdio, single merchant) is unchanged and needs none of the
above.
