# CLAUDE.md — Development Guidelines for clover-mcp

This file defines the coding principles and best practices that every contributor (human or AI) must follow in this project.

---

## Principles

### 1. KISS — Keep It Simple, Stupid

Prefer the simplest solution that correctly solves the problem. Complexity is a liability.

- A new function should do one thing and do it clearly.
- If you find yourself explaining what a block of code does, simplify it first.
- Avoid abstractions until they are earned by repetition (see DRY below). A premature abstraction is worse than a copy.
- When two implementations both work, the shorter one wins — unless clarity suffers.

**Applied here:** `resolve_base_url()` in `config.py` is a single dict lookup, not a class hierarchy. `_pick()` in `shaping.py` is three lines. Keep new helpers at that level.

---

### 2. DRY — Don't Repeat Yourself

Every piece of knowledge has a single authoritative home. Duplication is the root of maintenance bugs.

- If the same logic appears in two tools, extract a shared helper in `src/clover_mcp/` (formatting, shaping, windowing, etc.).
- Region → base-URL mapping lives **only** in `config.resolve_base_url()`. Never hardcode a hostname elsewhere.
- Allowlist field names live **only** in `shaping.py`. Never re-list them in a tool or a test.
- Shared test fixtures live **only** in `tests/conftest.py`.

**Red flag:** if you copy-paste a block and change one variable, that is a signal to parameterise, not to paste.

---

### 3. SOLID Principles — The Core of OOP

Applied pragmatically to this Python/async codebase:

| Principle | What it means here |
|---|---|
| **S** — Single Responsibility | Each module has one job: `config.py` loads config, `client.py` sends HTTP, `shaping.py` projects responses, `windowing.py` splits date ranges. Don't blur those lines. |
| **O** — Open/Closed | Add new Clover resources by adding a new file under `tools/` and registering it in `server.py`. Do not modify `client.py` or `shaping.py` to accommodate a specific tool's quirks. |
| **L** — Liskov Substitution | Not deeply relevant in a mostly-functional codebase, but: if you subclass `CloverClient`, the subclass must be a drop-in replacement — do not weaken the contract. |
| **I** — Interface Segregation | Keep tool signatures narrow. A tool that only reads inventory should not accept payment-related parameters. Pass only what is needed. |
| **D** — Dependency Inversion | Tools depend on `CloverClient` (the abstraction), not on `httpx` directly. Tests inject a mock-backed client — not the real network. Never import `httpx` inside a tool file. |

---

### 4. Separation of Concerns (SoC)

Each layer of the stack is responsible for exactly one concern. Do not let concerns leak across layers.

| Layer | Its concern | Must NOT do |
|---|---|---|
| `config.py` | Read env, validate, resolve URLs | Make HTTP calls |
| `auth.py` | Token lifecycle, file storage, refresh | Business logic |
| `client.py` | HTTP transport, retries, pagination | Know about Clover resources |
| `shaping.py` | Allowlist projection, PII removal | Know about tools or auth |
| `windowing.py` | Date chunking, ms conversion | Know about HTTP or tools |
| `formatting.py` | Money and time display | Know about the API |
| `tools/*.py` | Orchestrate a user-facing action | Duplicate HTTP logic or shaping |
| `server.py` | Register tools with FastMCP, run | Implement business logic directly |
| `tests/` | Verify behaviour | Call real network or read `.env` |

If you find yourself importing `httpx` in a tool file, or importing `fastmcp` in `client.py`, that is a SoC violation — stop and refactor.

---

## Best Practices

### 1. Write Clean and Readable Code

- **Name things after what they are**, not what they do to get there. `shape_customer()` not `strip_and_flatten_customer_dict()`.
- **No abbreviations** beyond universally understood ones (`id`, `ts`, `ms`, `mId`). Write `merchant_id`, not `mid` or `m`.
- **One concept per line.** Avoid chaining more than two method calls on a single expression.
- **No magic numbers.** `max_days=90`, `MAX_PRICE_CENTS = 100_000_000` — name every constant.
- **Comments explain WHY, not WHAT.** The code says what; a comment earns its place only when the reasoning is non-obvious (e.g. "Clover returns 200 with empty body on some PUTs").
- **Keep functions short.** If a function doesn't fit on one screen, it has more than one responsibility.

---

### 2. Follow Design Principles & Architecture

- **Module boundaries are real.** Before adding code to a file, ask: is this the right module? Resist the urge to add a "quick fix" in the wrong layer.
- **The endpoint audit gate is a design constraint.** No tool ships until its endpoint row in `docs/endpoints.md` is verified against the Clover sandbox. Do not skip this.
- **Write tools as thin orchestrators.** A tool function should: validate inputs → call `client.*` → run output through the appropriate `shaping.*` function → return a clean dict. Nothing more.
- **No global mutable state** beyond the module-level `_client` in `server.py` and the asyncio lock in `auth.py`. Both are intentional and documented.
- **Async all the way down.** All I/O — HTTP calls, file reads in `auth.py` — must be non-blocking. Do not call `open()` or `requests` in an `async def` function.
- **Write tools is a privilege, not a default.** Any new write tool must have: explicit ID parameter, expected-current-value pre-check, `dry_run` support, input bounds, and a description that starts with "Modifies merchant data."

---

### 3. Always Do Testing

- **Every tool gets a test file** in `tests/tools/test_<tool_name>.py` with at minimum: one happy-path test and one error-path test (rotate through 401, 403, 404, 429).
- **Contract tests are first-class.** `tests/contract/` tests cover the guarantees that would silently break if a module drifts: region resolution, window splitting, shaping allowlist (PII/card/PIN leak prevention), money formatting.
- **Use `respx` to mock `httpx`.** Tests must never make real network calls. Use `conftest.py` fixtures — do not re-create the mock router in each test.
- **The allowlist test is a security gate.** `test_shaping_allowlist.py` must pass before any shaping change merges. Add new banned field names to `BANNED_KEYS` whenever a new sensitive Clover field is discovered.
- **Coverage floors:** `client.py`, `auth.py`, `windowing.py`, `formatting.py`, `shaping.py`, `config.py` ≥ 85%; tool modules ≥ 60%.
- **CI must be green before merging** — ruff lint, ruff format, mypy strict (on core modules), and pytest.

---

### 4. Validate User Input and Implement Graceful Error Handling

- **Validate at the boundary.** Tool parameters are the system boundary. Validate there — not inside `client.py` or `shaping.py`.
- **Fail fast and loudly on config errors.** `load_config()` raises a `RuntimeError` listing every missing variable before the server starts. Never silently default a required value.
- **Surface Clover errors verbatim.** Do not paraphrase a 403 or 404 — pass through Clover's original message so the operator can act on it.
- **Write tools require pre-checks.** Before any `PUT` or `POST`, verify the current state matches what the caller expects (`expected_current_price_cents`, `expected_current_quantity`). Fail with a diff, not silently.
- **Never retry non-idempotent writes on 5xx.** A retry on a `PUT /items/{id}` or `POST /customers` may duplicate the action. Reads get one retry; writes surface the error immediately.
- **Bound all numeric inputs.** Price: `0 ≤ price_cents ≤ 100_000_000`. Stock: `0 ≤ quantity ≤ 1_000_000`. Reject out-of-range values before the HTTP call.
- **Log to stderr only.** The stdio MCP transport uses stdout for the protocol. Any print or logging must go to stderr. Never log token values, customer PII, or card data.
