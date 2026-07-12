# MCP Production Best Practices

> Research report for clover-mcp — a Python/FastMCP server exposing Clover POS data to AI assistants.
> Sources: [MCP Spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/), [MCP Security Best Practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices), [FastMCP docs](https://gofastmcp.com), [MCP Authorization spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
> Compiled 2026-06-29.

---

## Table of Contents

1. [Tool Design](#1-tool-design)
2. [Prompts](#2-prompts)
3. [Resources](#3-resources)
4. [Sampling & Elicitation](#4-sampling--elicitation)
5. [Security](#5-security)
6. [Transport & Deployment](#6-transport--deployment)
7. [Observability & Operations](#7-observability--operations)
8. [Testing & Quality](#8-testing--quality)
9. [Auditor Checklist — Read-Mostly POS MCP Server](#9-auditor-checklist--read-mostly-pos-mcp-server)

---

## 1. Tool Design

Tools are **model-controlled** — the LLM discovers and invokes them autonomously. Good tool design shapes what the model does, how much context it wastes, and how safely operators can trust it.

### 1.1 Naming Conventions

| Item | Level | How to verify |
|---|---|---|
| Tool `name` uses `snake_case` and is globally unique within the server | MUST | `tools/list` — scan names for collisions or mixed case |
| `name` reflects the action and resource: `verb_noun` pattern (e.g., `get_orders`, `update_item_price`) | SHOULD | Manual review of `tools/list` response |
| `title` (human-readable display name) is set and differs from `name` | SHOULD | Check `tools/list`: both `name` and `title` fields present |
| Description is written from the model's perspective; starts with an action verb | SHOULD | Inspect each tool `description` field |
| Write-tool descriptions start with "Modifies merchant data." (per CLAUDE.md) | MUST (project) | Grep tool definitions for write tools |

**`name` vs `title`** (spec 2025-11-25): `name` is the machine identifier used in `tools/call`. `title` is an optional human-readable label for display in client UIs. Always provide `title` for better UX; never rely on it for routing.

### 1.2 Behavioural Annotations

Annotations are **advisory hints** — clients MUST treat them as untrusted unless the server is trusted. They shape user experience (e.g., skipping confirmation prompts for read-only tools).

| Annotation | Meaning | Level | How to verify |
|---|---|---|---|
| `readOnlyHint: true` | Tool only reads data, does not modify external state | SHOULD set on all read tools | `tools/list` → `annotations.readOnlyHint` on every query tool |
| `destructiveHint: true` | Tool may perform destructive updates (default: `true`) | MUST set `false` on safe writes, `true` on deletes | Check delete/overwrite tools |
| `idempotentHint: true` | Repeated calls with same args produce same result | SHOULD set on PUT-style updates | Verify update tools declare this |
| `openWorldHint: true` | Tool interacts with external systems (default: `true`) | SHOULD set `false` for pure local computation | Not usually relevant for API-backed tools |

Source: [MCP Tools spec](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

**clover-mcp implication:** Every `get_*` / `list_*` tool MUST declare `readOnlyHint: true`. Write tools (`update_item_price`, etc.) MUST declare `destructiveHint: true` and SHOULD declare `idempotentHint: true` where applicable (PUT semantics).

### 1.3 Input Schema Validation

| Item | Level | How to verify |
|---|---|---|
| Every tool declares a complete `inputSchema` (JSON Schema object) | MUST | `tools/list` — every tool has `inputSchema` with `type: object` |
| Required parameters are listed in `required` array | MUST | Inspect `inputSchema.required` |
| Numeric bounds are set: price `0–100_000_000`, quantity `0–1_000_000` | MUST (project) | Check `minimum`/`maximum` in number field schemas |
| `enum` or `pattern` used for constrained string values (e.g., region, status) | SHOULD | Inspect string field schemas |
| Parameter descriptions are present for every property | SHOULD | Check `properties.<field>.description` |
| Tool validates inputs at the boundary before any downstream call | MUST | Code review: validation in tool function, not client.py |

### 1.4 Output Schemas / Structured Content

The spec (2025-11-25) adds `outputSchema` and `structuredContent` to tool results:

| Item | Level | How to verify |
|---|---|---|
| Tools return `structuredContent` (JSON object) alongside `content` text for machine-readable data | SHOULD | Inspect `tools/call` responses for `structuredContent` field |
| If `outputSchema` is provided, server MUST ensure results conform to it | MUST | Add schema validation in tests |
| For backwards compat, if `structuredContent` is returned, a serialized JSON text block SHOULD also be in `content` | SHOULD | Verify both fields in response |

**FastMCP note:** Return type annotations on Python tool functions automatically generate output schemas. Returning a `dict` or Pydantic model gives structured output.

### 1.5 Pagination Conventions

MCP uses **opaque cursor-based pagination** — no page numbers.

| Item | Level | How to verify |
|---|---|---|
| `tools/list` supports cursor pagination | MUST (if >1 page) | Send `tools/list` with and without cursor |
| List tools that return collections (orders, items, customers) accept `cursor` / `limit` parameters | SHOULD | Inspect tool input schemas for pagination params |
| Server returns `nextCursor` when more results exist | MUST | Test with small page size |
| Client MUST NOT assume a fixed page size | MUST | N/A — server-side |
| Cursors are opaque and stable within a session | SHOULD | Test cursor reuse |

Source: [MCP Pagination spec](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination)

### 1.6 Error Semantics: `isError` vs Protocol Error

Two distinct error channels exist:

| Error type | When to use | Wire format |
|---|---|---|
| **Protocol error** (JSON-RPC `error` field) | Tool doesn't exist; invalid arguments (schema violation); server crash | `{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"..."}}` |
| **Tool execution error** (`isError: true` in result) | API failure (401/403/404/429 from Clover); business logic failure; rate limit | `{"result":{"content":[{"type":"text","text":"..."}],"isError":true}}` |

| Item | Level | How to verify |
|---|---|---|
| Clover API errors (4xx/5xx) are returned as `isError: true` results, NOT protocol errors | MUST | Test with bad merchant ID; inspect response shape |
| Protocol errors are only used for unknown tool name or malformed arguments | MUST | Send unknown tool name; expect JSON-RPC error |
| `isError: true` responses include Clover's original error message verbatim | SHOULD | Compare error text against Clover API docs |

### 1.7 Token Efficiency of Responses

| Item | Level | How to verify |
|---|---|---|
| Response shaping (allowlist) strips fields the LLM doesn't need | MUST (project) | Call a tool and verify no raw Clover response fields leak |
| Money values are formatted as human-readable strings, not raw cents | SHOULD | Check `formatting.py` usage |
| Large list results are paginated, not returned all at once | SHOULD | Test list_orders with large dataset |
| Tool descriptions are concise — avoid padding that wastes context window | SHOULD | Measure token count of `tools/list` response |

---

## 2. Prompts

Prompts are **user-controlled** workflow templates, not model-controlled. They're surfaced as slash commands or menu items in client UIs.

### 2.1 When to Provide Prompts

| Item | Level | How to verify |
|---|---|---|
| Provide prompts for common multi-step workflows (e.g., "generate daily sales summary", "find low-stock items") | SHOULD | `prompts/list` — check if workflows are encoded |
| Do NOT encode prompts for single-tool operations that the model can handle natively | NICE | Review: prompts should compose >1 tool |
| Declare `prompts.listChanged: true` if prompt list changes at runtime | SHOULD | Check server capability declaration |

### 2.2 Argument Design

| Item | Level | How to verify |
|---|---|---|
| Required arguments are marked `required: true` | MUST | `prompts/list` → `arguments[*].required` |
| Arguments have clear descriptions | SHOULD | Check `arguments[*].description` |
| Use completion API (`completions` capability) for argument autocomplete where values are enumerable | NICE | Test tab-completion in Claude Desktop |

### 2.3 Discoverability

| Item | Level | How to verify |
|---|---|---|
| Prompt `description` explains when a user would invoke it | SHOULD | Read each prompt description |
| Prompt `title` is set (display name for UI) | SHOULD | Check `title` field in `prompts/list` |
| Prompts that embed resources include them as `embedded resource` content blocks | SHOULD | Inspect `prompts/get` response content types |

---

## 3. Resources

Resources are **application-controlled** context — the host app decides what to inject. They model persistent, readable data identified by URI.

### 3.1 Resources vs Tools Decision

| Scenario | Use Resource | Use Tool |
|---|---|---|
| Static or slowly-changing reference data (merchant config, category list) | Yes | No |
| Data requiring parameters or real-time query | No | Yes |
| Data the user/app explicitly selects for context inclusion | Yes | No |
| Data the LLM needs to trigger a side effect to fetch | No | Yes |

### 3.2 Resource Templates

| Item | Level | How to verify |
|---|---|---|
| Parameterized data (e.g., `clover://items/{item_id}`) uses URI templates (RFC 6570) | SHOULD | `resources/templates/list` — check `uriTemplate` fields |
| Template arguments support completion API | NICE | Test autocomplete in supporting client |
| Templates use custom URI schemes (e.g., `clover://`) for API-backed resources, not `https://` | SHOULD | Inspect URI schemes in resource/template list |

Source: [MCP Resources spec](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)

### 3.3 Subscriptions

| Item | Level | How to verify |
|---|---|---|
| Declare `resources.subscribe: true` only if the server can push change notifications | MUST | Server capabilities must match implementation |
| Declare `resources.listChanged: true` and send `notifications/resources/list_changed` when inventory changes | SHOULD | Test by modifying resource list; verify notification |

### 3.4 Annotations

Resources support `audience` (`"user"` | `"assistant"`), `priority` (0–1.0), and `lastModified` (ISO 8601):

| Item | Level | How to verify |
|---|---|---|
| Set `audience: ["assistant"]` for data the LLM needs but users don't need to see | NICE | Check annotation fields in `resources/list` |
| Set `priority` to guide context window budgeting | NICE | Check annotation fields |

---

## 4. Sampling & Elicitation

### 4.1 Sampling (`ctx.sample`)

Sampling lets the **server** request an LLM completion via the **client** — no server-side API key required. The client maintains control over model selection and user approval.

| Item | Level | How to verify |
|---|---|---|
| Server MUST NOT hold its own LLM API key for agentic features; use `ctx.sample` instead | MUST | Grep for direct Anthropic/OpenAI API calls in server code |
| Check client `sampling` capability before calling; degrade gracefully if absent | MUST | Code review: `if ctx.client_capabilities.sampling` guard |
| Keep `maxTokens` bounded to prevent runaway costs | SHOULD | Inspect sampling calls for `maxTokens` |
| Use `modelPreferences` hints (not hard-coded model names) | SHOULD | Check sampling calls for `modelPreferences` |
| SHOULD always have a human-in-the-loop approval path (enforced by client) | SHOULD | N/A — client enforces; document that sampling is used |
| Tool loops using sampling MUST cap maximum iterations | MUST | Code review: iteration limit in any sampling loops |

Source: [MCP Sampling spec](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)

**FastMCP:** `await ctx.sample("prompt text", max_tokens=500)` — straightforward API. Check client declared `sampling` capability first.

### 4.2 Elicitation (`ctx.elicit`)

Elicitation lets the **server** request structured input from the **user** via the **client** during tool execution — human-in-the-loop confirmations.

| Item | Level | How to verify |
|---|---|---|
| Use `ctx.elicit` for write-operation confirmations where dry-run isn't sufficient | SHOULD | Check write tools for elicitation use |
| Check client `elicitation` capability before calling; degrade gracefully | MUST | Code review: capability guard before `ctx.elicit` |
| Use **form mode** for non-sensitive structured input; use **URL mode** for credentials/payment | MUST | Verify no passwords/tokens collected via form mode |
| Schema is restricted to flat primitives (string/number/boolean/enum) | MUST | Check `requestedSchema` — no nested objects |
| Handle all three response actions: `accept`, `decline`, `cancel` | MUST | Code review: all three branches handled |
| MUST NOT use form elicitation for passwords, API keys, tokens, or payment credentials | MUST | Audit elicitation schema fields |

Source: [MCP Elicitation spec](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)

**clover-mcp implication:** For the write tools (update price, update stock), `ctx.elicit` for confirmation is a strong alternative to `dry_run`. Must verify client supports elicitation before using.

---

## 5. Security

This is the most critical section. MCP's power comes with significant attack surface.

### 5.1 OAuth 2.1 Resource-Server Pattern

Applies to the **HTTP transport** deployment. stdio uses environment credentials instead.

| Item | Level | How to verify |
|---|---|---|
| MCP server acts as OAuth 2.1 resource server — validates Bearer tokens on every request | MUST | Test unauthenticated request: expect 401 |
| MCP server implements RFC 9728 Protected Resource Metadata at `/.well-known/oauth-protected-resource` | MUST | `GET /.well-known/oauth-protected-resource` returns JSON |
| 401 response includes `WWW-Authenticate: Bearer resource_metadata="..."` header | MUST | Inspect 401 response headers |
| Authorization server discovery follows RFC 8414 / OIDC discovery order | MUST | Verify AS metadata endpoint is advertised |
| PKCE (`S256`) is required; refuse to proceed if `code_challenge_methods_supported` absent | MUST | Auth server metadata check |
| All auth endpoints served over HTTPS; redirect URIs are localhost or HTTPS | MUST | Verify TLS on endpoints |
| Short-lived access tokens; refresh token rotation for public clients | SHOULD | Check token TTL with AS configuration |

Sources: [Authorization spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization), [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728), [RFC 8707](https://www.rfc-editor.org/rfc/rfc8707.html)

### 5.2 RFC 8707 Resource Indicators / Audience Binding

| Item | Level | How to verify |
|---|---|---|
| MCP clients MUST include `resource` parameter (canonical server URI) in auth and token requests | MUST | Inspect authorization request parameters |
| MCP server MUST validate token audience — reject tokens not issued specifically for this server | MUST | Test with token issued for different resource; expect 401/403 |
| Token MUST include server's canonical URI in audience claim (`aud`) | MUST | Decode JWT and inspect `aud` claim |

### 5.3 The Token Pass-Through Anti-Pattern (MUST NOT)

**This is explicitly forbidden by the spec.** Token pass-through means accepting a token from an MCP client and forwarding it unchanged to a downstream API (e.g., forwarding the MCP bearer token directly to the Clover API).

| Item | Level | How to verify |
|---|---|---|
| MCP server MUST NOT forward the client's Bearer token to upstream APIs (Clover) | MUST NOT | Code review: `client.py` — Clover API auth uses its own credentials, never the MCP bearer token |
| MCP server obtains its own credentials for upstream APIs via environment (stdio) or secure store (HTTP) | MUST | Verify Clover credentials come from env/config, not from MCP request headers |
| Multi-tenant HTTP deployment: each tenant's Clover token is isolated to that tenant's session | MUST | Security audit of token storage and session-to-credential mapping |

**Risks of token pass-through:** bypasses rate limiting, accountability, and audit trails; enables lateral access across services; breaks trust boundaries.

Source: [Security Best Practices — Token Passthrough](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices#token-passthrough)

### 5.4 The Confused Deputy Problem

Applies when clover-mcp acts as an OAuth proxy to Clover's API.

| Item | Level | How to verify |
|---|---|---|
| If using a static Clover OAuth client ID with dynamic MCP client registration: MUST implement per-MCP-client consent before forwarding to Clover auth | MUST | Code review: consent registry check before Clover OAuth flow |
| Consent decision stored server-side per `(user_id, mcp_client_id)` pair, not just a cookie | MUST | Inspect auth flow implementation |
| OAuth `state` parameter is cryptographically random, stored server-side, single-use, set ONLY AFTER consent | MUST | Auth flow code review |
| Redirect URI validated with exact string match — no wildcards | MUST | Test with modified redirect URI |

Source: [Security Best Practices — Confused Deputy](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices#confused-deputy-problem)

### 5.5 Session Hijacking

| Item | Level | How to verify |
|---|---|---|
| Session IDs are cryptographically secure random values (UUID v4 or equivalent) | MUST | Inspect `MCP-Session-Id` format in HTTP responses |
| Session IDs MUST NOT be used for authentication — every request must re-validate the Bearer token | MUST | Test: send valid session ID with invalid/missing token; expect 401 |
| Session ID bound to user identity in server state: key is `<user_id>:<session_id>` | SHOULD | Code review: session state storage key format |
| For multi-tenant HTTP: session state MUST be isolated per tenant | MUST | Cross-tenant access test: session from tenant A must not read tenant B's data |

Source: [Security Best Practices — Session Hijacking](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices#session-hijacking)

### 5.6 Multi-Tenant Isolation

Specific to clover-mcp's HTTP multi-tenant mode (see commit `0b6e4ce`):

| Item | Level | How to verify |
|---|---|---|
| Merchant ID is derived from the validated token/session, NOT from a client-provided header | MUST | Code review: merchant ID extraction path; check header-spoofing guard |
| Every Clover API call includes the merchant ID from the authenticated context | MUST | Trace `merchant_id` through tool → client call chain |
| Cross-tenant access: tool cannot query another merchant's data by ID-guessing | MUST | Test: authenticated as merchant A, request merchant B's orders |
| Tenant credentials are isolated in separate storage namespaces | MUST | Inspect credential store key structure |

### 5.7 Prompt Injection / Tool Poisoning

| Item | Level | How to verify |
|---|---|---|
| Tool descriptions and resource content are sanitized before returning to the LLM | SHOULD | Test with merchant data containing instruction-like text |
| Tool outputs do not reflect unsanitized external content that could hijack the model | SHOULD | Code review: shaping layer strips/escapes suspicious fields |
| Write tools require explicit ID parameter and pre-check to prevent model-driven confusion | MUST (project) | Check all PUT/POST tools for `expected_current_*` pre-check pattern |
| Tool annotations are documented as advisory (client should treat as untrusted) | SHOULD | Documentation / server README |

Source: [MCP Spec — Tool Safety](https://modelcontextprotocol.io/specification/2025-11-25/)

### 5.8 Input Sanitization

| Item | Level | How to verify |
|---|---|---|
| All tool inputs validated at the boundary (schema + semantic checks) | MUST | Code review: validation in tool function |
| Numeric bounds enforced before HTTP call: price `0–100_000_000`, quantity `0–1_000_000` | MUST | Check input validation logic |
| String inputs sanitized before inclusion in Clover API requests | SHOULD | Code review: no format-string injection into API paths |
| Resource URIs validated before read | MUST | `resources/read` with path-traversal URI; expect error |

### 5.9 Secrets Handling & Logging Hygiene

| Item | Level | How to verify |
|---|---|---|
| No tokens, API keys, customer PII, or card data appear in logs | MUST | Grep log output / stderr for sensitive patterns |
| `logging` capability sends structured logs to client at appropriate level | SHOULD | `logging/setLevel` test; check `notifications/message` events |
| Log messages MUST NOT contain credentials, PII, or internal system details | MUST | Audit log emission sites |
| Clover tokens stored in env vars / config, never in code or version control | MUST | `git grep` for hardcoded credentials |
| `.env` file excluded from version control | MUST | Check `.gitignore` |

Source: [MCP Logging spec](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging)

### 5.10 Transport Security

| Item | Level | How to verify |
|---|---|---|
| HTTP transport: all endpoints served over HTTPS in production | MUST | Certificate check on deployed server |
| Streamable HTTP: `Origin` header validated on all incoming connections; reject with 403 if invalid | MUST | Test with `Origin: https://evil.example.com` — expect 403 |
| Locally running server binds to `127.0.0.1`, not `0.0.0.0` | SHOULD | Check server bind address |
| stdio transport: credentials retrieved from environment, not from protocol messages | MUST | Code review: `load_config()` uses env vars |
| `MCP-Protocol-Version` header validated; 400 on unsupported version | MUST | Send invalid protocol version header |

### 5.11 Rate Limiting / Abuse Protection

| Item | Level | How to verify |
|---|---|---|
| Server-side rate limiting on tool invocations | SHOULD | Test rapid repeated tool calls |
| Clover API rate limit (429) returned as `isError: true`, not swallowed | MUST | Simulate 429 from Clover mock; check tool response |
| Write tools: no retry on 5xx (non-idempotent writes may duplicate) | MUST | Code review: `client.py` retry logic excludes write methods |
| Sampling rate limited to prevent LLM cost runaway | SHOULD | Check if sampling calls have iteration caps |

### 5.12 Scope Minimization

| Item | Level | How to verify |
|---|---|---|
| Clover OAuth scopes requested are minimal for the tools exposed | SHOULD | Compare declared scopes against tools' actual API needs |
| `scopes_supported` in Protected Resource Metadata lists only minimum necessary scopes | SHOULD | Check metadata document `scopes_supported` |
| No wildcard or omnibus scopes (`*`, `full-access`) | MUST NOT | Inspect scope declarations |

---

## 6. Transport & Deployment

### 6.1 stdio vs Streamable HTTP

| Scenario | Recommended Transport | Rationale |
|---|---|---|
| Single merchant, local desktop use | stdio | Simpler, no auth needed, inherits OS process isolation |
| Multi-tenant SaaS / remote access | Streamable HTTP | Supports OAuth, multiple concurrent clients |
| CI/testing | stdio | No network, fast, deterministic |

| Item | Level | How to verify |
|---|---|---|
| stdio: server MUST NOT write non-MCP content to stdout | MUST | Run server; inspect all stdout output |
| stdio: all logging goes to stderr | MUST | Confirm `logging.basicConfig(stream=sys.stderr)` or equivalent |
| HTTP: server provides single MCP endpoint supporting both POST and GET | MUST | Test POST and GET to `/mcp` |
| HTTP: server returns `Content-Type: text/event-stream` or `application/json` for tool calls | MUST | Inspect response Content-Type headers |
| HTTP: session ID (`MCP-Session-Id`) is globally unique, cryptographically secure | MUST | Inspect session ID format |
| HTTP: `DELETE /mcp` with `MCP-Session-Id` should terminate session (or return 405) | SHOULD | Test session termination |

### 6.2 Versioning / Capability Negotiation

| Item | Level | How to verify |
|---|---|---|
| Server responds to `initialize` with the negotiated protocol version | MUST | Send `initialize` with `protocolVersion: "2025-11-25"` |
| Server declares all capabilities it actually implements (no phantom capabilities) | MUST | Cross-check capabilities against implemented handlers |
| Server MUST NOT use capabilities the client didn't declare | MUST | Check sampling/elicitation guards |
| `tools.listChanged: true` declared if tool list changes at runtime | SHOULD | Check server capabilities |

### 6.3 Graceful Degradation

| Item | Level | How to verify |
|---|---|---|
| Server checks client sampling capability before using `ctx.sample` | MUST | Code review |
| Server checks client elicitation capability before using `ctx.elicit` | MUST | Code review |
| Server falls back to dry_run behavior when elicitation is unavailable | SHOULD | Test with client that doesn't declare elicitation |
| Backwards compat: support HTTP+SSE (2024-11-05) transport alongside Streamable HTTP | NICE | Test with Claude Desktop (older client) |

### 6.4 Statelessness

| Item | Level | How to verify |
|---|---|---|
| Tools are stateless within a request; no tool call depends on undeclared prior state | SHOULD | Review tool implementations |
| Session state (if used via FastMCP `ctx.set_state`) is isolated per session | MUST | Test cross-session state leak |
| Server can handle multiple concurrent sessions without cross-contamination | MUST | Concurrent session test |

---

## 7. Observability & Operations

### 7.1 Logging

| Item | Level | How to verify |
|---|---|---|
| All logging goes to stderr for stdio transport | MUST | Capture server stderr; confirm log lines present |
| Server declares `logging` capability | SHOULD | Check capability declaration |
| Uses MCP structured logging (`notifications/message`) at appropriate severity levels | SHOULD | Send `logging/setLevel`; verify client receives log notifications |
| Log levels follow RFC 5424 syslog levels (debug/info/notice/warning/error/critical/alert/emergency) | SHOULD | Inspect log level usage in code |
| Log messages rate-limited to prevent flooding | SHOULD | Rapid-call test; observe log volume |
| Sensitive data (tokens, PII, card data) NEVER appears in logs | MUST | Grep stderr output for sensitive patterns |

### 7.2 Audit Trails for Writes

| Item | Level | How to verify |
|---|---|---|
| Every write tool call is logged with: merchant_id, tool name, arguments (sanitized), outcome | MUST (project) | Trigger a write tool; confirm audit log entry |
| Audit log is append-only and includes timestamp and request ID | SHOULD | Inspect audit log format |
| Write tool pre-check failures are logged as warnings | SHOULD | Trigger a pre-check failure; confirm log |

### 7.3 Health Checks

| Item | Level | How to verify |
|---|---|---|
| HTTP deployment: a health/ping endpoint responds without auth | SHOULD | `GET /health` or `POST` with `ping` returns 200 |
| MCP `ping` utility supported | SHOULD | Send `{"method":"ping"}` — expect `{}` response |
| Server advertises `instructions` field in `initialize` response for operator guidance | NICE | Check `InitializeResult.instructions` |

### 7.4 Progress Notifications

| Item | Level | How to verify |
|---|---|---|
| Long-running tools (e.g., date-windowed order fetches) emit progress notifications | SHOULD | Call a windowed query; inspect for `notifications/progress` |
| Progress uses `ctx.report_progress(progress, total)` | SHOULD | Code review |

---

## 8. Testing & Quality

### 8.1 Contract Tests

| Item | Level | How to verify |
|---|---|---|
| Every tool has a test: at minimum one happy-path and one error-path (401/403/404/429) | MUST | `ls tests/tools/` — one file per tool |
| `test_shaping_allowlist.py` passes: no PII/card/PIN fields leak through shaping | MUST | `pytest tests/contract/test_shaping_allowlist.py` |
| Region → base-URL mapping tested (no hardcoded hosts in tools) | MUST | `tests/contract/` coverage |
| Money formatting contract test: cents → display string | SHOULD | `tests/contract/test_formatting.py` |
| Window splitting contract test: date ranges chunk correctly | SHOULD | `tests/contract/test_windowing.py` |

### 8.2 Schema Validation

| Item | Level | How to verify |
|---|---|---|
| `inputSchema` is validated against actual tool parameters (schema matches implementation) | MUST | Use `jsonschema` to validate test inputs against schema |
| `outputSchema` (if provided) is validated against actual tool outputs | MUST | Schema validation in test fixtures |
| Tool list conforms to MCP spec schema | SHOULD | Validate `tools/list` response against MCP JSON Schema |

### 8.3 Mocking Transport

| Item | Level | How to verify |
|---|---|---|
| Tests use `respx` to mock `httpx` — no real network calls | MUST | `grep -r "httpx" tests/` — only `respx` patterns |
| Mock Clover responses cover: 200 with data, 200 with empty body (Clover quirk), 400, 401, 403, 404, 429, 500 | SHOULD | Check `conftest.py` mock response fixtures |
| `conftest.py` provides shared mock client — not recreated per test | SHOULD | `tests/conftest.py` review |

### 8.4 Coverage Floors

Per CLAUDE.md project requirements:

| Module | Minimum Coverage |
|---|---|
| `client.py`, `auth.py`, `windowing.py`, `formatting.py`, `shaping.py`, `config.py` | ≥ 85% |
| `tools/*.py` | ≥ 60% |

Verify with: `pytest --cov=src/clover_mcp --cov-report=term-missing`

### 8.5 CI Gates

| Item | Level | How to verify |
|---|---|---|
| `ruff` lint passes | MUST | `ruff check src/` |
| `ruff format --check` passes | MUST | `ruff format --check src/` |
| `mypy --strict` passes on core modules | MUST | `mypy src/clover_mcp/config.py src/clover_mcp/client.py ...` |
| `pytest` passes with coverage floors | MUST | `pytest --cov` |

---

## 9. Auditor Checklist — Read-Mostly POS MCP Server

A crisp checklist for auditing clover-mcp against production MCP requirements.

### Security (Critical — check first)

- [ ] **Token pass-through absent**: `client.py` uses Clover credentials from config/env, NEVER the MCP Bearer token from the request
- [ ] **Multi-tenant header-spoofing guard**: merchant ID derived from validated token, NOT from `X-Merchant-Id` or similar client header
- [ ] **Per-session credential isolation**: tenant A's Clover token cannot be accessed by tenant B's session
- [ ] **OAuth 2.1 resource server**: HTTP deployment validates Bearer token on every request (not just session init)
- [ ] **RFC 9728 metadata endpoint**: `GET /.well-known/oauth-protected-resource` returns valid JSON with `authorization_servers`
- [ ] **RFC 8707 audience validation**: tokens rejected if `aud` claim doesn't match this server's canonical URI
- [ ] **No secrets in logs**: grep stderr for token/PII patterns
- [ ] **HTTPS only in production**: no plain HTTP endpoints
- [ ] **Origin header validation**: HTTP transport rejects `Origin` headers that don't match expected domains (403)
- [ ] **Allowlist shaping**: no `card`, `pin`, `bank`, `ssn`, `cvv`, `pan` fields in any tool response

### Tool Design

- [ ] **`readOnlyHint: true`** on every `get_*` / `list_*` tool
- [ ] **`destructiveHint: true`** on every write/delete tool
- [ ] **`title` field** set on every tool (distinct from `name`)
- [ ] **Numeric bounds** in `inputSchema` for price (`0–100_000_000`) and quantity (`0–1_000_000`)
- [ ] **`isError: true`** used for Clover API errors (not JSON-RPC protocol errors)
- [ ] **Clover error messages passed through verbatim** (not paraphrased)
- [ ] **Write tools** have: explicit ID param, `expected_current_*` pre-check, `dry_run` support, description starting with "Modifies merchant data."
- [ ] **No retry on 5xx** for write tools

### Sampling & Elicitation

- [ ] **No LLM API key in server**: all LLM calls via `ctx.sample`
- [ ] **Capability guard** before `ctx.sample` and `ctx.elicit`
- [ ] **Sampling iteration cap**: any sampling loop has a maximum iteration limit
- [ ] **No sensitive data via form elicitation**: no API keys, passwords, or tokens collected via `elicitation/create` with `mode: form`
- [ ] **All three elicitation actions handled**: `accept`, `decline`, `cancel`

### Transport & Lifecycle

- [ ] **stdio: nothing to stdout except MCP JSON**: no `print()` statements in tool code
- [ ] **All logging to stderr**: `logging` configured to `sys.stderr`
- [ ] **Capability declarations match implementation**: no phantom capabilities declared
- [ ] **`MCP-Protocol-Version` header validated** on HTTP transport
- [ ] **Session IDs cryptographically random** (not sequential or guessable)

### Observability

- [ ] **Audit log** for every write tool call (merchant_id, tool, sanitized args, outcome, timestamp)
- [ ] **MCP `logging` capability declared** and `notifications/message` emitted at appropriate levels
- [ ] **Log rate limiting**: high-frequency tools don't flood client with log messages
- [ ] **Progress notifications** on long date-windowed queries

### Testing

- [ ] **Every tool has a test file** with ≥1 happy-path and ≥1 error-path test
- [ ] **`test_shaping_allowlist.py` passes** (PII/card/PIN security gate)
- [ ] **No real network calls in tests** (`respx` mocks only)
- [ ] **Coverage floors met**: core modules ≥85%, tools ≥60%
- [ ] **CI green**: ruff lint, ruff format, mypy strict, pytest

### Spec Features Most Often Missed

- [ ] **`outputSchema` not yet provided** — add to enable structured content validation
- [ ] **`structuredContent` field absent** — tools return text only; add for machine-readable output
- [ ] **Resource templates not implemented** — consider `clover://items/{item_id}` pattern for direct resource access
- [ ] **Prompts not implemented** — consider adding workflow prompts (daily summary, low-stock report)
- [ ] **`tools.listChanged` not declared** — if tool list is static this is fine, but should be explicit `false`
- [ ] **Pagination on tool list** — verify `tools/list` correctly returns `nextCursor` if tools exceed one page
- [ ] **`completions` capability** — argument autocomplete not implemented for resource templates

---

*Sources consulted:*
- *MCP Specification 2025-11-25: https://modelcontextprotocol.io/specification/2025-11-25/*
- *MCP Authorization: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization*
- *MCP Security Best Practices: https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices*
- *MCP Tools: https://modelcontextprotocol.io/specification/2025-11-25/server/tools*
- *MCP Resources: https://modelcontextprotocol.io/specification/2025-11-25/server/resources*
- *MCP Prompts: https://modelcontextprotocol.io/specification/2025-11-25/server/prompts*
- *MCP Sampling: https://modelcontextprotocol.io/specification/2025-11-25/client/sampling*
- *MCP Elicitation: https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation*
- *MCP Transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports*
- *MCP Pagination: https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination*
- *MCP Logging: https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging*
- *MCP Lifecycle: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle*
- *FastMCP Tools: https://gofastmcp.com/servers/tools*
- *FastMCP Context: https://gofastmcp.com/servers/context*
- *RFC 8707 Resource Indicators: https://www.rfc-editor.org/rfc/rfc8707.html*
- *RFC 9728 Protected Resource Metadata: https://datatracker.ietf.org/doc/html/rfc9728*
