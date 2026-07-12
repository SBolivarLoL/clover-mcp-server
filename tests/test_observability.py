"""Tests for audit logging + tracing/latency (observability.py)."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.observability import audit, traced
from tests.conftest import TEST_MERCHANT_ID


def _pop_ts(rec: dict) -> None:
    """Assert the record carries a valid UTC ISO-8601 `ts`, then drop it so the
    remaining fields can be compared exactly."""
    ts = rec.pop("ts")
    assert datetime.fromisoformat(ts).utcoffset().total_seconds() == 0


def test_audit_emits_structured_json(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "true")
    audit("write", method="POST", path="/items", status=200, merchant="M1")
    rec = json.loads(capsys.readouterr().err.strip())
    _pop_ts(rec)
    assert rec == {
        "audit": "write",
        "method": "POST",
        "path": "/items",
        "status": 200,
        "merchant": "M1",
    }


def test_audit_disabled_emits_nothing(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "false")
    audit("write", method="POST")
    assert capsys.readouterr().err == ""


@pytest.mark.asyncio
async def test_traced_emits_latency_when_enabled(
    capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.setenv("CLOVER_LATENCY_LOG", "true")
    async with traced("clover.http", method="GET", path="/items"):
        pass
    rec = json.loads(capsys.readouterr().err.strip())
    assert rec["op"] == "clover.http"
    assert rec["method"] == "GET"
    assert isinstance(rec["latency_ms"], (int, float))


@pytest.mark.asyncio
async def test_traced_silent_by_default(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    monkeypatch.delenv("CLOVER_LATENCY_LOG", raising=False)
    async with traced("op"):
        pass
    assert capsys.readouterr().err == ""


@pytest.mark.asyncio
async def test_traced_records_and_reraises_error(
    capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.setenv("CLOVER_LATENCY_LOG", "true")
    with pytest.raises(ValueError):
        async with traced("op"):
            raise ValueError("boom")
    rec = json.loads(capsys.readouterr().err.strip())
    assert rec["error"] == "ValueError"


@pytest.mark.asyncio
async def test_client_audits_writes(
    client: CloverClient, mock_http: respx.Router, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "true")
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/items"
    mock_http.post(path).mock(return_value=httpx.Response(200, json={"id": "I1"}))
    await client.post("/items", json={"name": "x", "price": 100})
    audits = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if '"audit"' in line
    ]
    assert audits, "expected an audit line for the write"
    last = audits[-1]
    _pop_ts(last)
    assert last == {
        "audit": "write",
        "method": "POST",
        "path": "/items",
        "status": 200,
        "merchant": TEST_MERCHANT_ID,
    }


@pytest.mark.asyncio
async def test_client_audit_includes_tenant_when_set(
    test_config, mock_http: respx.Router, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    """In multi-tenant mode the resolved tenant key is recorded on the write —
    the audit trail answers "who", not just "which merchant"."""
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "true")
    client = CloverClient(test_config, tenant="acme-co")
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/items"
    mock_http.post(path).mock(return_value=httpx.Response(200, json={"id": "I1"}))
    await client.post("/items", json={"name": "x", "price": 100})
    await client.close()
    audits = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if '"audit"' in line
    ]
    assert audits[-1]["tenant"] == "acme-co"


@pytest.mark.asyncio
async def test_iterate_caps_pages_and_emits_note(
    client: CloverClient, mock_http: respx.Router, capsys: pytest.CaptureFixture[str]
) -> None:
    """iterate() stops at max_pages and emits a `note` — a truncated walk is never
    silent (guards against a runaway page walk)."""
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/items"
    # Always a full page → would paginate forever without the cap.
    mock_http.get(path).mock(
        return_value=httpx.Response(200, json={"elements": [{"id": "a"}, {"id": "b"}]})
    )
    seen = 0
    async for _ in client.iterate("/items", limit=2, max_pages=3):
        seen += 1
    await client.close()

    assert seen == 6  # 3 pages × 2 rows, then stop
    notes = [json.loads(line) for line in capsys.readouterr().err.splitlines() if '"note"' in line]
    assert notes[-1]["note"] == "pagination_capped"
    assert notes[-1]["max_pages"] == 3


@pytest.mark.asyncio
async def test_client_does_not_audit_reads(
    client: CloverClient, mock_http: respx.Router, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "true")
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/items"
    mock_http.get(path).mock(return_value=httpx.Response(200, json={"elements": []}))
    await client.get("/items")
    assert '"audit"' not in capsys.readouterr().err
