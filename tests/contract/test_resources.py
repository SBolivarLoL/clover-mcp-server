"""Contract: the capabilities resource reflects the real tool/prompt inventory."""

from __future__ import annotations

import json

import pytest

from clover_mcp import server


@pytest.mark.asyncio
async def test_capabilities_resource_reflects_inventory() -> None:
    result = await server.mcp.read_resource("clover://capabilities")
    data = json.loads(result.contents[0].content)

    # Reads and writes are split by annotation, not hardcoded.
    assert "get_merchant_info" in data["read_tools"]
    assert "create_item" in data["write_tools"]
    assert "get_merchant_info" not in data["write_tools"]

    assert "daily_briefing" in data["prompts"]
    assert data["guardrails"]["writes_need_confirmation"] is True
    assert data["excluded_by_design"]  # non-empty
    assert data["counts"]["reads"] == len(data["read_tools"])
    assert data["counts"]["writes"] == len(data["write_tools"])
