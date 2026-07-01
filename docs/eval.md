# Eval & benchmark

Correctness eval + operational benchmark for clover-mcp, run against a **live
Clover sandbox** merchant. Reproduce with `uv run python scripts/benchmark.py`.

_Last run: 2026-07-01, sandbox (`apisandbox.dev.clover.com`, region `na`), from a
single client process. Numbers are end-to-end (include network RTT to Clover's
sandbox + Clover-side processing), not just this server's overhead._

## Methodology

The harness ([scripts/benchmark.py](../scripts/benchmark.py)) runs three phases,
all **read-only** (GET) and throttled to stay well under Clover's ~16 req/s limit:

1. **Correctness (the eval).** Every read tool is invoked once against the live
   sandbox. Each result must (a) contain its expected top-level key and (b) pass
   the **leak gate** — a recursive scan asserting no banned key
   (`pin`, `unhashedPin`, `cards`, `cardTransaction`, `pan`, `token`, `href`,
   `abaAccountNumber`, `ddaAccountNumber`) appears anywhere in the payload. This
   is the same allowlist the contract tests enforce, but on *live* data.
2. **Latency.** One non-cached read (`GET /tenders`) is timed over 20 iterations
   (150 ms throttle between samples); report p50/p95/max/mean.
3. **Load.** A bounded burst of 30 requests at concurrency 5; report throughput
   and error/429 counts — surfaces rate-limit behaviour under pressure.

Why sandbox: it's the only environment available without a real merchant, it's
walled off from production, and it processes no real payments. See
[DEPLOY.md → Path to production](DEPLOY.md#path-to-production-sandbox--real-clover-merchants).

## Results

### Correctness — 28 / 28 read tools pass
Every read tool returns its expected shape and **leaks no card/PII/PIN/banking
data** on live sandbox payloads (including a customer, item, category, and order
seeded for the run).

### Latency — `GET /tenders`, n=20
| p50 | p95 | max | mean |
|---|---|---|---|
| 175.7 ms | 179.1 ms | 179.2 ms | 175.6 ms |

Latency is tight (p95 within ~2% of p50) and dominated by RTT to the sandbox +
Clover processing; this server's own overhead (shaping, dict projection) is
sub-millisecond. A cold first call is higher (~550 ms) due to TLS/connection
setup — the client reuses one `httpx.AsyncClient`, so subsequent calls amortize it.

### Load — 30 requests @ concurrency 5
| throughput | errors | 429s | elapsed |
|---|---|---|---|
| 11.6 req/s | 0 | 0 | 2.59 s |

No errors and no rate-limiting at this level. Observed throughput (11.6 req/s) is
below the theoretical ceiling for 5×176 ms because httpx's default connection pool
and Clover's per-connection handling serialize some requests — comfortably within
the ~16 req/s budget, which is the point.

## Error handling

The client's failure behaviour (unit-tested in `tests/`, deterministic via respx):

| Condition | Behaviour |
|---|---|
| **401** (oauth_refresh) | refresh the token once, retry; otherwise surface verbatim |
| **403** | surfaced verbatim (Clover's message passed through, not paraphrased) |
| **404** | surfaced verbatim (e.g. `get_order` on an unknown id) |
| **429** | single auto-retry iff `Retry-After` ≤ 5 s, else surface |
| **5xx** | single retry on **reads**; **writes never retried** (non-idempotent) |
| network error | surfaced; observability records the exception type |

## Traces & observability

With the `otel` extra + an OTLP exporter, every Clover call emits a span
(`clover.http`, attrs `method`/`path`). Without it, `CLOVER_LATENCY_LOG=true`
emits per-request `latency_ms` lines, and writes always emit an audit line. See
[README → Observability](../README.md#observability). The latency numbers above
were captured via this path.

## Failure analysis

1. **Naming inconsistency — `list_taxes` returns `tax_rates`.** Every other
   `list_<noun>` tool returns a `<noun>` key (`list_tenders`→`tenders`,
   `list_discounts`→`discounts`), but `list_taxes` returns `tax_rates`. The eval
   caught this. It is **not** fixed here — the key is already published in 0.6.0,
   so renaming it is a breaking change not worth a cosmetic gain. Documented so
   callers aren't surprised; revisit at the next major version.
2. **Doc-derived shapes on empty endpoints.** `order_types`, `opening_hours`,
   `attributes`, `tags`, `item_groups`, `discounts`, and `cash_events` are empty
   on this sandbox, so their element shapes are from Clover's docs, not live
   confirmation (the 🟡 rows in [endpoints.md](endpoints.md)). They return cleanly
   (200, empty) and pass the leak gate; the exact field projection for non-empty
   data is unverified for those.
3. **AI tools not benchmarked.** The 5 sampling tools need a connected client's
   model (`ctx.sample`) and fall back gracefully without one, so they're excluded
   from this API-latency benchmark; they're covered by unit tests instead.
4. **Single-region, single-client run.** Numbers reflect one client → the `na`
   sandbox. Production latency will vary by region and hosting locality.
