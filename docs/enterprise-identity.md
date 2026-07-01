# Enterprise identity: SSO/SAML, SCIM, audit & multi-tenant authorization

**Where the responsibility sits.** clover-mcp is an OAuth 2.1 **resource server**.
It *consumes* a validated identity and authorizes access to one Clover merchant's
data. It does **not** implement SSO, SAML, or SCIM itself — those belong to your
Identity Provider (Auth0, Okta, Entra ID, WorkOS, Keycloak, …) or the managed
gateway (Prefect Horizon / FastMCP Cloud). This is the correct boundary: an MCP
resource server that re-implemented a SAML stack would be badly over-scoped.

This doc explains how each enterprise-identity concern maps onto what this server
actually does, and how to wire it.

## Responsibility matrix

| Concern | IdP / gateway (above us) | clover-mcp (this server) |
|---|---|---|
| **SSO / SAML / OIDC login** | Authenticate the human; mint a token/assert identity | — |
| **SCIM user provisioning** | Create/update/deprovision users | — |
| **Token issuance** | Issue JWTs (JWKS-signed) | Validate them (JWKS · issuer · audience) |
| **Authorization → merchant** | Put a merchant/tenant claim in the token | Map identity → one Clover merchant, fail-closed |
| **Per-tenant isolation** | — | Enforce it (per-tenant client + credentials) |
| **Audit** | IdP login/audit logs | Audit every write (who/what/when) |

## SSO / SAML

The login method is **transparent** to clover-mcp. Whether the user signs in via
SAML, OIDC, or a social provider, the IdP produces a JWT; this server validates
the JWT signature and claims. Two deployment shapes:

- **Self-host (you validate the JWT).** Configure the OAuth resource server —
  clover-mcp publishes RFC 9728 Protected Resource Metadata and validates every
  request against your IdP's JWKS. SAML-vs-OIDC is an IdP concern; we only see the
  resulting token.
  ```
  CLOVER_TRANSPORT=http
  CLOVER_PUBLIC_URL=https://mcp.example.com
  CLOVER_AUTH_ISSUER=https://idp.example.com/
  CLOVER_AUTH_JWKS_URI=https://idp.example.com/.well-known/jwks.json
  CLOVER_AUTH_AUDIENCE=clover-mcp            # RFC 8707 — bind tokens to this resource
  CLOVER_AUTH_SCOPES="clover.read clover.write"   # optional required scopes
  ```
  (Missing issuer/JWKS/public-URL → the server refuses to start. Missing audience
  → a startup warning; set it.)

- **Managed gateway (Horizon does SSO).** The gateway authenticates the user
  (its own SSO/SAML) and forwards identity as a header. clover-mcp then routes by
  that header — **fail-closed** until you verify the gateway strips client-supplied
  copies. See the header-spoofing test in [SECURITY.md](SECURITY.md).

Verify SSO end-to-end with `whoami`: it echoes the authenticated identity, the
claim names present (never their values), scopes, and whether a tenant is mapped.

## SCIM (user lifecycle → tenant lifecycle)

SCIM provisions and **deprovisions** users in your IdP. clover-mcp doesn't store
users, but it has the analogous object: the **tenant map** (identity → Clover
merchant + credentials), in `CLOVER_TENANTS_JSON` or the merchant store, resolved
per request in [remote.py](../src/clover_mcp/remote.py).

Map SCIM events onto tenant lifecycle:

| SCIM event | Action on clover-mcp |
|---|---|
| User created / assigned the app | Add `{identity: {merchant_id, access_token_env}}` to the tenant map |
| User updated | Update the tenant entry (e.g. rotate the token reference) |
| **User deprovisioned** | **Remove the tenant entry** → the next request fails closed (no tenant → no data). This is the critical security action. |

Because unmapped identities already **fail closed**, an out-of-band deprovision
(remove the mapping) is safe by default. For automation, drive the map from a
secret manager or DB and update it from your SCIM webhook — swap `load_tenants`
in `remote.py` for that lookup (same `{key: entry}` shape). Reference tokens by
env-var name (`access_token_env`) so each merchant's secret is injected and rotated
independently — never inline every token in one blob.

## Multi-tenant authorization (implemented)

This is enforced in code, not aspirational:

- **Tenant derived from the validated identity**, never a client-supplied value.
  `request_tenant_key()` uses the configured claim (`CLOVER_TENANT_CLAIM`), else
  `email`/subject; header routing requires `CLOVER_TRUST_IDENTITY_HEADER=true`.
- **Per-tenant isolation** — a client and token store are built per resolved
  tenant; merchant A's token can never serve merchant B.
- **Fail-closed everywhere** — no identity, no mapping, or an untrusted header →
  the data tools refuse; only `whoami` stays reachable (for setup/testing).
- **Least privilege** — provision each Clover token with only the scopes the tools
  use; this server never needs payment-capture/refund scopes.

Cross-tenant isolation is a first-class test target: a token for tenant A must not
read tenant B's data. See [SECURITY.md](SECURITY.md) for the full hardening
checklist (spoofing test, prefer-JWT-over-header, encryption-at-rest, custodial
duties).

## Audit logging

Every write emits a structured audit record to stderr (`method`, `path`, `status`,
`merchant`) — see [README → Observability](../README.md#observability). Ship stderr
to your log pipeline (CloudWatch, Loki, Datadog) and you have a per-merchant,
per-mutation audit trail. Combine with the IdP's login/audit logs for the full
"who logged in → what they changed" story. Optional OpenTelemetry spans
(`clover.http`) add distributed tracing across the same calls.

## What we deliberately do NOT build

- A SAML/OIDC **identity provider** — use a real IdP.
- A **SCIM server/endpoint** — user provisioning belongs in the IdP; we consume
  the result via the tenant map.
- **Session/user storage** — the server is request-scoped; identity comes from the
  token or gateway header on every request (a session id is never an authenticator).
- **Message queues** — a read-mostly, request-scoped server has no async work to
  queue; adding one would be complexity without a driver.
