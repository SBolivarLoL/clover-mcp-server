#!/usr/bin/env python3
"""One-shot OAuth token helper for Clover sandbox.

Starts a local HTTP server on port 8080, opens the Clover authorize URL
in your browser, waits for the redirect, exchanges the code for a token,
and prints it.

Usage:
    uv run python scripts/get_sandbox_token.py
"""

import http.server
import json
import os
import threading
import urllib.parse
import urllib.request
import webbrowser
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["CLOVER_OAUTH_CLIENT_ID"]
CLIENT_SECRET = os.environ["CLOVER_OAUTH_CLIENT_SECRET"]
MERCHANT_ID = os.environ.get("CLOVER_MERCHANT_ID", "")
REDIRECT_URI = "http://localhost:8080"
AUTHORIZE_URL = f"https://sandbox.dev.clover.com/oauth/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
TOKEN_URL = "https://sandbox.dev.clover.com/oauth/token"

result: dict = {}
server_done = threading.Event()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        code = params.get("code", [None])[0]
        merchant_id = params.get("merchant_id", [MERCHANT_ID])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if not code:
            self.wfile.write(b"<h2>No code received. Check browser URL for details.</h2>")
            server_done.set()
            return

        # Exchange code for token — Clover sandbox uses GET with query params
        qs = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
        })
        req = urllib.request.Request(f"{TOKEN_URL}?{qs}", method="GET")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
            body = json.loads(raw)
            print(f"\nFull exchange response: {body}")
            token = body.get("access_token") or body.get("token")
            result["token"] = token
            result["merchant_id"] = merchant_id
            result["body"] = body
            self.wfile.write(f"<h2>Token received! You can close this tab.</h2><pre>{token}</pre>".encode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            print(f"\nExchange HTTP error {e.code}: {err_body}")
            result["error"] = f"{e.code}: {err_body}"
            self.wfile.write(f"<h2>Exchange failed {e.code}: {err_body}</h2>".encode())
        except Exception as e:
            print(f"\nExchange error: {e}")
            result["error"] = str(e)
            self.wfile.write(f"<h2>Exchange failed: {e}</h2>".encode())

        server_done.set()

    def log_message(self, *args):
        pass  # silence request logs


def main():
    print(f"\nOpening browser for Clover OAuth...\n  {AUTHORIZE_URL}\n")
    server = http.server.HTTPServer(("localhost", 8080), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    webbrowser.open(AUTHORIZE_URL)
    print("Waiting for redirect (approve the app in your browser)...")
    server_done.wait(timeout=120)
    server.shutdown()

    if "error" in result:
        print(f"\nError: {result['error']}")
    elif "token" in result:
        token = result["token"]
        mid = result["merchant_id"]
        print(f"\nExchange success. Testing token immediately...")
        test_req = urllib.request.Request(
            f"https://apisandbox.dev.clover.com/v3/merchants/{mid}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(test_req) as r:
                test_body = json.loads(r.read())
            print(f"\nAPI TEST PASSED!")
            print(f"  Merchant name: {test_body.get('name')}")
            print(f"\n  CLOVER_MERCHANT_ID={mid}")
            print(f"  CLOVER_ACCESS_TOKEN={token}")
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            print(f"\nAPI TEST FAILED (HTTP {e.code}): {err}")
            print(f"\n  Token was: {token}")
            print(f"  Merchant ID was: {mid}")
    else:
        print("\nNo token received — timed out or redirect not caught.")


if __name__ == "__main__":
    main()
