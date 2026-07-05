"""Clover API error types and HTTP status → MCP-friendly message mapping."""

from __future__ import annotations

import httpx


class ReadOnlyError(Exception):
    """Raised when a write is attempted while the server is in read-only mode
    (CLOVER_READ_ONLY=true). Refused before any HTTP call — no data is modified."""


class CloverAPIError(Exception):
    """Raised when the Clover API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


# A 404 on an id-bearing path almost always means a bad id. Map the resource to
# the read tool that lists valid ids, so the agent's next move is unambiguous.
# Keyed by the path segment that precedes the id (matched as a substring of the
# request context, e.g. "GET /items/ABC"). One authoritative home for the hints.
_NOT_FOUND_REMEDIES: dict[str, str] = {
    "/items/": "verify the item_id — call list_items to get valid ids",
    "/orders/": "verify the order_id — call list_orders or list_open_orders for valid ids",
    "/customers/": "verify the customer_id — call search_customers for valid ids",
    "/categories/": "verify the category_id — call list_categories for valid ids",
    "/employees/": "verify the employee_id — call list_employees for valid ids",
    "/line_items/": "verify the line_item_id — call get_order to list an order's line items",
}


def _not_found_remedy(context: str) -> str:
    """Return an actionable next-step hint for a 404 based on the request path,
    or "" when no resource-specific remedy applies."""
    # Longest match wins so a nested path ("/orders/O/line_items/L") gets the
    # line-item remedy, not the parent order one.
    matches = [(seg, remedy) for seg, remedy in _NOT_FOUND_REMEDIES.items() if seg in context]
    if not matches:
        return ""
    return max(matches, key=lambda m: len(m[0]))[1]


def raise_for_status(
    response: httpx.Response, *, context: str = "", auth_mode: str = "token"
) -> None:
    """Parse a Clover error response and raise CloverAPIError with a clear message.

    `auth_mode` ("token" | "oauth_refresh") only tailors the 401 remediation hint —
    errors.py stays ignorant of Config; the caller passes the mode string.
    """
    if response.is_success:
        return

    ctx = f" (while {context})" if context else ""
    retry_after: int | None = None

    try:
        body = response.json()
        # Clover wraps errors as {"message": "..."} or {"error": {"message": "..."}}
        if isinstance(body, dict):
            clover_msg = (
                body.get("message") or (body.get("error") or {}).get("message") or response.text
            )
        else:
            clover_msg = response.text
    except Exception:
        clover_msg = response.text or f"HTTP {response.status_code}"

    code = response.status_code

    if code == 401:
        if auth_mode == "oauth_refresh":
            msg = (
                f"Invalid or expired access token{ctx}. The OAuth refresh failed or the "
                "grant was revoked — re-run your token provisioning (scripts/get_sandbox_token.py) "
                "or check the refresh grant / CLOVER_OAUTH_CLIENT_ID."
            )
        else:
            msg = (
                f"Invalid or expired access token{ctx}. "
                "Regenerate your token or check CLOVER_ACCESS_TOKEN."
            )
    elif code == 403:
        msg = f"Permission denied{ctx}: {clover_msg}. Check that your token has the required Clover permission scope."
    elif code == 404:
        msg = f"Resource not found{ctx}: {clover_msg}"
        remedy = _not_found_remedy(context)
        if remedy:
            msg += f" — {remedy}"
    elif code == 429:
        raw = response.headers.get("Retry-After", "")
        retry_after = int(raw) if raw.isdigit() else None
        wait = f" Retry after {retry_after}s." if retry_after else ""
        msg = f"Rate limited by Clover{ctx}.{wait}"
    elif 400 <= code < 500:
        msg = f"Bad request (HTTP {code}){ctx}: {clover_msg}"
    else:
        msg = f"Clover service error (HTTP {code}){ctx}: {clover_msg}"

    raise CloverAPIError(code, msg, retry_after=retry_after)
