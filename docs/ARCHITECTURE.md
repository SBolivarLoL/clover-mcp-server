# Architecture

clover-mcp is a FastMCP server with strict separation of concerns: each module
does one job (see [CLAUDE.md](../CLAUDE.md)). Tools are thin orchestrators —
**validate → call the client → shape the response** — and everything sensitive is
removed by an allowlist before it leaves the process.

## System diagram

```mermaid
flowchart TB
    Client["MCP client<br/>(Claude · Cursor · ChatGPT)"]

    subgraph Transport
        direction LR
        Stdio["stdio<br/>local · single merchant"]
        Http["Streamable HTTP<br/>remote · single/multi-tenant"]
    end
    Client --> Stdio
    Client --> Http

    Http -->|"bearer JWT / gateway header"| Auth["remote.py — OAuth 2.1 resource server<br/>JWKS · issuer · audience (RFC 8707)<br/>RFC 9728 PRM · fail-closed tenant routing"]

    subgraph Server["FastMCP server (server.py) — 4 capability layers"]
        direction LR
        Tools["Tools<br/>34 reads · 8 guarded writes"]
        AI["AI tools<br/>5 · ctx.sample"]
        Prompts["Prompts<br/>6 workflows"]
        Res["Resource<br/>clover://capabilities"]
    end
    Stdio --> Server
    Auth --> Server

    Tools --> Orch
    AI --> Orch
    subgraph Orch["Tool orchestrators — tools/*.py (thin)"]
        direction LR
        Merchant[merchant] --- Inventory[inventory] --- Orders[orders]
        Reporting[reporting] --- Customers[customers] --- Employees[employees]
    end

    Orch --> Shaping["shaping.py — allowlist projection<br/>strips card · PIN · bank · href"]
    Orch --> CClient["client.py — CloverClient<br/>retries · pagination · 401→refresh"]
    Shaping --> CClient
    CClient --> Obs["observability.py<br/>audit · OTel spans · latency"]
    CClient -->|HTTPS| Clover[("Clover REST API<br/>region / sandbox")]

    Config["config.py — env · region→URL"] -. configures .-> Server
    AuthLife["auth.py — token lifecycle (0600 store)"] -. tokens .-> CClient
    Confirm["confirm.py — elicitation guard"] -. gates writes .-> Tools
    Window["windowing.py · formatting.py"] -. dates · money .-> Reporting
```

## Request flow (a guarded write)

```mermaid
sequenceDiagram
    participant C as MCP client
    participant S as server.py (tool)
    participant G as confirm.py
    participant K as client.py
    participant O as observability.py
    participant API as Clover API

    C->>S: set_item_price_cents(item, new, expected)
    S->>S: validate bounds + optimistic-lock pre-check (GET current)
    S->>G: confirm_write(...)
    G-->>C: elicit "apply?" (or confirm=True)
    C-->>G: accept
    S->>K: PUT /items/{id}
    K->>O: traced("clover.http") + audit("write", status)
    K->>API: PUT (never retried on 5xx)
    API-->>K: 200 (or verbatim error)
    K-->>S: shaped item
    S-->>C: {ok, item}
```

## Modules (one job each)

| Module | Concern | Must not |
|---|---|---|
| `config.py` | env, validation, region→URL | make HTTP calls |
| `auth.py` | token lifecycle, refresh, 0600 store | business logic |
| `remote.py` | OAuth resource server, multi-tenant routing | know about resources |
| `client.py` | HTTP transport, retries, pagination | know Clover resources |
| `shaping.py` | allowlist projection, PII removal | know tools or auth |
| `windowing.py` | date chunking, ms conversion | know HTTP |
| `formatting.py` | money & time display | know the API |
| `observability.py` | audit, OTel spans, latency | swallow errors |
| `confirm.py` | write confirmation (elicitation) | perform I/O |
| `tools/*.py` | orchestrate one user action | duplicate HTTP/shaping |
| `server.py` | register tools/prompts/resources, run | business logic |

## Key design choices

- **Allowlist, not denylist.** Shapers keep only named fields, so a new sensitive
  Clover field can't leak by default — enforced by a contract test and re-checked
  on live data by the [eval](eval.md).
- **Writes are a privilege.** Every write has an explicit id, an expected-current
  pre-check (optimistic lock), input bounds, `dry_run`, and confirmation; writes
  are never retried on 5xx (non-idempotent). No payment capture / refund / delete.
- **Auth at the edge, tenant from the token.** In multi-tenant mode the merchant
  is derived from the validated identity, never a client-supplied value; header
  routing is fail-closed until verified (see [SECURITY.md](SECURITY.md)).
- **Observability is opt-in and free when off.** OTel spans only when an exporter
  is configured; audit/latency are structured stderr lines.
