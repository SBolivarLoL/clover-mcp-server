"""Tests for Layer 2 AI/LLM (sampling) tools.

The core behaviour to pin is `_narrate`: it returns the gathered data PLUS the
model's narrative on success, and falls back to data + note (never raises) when
the client can't sample. One wired test confirms the gather → bounded-prompt →
sample path for a representative tool.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from clover_mcp.client import CloverClient
from clover_mcp.tools import ai
from tests.conftest import TEST_MERCHANT_ID


class FakeCtx:
    """Stand-in Context whose sample() returns canned text and records the prompt."""

    def __init__(self, text: str = "AI narrative here") -> None:
        self._text = text
        self.last_user: str | None = None
        self.last_system: str | None = None

    async def sample(self, user, *, system_prompt=None, max_tokens=None):  # type: ignore[no-untyped-def]
        self.last_user = user
        self.last_system = system_prompt
        return SimpleNamespace(text=self._text)


class FailCtx:
    """A client that cannot sample — sample() raises."""

    async def sample(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("client does not support sampling")


@pytest.mark.asyncio
async def test_narrate_success_returns_data_and_summary() -> None:
    ctx = FakeCtx("Sales up 10%.")
    out = await ai._narrate(ctx, system="sys", user="usr", data={"k": 1})  # type: ignore[arg-type]
    assert out["is_ai_generated"] is True
    assert out["ai_summary"] == "Sales up 10%."
    assert out["data"] == {"k": 1}
    assert "note" not in out


@pytest.mark.asyncio
async def test_narrate_falls_back_when_no_sampling() -> None:
    out = await ai._narrate(FailCtx(), system="sys", user="usr", data={"k": 1})  # type: ignore[arg-type]
    assert out["is_ai_generated"] is False
    assert out["data"] == {"k": 1}  # raw data still returned
    assert "sampling" in out["note"].lower()
    assert "ai_summary" not in out


@pytest.mark.asyncio
async def test_suggest_item_categories_wires_gather_to_sample(
    client: CloverClient, mock_http: respx.Router
) -> None:
    base = f"/v3/merchants/{TEST_MERCHANT_ID}"
    mock_http.get(f"{base}/categories").mock(
        return_value=httpx.Response(200, json={"elements": [{"id": "C1", "name": "Drinks"}]})
    )
    mock_http.get(f"{base}/items").mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {"id": "I1", "name": "Latte", "categories": {"elements": [{"id": "C1"}]}},
                    {"id": "I2", "name": "Mystery Item"},  # no categories → uncategorized
                ]
            },
        )
    )
    ctx = FakeCtx("I2 → Drinks")

    out = await ai.suggest_item_categories(client, ctx)  # type: ignore[arg-type]

    assert out["is_ai_generated"] is True
    assert out["data"]["uncategorized_count"] == 1
    assert out["data"]["uncategorized_items"][0]["name"] == "Mystery Item"
    assert "Drinks" in out["data"]["existing_categories"]
    # the bounded prompt actually carried the uncategorized item to the model
    assert "Mystery Item" in ctx.last_user
