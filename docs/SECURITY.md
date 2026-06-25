# Security

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md): report privately to **mikeldev62@gmail.com**
(not a public issue). Acknowledgement within 72 hours.

---

## Hardening before hosting real merchants (multi-tenant)

Single-merchant stdio/`uvx` use (one operator, one token) needs none of this.
The checklist below applies when **one deployment serves several merchants**
(`CLOVER_MULTI_MERCHANT=true`), where one merchant must never see another's data.

Legend: ✅ enforced in code · ⚙️ operator action required · 📋 process/legal.

### 1. ✅ Forwarded-header identity is fail-closed

A gateway platform (FastMCP Cloud / Horizon) authenticates the **user** at the
edge and forwards their identity as an HTTP header (e.g. `horizon-user-email`),
which `CLOVER_TENANT_HEADER` uses to pick the merchant. **This is only safe if
the gateway strips any client-supplied copy of that header.** If it doesn't, a
client can send `horizon-user-email: victim@example.com` and read/write that
merchant's data — a cross-tenant authorization bypass.

When `CLOVER_TENANT_HEADER` is set without `CLOVER_TRUST_IDENTITY_HEADER=true`, the
server **boots but fails closed on every data call** — `request_tenant_key` refuses
to resolve a tenant, so no tool returns merchant data. It deliberately does **not**
hard-fail at startup, because `whoami` must stay reachable to run the spoofing test
below. It also logs a startup WARNING. Set `CLOVER_TRUST_IDENTITY_HEADER=true` only
after the test passes.

#### ⚙️ The header-spoofing test (run before setting the trust flag)

1. Deploy with multi-tenant config but **without** `CLOVER_TRUST_IDENTITY_HEADER`.
   The server boots and `whoami` works (data tools fail closed — that's fine; you
   only need `whoami`).
2. From an **external** MCP client (MCP Inspector), connect through the real
   gateway and call `whoami` while injecting a forged header:
   `horizon-user-email: spoof@test.invalid`.
3. Inspect the result:
   - If `resolved_tenant_key` / `identity_headers` comes back as
     `spoof@test.invalid` → **the gateway is NOT stripping it. STOP.** Do not set
     `CLOVER_TRUST_IDENTITY_HEADER`. Switch to validated-JWT identity (below).
   - If your forged value is gone (only the gateway's real value remains) → the
     gateway strips client headers. You may set `CLOVER_TRUST_IDENTITY_HEADER=true`.

`whoami` echoes this procedure in its `spoofing_check` field whenever header
routing is configured.

### 2. ⚙️ Prefer cryptographic identity over forwarded headers

A self-hosted resource server that **validates the JWT itself**
(`CLOVER_TRANSPORT=http` + `CLOVER_TENANT_CLAIM` against your IdP's JWKS) is
stronger than trusting any gateway header — there is no header to spoof. Prefer
this for new multi-tenant deployments; use header routing only on a managed
platform whose gateway you've verified strips client headers.

### 3. ✅/⚙️ Per-tenant credential isolation

Don't keep every merchant's plaintext token in one `CLOVER_TENANTS_JSON` blob.
Each tenant entry may instead **reference its token by env-var name**, so each
merchant's secret is injected individually (k8s/Horizon secret, secret-manager
mount):

```json
{
  "alice@store.com": { "merchant_id": "ABC123", "access_token_env": "CLOVER_TOKEN_ABC123" },
  "bob@store.com":   { "merchant_id": "DEF456", "access_token_env": "CLOVER_TOKEN_DEF456" }
}
```

(`refresh_token_env` works the same way.) The env reference wins over an inline
`access_token`. A missing/empty referenced var fails closed.

- ⚙️ **Encryption at rest:** store these secrets in a managed secret manager
  (AWS Secrets Manager, GCP Secret Manager, Vault) — encrypted, least-privilege,
  audited — not in a plaintext file or a committed env. The token map is the
  crown-jewel: a leak is every merchant's data.
- ⚙️ **Least privilege:** provision each merchant's Clover API token with only
  the scopes the tools need (this server is read-mostly + a few guarded writes;
  it never needs payment-capture/refund scopes).

### 4. ⚙️ Restart-safe credentials

On ephemeral-disk hosts (Horizon) use **permanent dashboard API tokens**
(`auth_mode: "token"`, the default) — `oauth_refresh` single-use rotation can't
survive a restart there. Tokens loaded from env/secret-manager survive restarts;
the on-disk token store does not.

### 5. ⚙️ Consider one deployment per merchant

Multi-tenant is a product decision, not a default. **One deploy = one merchant**
(single-merchant token config) has **zero cross-tenant spoofing surface** and is
the simplest fully-isolated option. Choose multi-tenant only when the operational
savings outweigh the added trust-boundary risk above.

### 6. 📋 Legal / compliance (custodial duties)

Hosting multiple merchants makes you the custodian of their Clover credentials
and their customers' PII. Before going live, confirm with counsel:

- Data-protection obligations (GDPR/CCPA) as a processor of customer PII.
- Clover developer-terms on multi-merchant aggregation and indemnification.
- Updated disclaimers — the bundled ones assume single-merchant operation.

This document is engineering guidance, **not legal advice.**

---

## What the server already does (all modes)

- **Response allowlist shaping** — card data, employee PINs, and merchant
  banking/account numbers are never returned (enforced by `shaping.py` + contract
  tests).
- **Guarded writes** — every write validates, supports `dry_run`, and confirms
  via MCP elicitation (or an explicit `confirm=True`) before mutating; fail-closed
  if unconfirmed.
- **No payment rails** — no payment capture, refunds, voids, charge creation, or
  record deletes, by design.
- **Remote mode is authenticated** — `CLOVER_TRANSPORT=http` refuses to start
  without layer-1 OAuth (JWKS + issuer + public URL).
