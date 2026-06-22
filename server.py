"""FastMCP Cloud entrypoint (repo root).

Deploy with entrypoint  ``server.py:create_server``  —  a fail-closed factory
that always builds the OAuth resource server and refuses to start without an IdP
(so a hosted HTTP deploy can never serve unauthenticated). See docs/DEPLOY.md.

``server.py:mcp`` is also exported for local/inferred use, but on a hosted
deploy prefer the factory.
"""

from clover_mcp.server import create_server, mcp

__all__ = ["create_server", "mcp"]
