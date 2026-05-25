"""Clover API error types and HTTP status → MCP-friendly message mapping."""

from __future__ import annotations

import httpx


class CloverAPIError(Exception):
    """Raised when the Clover API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


def raise_for_status(response: httpx.Response, *, context: str = "") -> None:
    """Parse a Clover error response and raise CloverAPIError with a clear message."""
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
        msg = f"Invalid or expired access token{ctx}. Regenerate your token or check CLOVER_ACCESS_TOKEN."
    elif code == 403:
        msg = f"Permission denied{ctx}: {clover_msg}. Check that your token has the required Clover permission scope."
    elif code == 404:
        msg = f"Resource not found{ctx}: {clover_msg}"
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
