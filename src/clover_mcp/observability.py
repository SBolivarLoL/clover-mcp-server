"""Audit logging + optional OpenTelemetry tracing / latency.

Cross-cutting observability, kept deliberately dependency-light:

- **Audit** — every mutating (write) HTTP call emits one structured JSON line to
  stderr: method, path, status, merchant. Never bodies or secrets. On by default;
  disable with ``CLOVER_AUDIT_LOG=false``.
- **Tracing** — ``traced()`` wraps an operation. If OpenTelemetry is installed
  AND an exporter is configured (the operator ran under `opentelemetry-instrument`
  or set a provider), it creates a real span; otherwise it's a no-op. Either way,
  with ``CLOVER_LATENCY_LOG=true`` it emits a structured latency line.

Everything goes to **stderr** — the stdio MCP transport owns stdout.
ponytail: no hard OTel dependency; spans only when the operator opts in.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any


def _import_otel_trace() -> Any:
    """Return the opentelemetry trace API if installed, else None."""
    try:
        from opentelemetry import trace
    except Exception:  # pragma: no cover - OTel not installed
        return None
    return trace


# Resolved once at import. If absent, get_tracer() below is never called and
# tracing degrades to (optional) latency lines only.
_OTEL_TRACE: Any = _import_otel_trace()


def _truthy(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def audit_enabled() -> bool:
    return _truthy("CLOVER_AUDIT_LOG", "true")


def latency_enabled() -> bool:
    return _truthy("CLOVER_LATENCY_LOG", "false")


def _emit(record: dict[str, Any]) -> None:
    """Write one structured JSON line to stderr."""
    print(json.dumps(record, default=str, separators=(",", ":")), file=sys.stderr)


def audit(event: str, **fields: Any) -> None:
    """Emit a structured audit record (stderr). Pass only non-sensitive fields —
    never tokens, request bodies, PII, or card data."""
    if audit_enabled():
        _emit({"audit": event, **fields})


def _tracer() -> Any:
    if _OTEL_TRACE is None:
        return None
    return _OTEL_TRACE.get_tracer("clover-mcp")


@asynccontextmanager
async def traced(name: str, **attrs: Any) -> AsyncIterator[Any]:
    """Time an operation, optionally as an OTel span.

    Always measures wall-clock; emits a latency line when CLOVER_LATENCY_LOG is
    on; creates a real span when OTel is configured (no-op otherwise). Records the
    exception type on the latency line if the body raises, then re-raises.
    """
    start = time.perf_counter()
    tracer = _tracer()
    error: str | None = None
    cm = tracer.start_as_current_span(name) if tracer is not None else None
    span = cm.__enter__() if cm is not None else None
    if span is not None:
        for key, value in attrs.items():
            with suppress(Exception):  # attribute typing is best-effort
                span.set_attribute(str(key), value)
    try:
        yield span
    except Exception as exc:  # record then re-raise; observability never swallows
        error = type(exc).__name__
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        if cm is not None:
            cm.__exit__(None, None, None)
        if latency_enabled():
            line: dict[str, Any] = {"latency_ms": duration_ms, "op": name, **attrs}
            if error:
                line["error"] = error
            _emit(line)
