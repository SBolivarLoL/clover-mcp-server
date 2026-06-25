"""Live protocol validation for MCP sampling + elicitation.

Connects a real fastmcp Client (with sampling + elicitation handlers) to the
server in-process. The tools call the live Clover sandbox; the server→client
sampling/elicitation requests route to our handlers over the real MCP protocol —
exactly the round-trips the unit tests can only mock.

Run: source .env first, then `.venv/bin/python scripts/validate_sampling_elicitation.py`
Requires CLOVER_SANDBOX=true (it performs one guarded create on the sandbox).
"""

import asyncio
import os

from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from clover_mcp.server import mcp

CANNED = "VALIDATION-NARRATIVE: sales look flat; top seller is the test latte."
elicit_log: list[str] = []


async def sampling_handler(messages, params, ctx):
    """Stand in for the client's model — proves ctx.sample() round-trips."""
    return CANNED


def make_elicit_handler(action: str):
    async def handler(message, response_type, params, ctx):
        elicit_log.append(message)
        return ElicitResult(action=action)

    return handler


async def main() -> None:
    assert os.getenv("CLOVER_SANDBOX", "").lower() in ("1", "true", "yes"), "sandbox only"
    ok = True

    # 1) SAMPLING — summarize_sales should return the model's narrative.
    async with Client(mcp, sampling_handler=sampling_handler) as c:
        res = await c.call_tool("summarize_sales", {})
        data = res.structured_content or {}
        print(f"[sampling] is_ai_generated={data.get('is_ai_generated')}")
        print(f"[sampling] ai_summary={data.get('ai_summary')!r}")
        if data.get("is_ai_generated") is True and CANNED in (data.get("ai_summary") or ""):
            print("  ✅ sampling round-trip works (server emitted ctx.sample, used the response)")
        else:
            ok = False
            print("  ❌ sampling did NOT round-trip")

    # 2) ELICITATION accept — create_category should write after approval.
    async with Client(mcp, elicitation_handler=make_elicit_handler("accept")) as c:
        res = await c.call_tool("create_category", {"name": "CU-Validate-Accept"})
        data = res.structured_content or {}
        print(f"\n[elicit accept] ok={data.get('ok')} prompt={elicit_log[-1:]}")
        if data.get("ok") is True and elicit_log:
            print("  ✅ elicitation round-trip works (server asked, client accepted, write done)")
        else:
            ok = False
            print("  ❌ elicitation accept path failed")

    # 3) ELICITATION decline — write must be refused, no data created.
    async with Client(mcp, elicitation_handler=make_elicit_handler("decline")) as c:
        res = await c.call_tool("create_category", {"name": "CU-Validate-Decline"})
        data = res.structured_content or {}
        print(f"\n[elicit decline] ok={data.get('ok')} reason={data.get('reason')}")
        if data.get("ok") is False and data.get("reason") == "confirmation_required":
            print("  ✅ decline correctly refuses the write (fail-closed)")
        else:
            ok = False
            print("  ❌ decline did NOT refuse")

    # 4) RESOURCE — capabilities cheat-sheet readable over the protocol.
    async with Client(mcp) as c:
        contents = await c.read_resource("clover://capabilities")
        import json

        caps = json.loads(contents[0].text)
        print(f"\n[resource] reads={caps['counts']['reads']} writes={caps['counts']['writes']} "
              f"prompts={caps['counts']['prompts']}")
        prompts = await c.list_prompts()
        print(f"[prompts] {[p.name for p in prompts]}")
        print("  ✅ resource + prompts served over the protocol")

    print("\n" + ("ALL GREEN ✅" if ok else "SOME CHECKS FAILED ❌"))


if __name__ == "__main__":
    asyncio.run(main())
