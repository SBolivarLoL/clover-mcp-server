#!/usr/bin/env python3
"""One-shot OAuth v2 (expiring-token) helper for the Clover sandbox.

Runs the authorization-code flow: starts a local server on port 8080, opens the
Clover consent page, catches the redirect, exchanges the code at the v2 token
endpoint, and returns an **expiring access token + refresh token** pair (unlike
the legacy non-expiring merchant token).

It writes the pair to the oauth_refresh token store and prints the .env lines.

Prereqs (already set for this app):
  - App redirect URI / Site URL = http://localhost:8080
  - CLOVER_OAUTH_CLIENT_ID and CLOVER_OAUTH_CLIENT_SECRET in .env

Usage:
    uv run python scripts/get_sandbox_token.py
"""

import contextlib
import http.server
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from clover_mcp.auth import TokenStore

load_dotenv()

CLIENT_ID = os.environ["CLOVER_OAUTH_CLIENT_ID"]
CLIENT_SECRET = os.environ["CLOVER_OAUTH_CLIENT_SECRET"]
REDIRECT_URI = "http://localhost:8080"

# v2 expiring-token flow (sandbox). Consent page is on sandbox.dev.clover.com;
# the token exchange is on the API host apisandbox.dev.clover.com.
AUTHORIZE_URL = (
    "https://sandbox.dev.clover.com/oauth/v2/authorize?"
    + urllib.parse.urlencode(
        {"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code"}
    )
)
TOKEN_URL = "https://apisandbox.dev.clover.com/oauth/v2/token"
TOKEN_STORE = Path("~/.config/clover-mcp/tokens.json").expanduser()

result: dict = {}
server_done = threading.Event()


def _fmt(ts: object) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).isoformat()
    except Exception:
        return str(ts)


def _exchange(code: str) -> dict:
    body = json.dumps(
        {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code}
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        print(f"  ← request hit the port: {self.path}")

        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        merchant_id = params.get("merchant_id", [""])[0]

        # Ignore stray requests (e.g. /favicon.ico) so they don't abort the wait
        if not code and not error and parsed.path not in ("/", ""):
            self.send_response(204)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if error:
            desc = params.get("error_description", [""])[0]
            result["error"] = f"OAuth redirect error: {error} {desc}".strip()
            self.wfile.write(f"<h2>OAuth error: {error}</h2><pre>{desc}</pre>".encode())
            server_done.set()
            return

        if not code:
            self.wfile.write(b"<h2>Reached localhost:8080 but no code in the URL.</h2>")
            return  # don't abort — wait for the real redirect

        try:
            tokens = _exchange(code)
            result["tokens"] = tokens
            result["merchant_id"] = merchant_id
            self.wfile.write(b"<h2>Tokens received. You can close this tab.</h2>")
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            err = e.read().decode()
            result["error"] = f"{e.code}: {err}"
            self.wfile.write(f"<h2>Exchange failed {e.code}</h2><pre>{err}</pre>".encode())
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
            self.wfile.write(f"<h2>Exchange failed: {e}</h2>".encode())

        server_done.set()

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    print(
        "\nOpening (or copy manually) the consent page:\n\n"
        "  https://sandbox.dev.clover.com/oauth/v2/authorize\n"
    )
    server = http.server.HTTPServer(("localhost", 8080), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with contextlib.suppress(Exception):
        webbrowser.open(AUTHORIZE_URL)
    print("Waiting up to 10 minutes for the redirect to http://localhost:8080 ...")
    print("(Take your time approving — the server stays up. Ctrl-C to abort.)")
    server_done.wait(timeout=600)
    server.shutdown()

    if "error" in result:
        print(f"\n❌ Exchange error: {result['error']}")
        return
    if "tokens" not in result:
        print("\n❌ No tokens received — timed out or redirect not caught.")
        return

    t = result["tokens"]
    access = t["access_token"]
    refresh = t["refresh_token"]
    mid = result["merchant_id"]

    TokenStore(TOKEN_STORE).save({"access_token": access, "refresh_token": refresh})

    print("\n✅ Expiring tokens received and written to", TOKEN_STORE)
    print(f"   access_token  expires {_fmt(t.get('access_token_expiration'))}")
    print(f"   refresh_token expires {_fmt(t.get('refresh_token_expiration'))}")
    print("\nAdd these to .env to use oauth_refresh mode:\n")
    print("  CLOVER_AUTH_MODE=oauth_refresh")
    if mid:
        print(f"  CLOVER_MERCHANT_ID={mid}")
    print(f"  CLOVER_ACCESS_TOKEN={access}")
    print(f"  CLOVER_REFRESH_TOKEN={refresh}")
    print("\n(CLOVER_OAUTH_CLIENT_ID / CLOVER_OAUTH_CLIENT_SECRET are already set.)")


if __name__ == "__main__":
    main()
