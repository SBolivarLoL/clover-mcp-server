"""Tests for audit logging + tracing/latency (observability.py)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.observability import audit, traced
from tests.conftest import TEST_MERCHANT_ID


def test_audit_emits_structured_json(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "true")
    audit("write", method="POST", path="/items", status=200, merchant="M1")
    rec = json.loads(capsys.readouterr().err.strip())
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
    assert audits[-1] == {
        "audit": "write",
        "method": "POST",
        "path": "/items",
        "status": 200,
        "merchant": TEST_MERCHANT_ID,
    }


@pytest.mark.asyncio
async def test_client_does_not_audit_reads(
    client: CloverClient, mock_http: respx.Router, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.setenv("CLOVER_AUDIT_LOG", "true")
    path = f"/v3/merchants/{TEST_MERCHANT_ID}/items"
    mock_http.get(path).mock(return_value=httpx.Response(200, json={"elements": []}))
    await client.get("/items")
    assert '"audit"' not in capsys.readouterr().err
