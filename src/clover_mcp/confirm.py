"""Layer 4 — mid-tool write confirmation via MCP elicitation.

Guarded-write tools call `confirm_write()` after validation and before the
mutating request. It asks the user to approve through the client's elicitation
UI (`ctx.elicit`). This is the MCP-native guardrail for writes — preferred over
relying only on `dry_run` and the client's own prompting.

Fail-closed: if the client can't elicit (capability absent or it errors), the
write proceeds ONLY when the caller passed `confirm=True` explicitly. With
neither an accepted elicitation nor an explicit confirm, the write is refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.server.elicitation import AcceptedElicitation

if TYPE_CHECKING:
    from fastmcp import Context


async def confirm_write(ctx: Context | None, message: str, *, confirm: bool) -> tuple[bool, str]:
    """Return (approved, how). `how` is one of: explicit_confirm, elicited_accept,
    elicited_declined, elicitation_unsupported, no_context.

    `confirm=True` is an explicit caller override and approves without prompting
    (for clients that gate writes their own way or for non-interactive use)."""
    if confirm:
        return True, "explicit_confirm"
    if ctx is None:
        return False, "no_context"
    try:
        # No response payload needed — a yes/no accept/decline is all we want.
        result = await ctx.elicit(message, response_type=None)
    except Exception:  # noqa: BLE001 — capability absent / transport error → fail closed
        return False, "elicitation_unsupported"
    if isinstance(result, AcceptedElicitation):
        return True, "elicited_accept"
    return False, "elicited_declined"


def confirmation_required(how: str) -> dict[str, object]:
    """Standard refusal payload when a write was not confirmed."""
    return {
        "ok": False,
        "reason": "confirmation_required",
        "how": how,
        "message": (
            "Write not performed — it was not confirmed. Approve it through your "
            "client's confirmation prompt (MCP elicitation), or call again with "
            "confirm=True to explicitly authorize it."
        ),
    }
